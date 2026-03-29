from __future__ import annotations

import json
import math
import queue
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Iterator
from uuid import uuid4

import cv2
try:
    import psutil  # type: ignore
except ImportError:  # pragma: no cover
    psutil = None

from .camera import CameraSource
from .config import Settings, save_settings, settings_to_dict
from .detector import DetectorBackend, create_detector
from .mmwave import MmwaveSource
from .models import (
    CameraStatus,
    CountConfidence,
    CrossingDirection,
    CrossingEvent,
    CrossingIntensityBand,
    EntranceLoadLevel,
    FramePacket,
    MetricsSnapshot,
    MmwaveStatus,
    PipelineTimingsMs,
    PresenceCorroborationState,
    StatusPayload,
    SystemState,
    TrackObservation,
    ValidationSessionPayload,
    ValidationSessionRecord,
    ValidationState,
    WarningFlag,
)
from .storage import StorageWriter
from .tracking import CentroidTracker, LineCrossingCounter
from .utils import RatioWindow, TimedFlag, isoformat, median_int, utc_now


class SseHub:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._subscribers: dict[int, queue.Queue[tuple[datetime, str]]] = {}
        self._next_id = 1

    def subscribe(self) -> tuple[int, queue.Queue[tuple[datetime, str]]]:
        with self._lock:
            sub_id = self._next_id
            self._next_id += 1
            q: queue.Queue[tuple[datetime, str]] = queue.Queue(maxsize=32)
            self._subscribers[sub_id] = q
            return sub_id, q

    def unsubscribe(self, sub_id: int) -> None:
        with self._lock:
            self._subscribers.pop(sub_id, None)

    def publish(self, payload: str) -> None:
        now = utc_now()
        with self._lock:
            for q in self._subscribers.values():
                if q.full():
                    try:
                        q.get_nowait()
                    except queue.Empty:
                        pass
                try:
                    q.put_nowait((now, payload))
                except queue.Full:
                    pass

    def backlog_age_ms(self) -> int:
        now = utc_now()
        oldest: int = 0
        with self._lock:
            for q in self._subscribers.values():
                if q.empty():
                    continue
                try:
                    ts, _ = q.queue[0]  # type: ignore[attr-defined]
                except Exception:
                    continue
                oldest = max(oldest, int((now - ts).total_seconds() * 1000))
        return oldest


@dataclass
class RuntimeState:
    started_at: datetime
    last_camera_metric_ts: datetime | None = None
    last_snapshot_ts: datetime | None = None
    last_detector_run_ts: datetime | None = None
    last_processed_frame_id: int = 0
    gated_mode: bool = False
    publish_backlog_since: datetime | None = None
    publish_recover_since: datetime | None = None
    publish_degraded_active: bool = False
    mmwave_state_since: datetime | None = None
    last_mmwave_state: PresenceCorroborationState = PresenceCorroborationState.UNKNOWN
    latest_timings: PipelineTimingsMs = field(default_factory=PipelineTimingsMs)


@dataclass
class ValidationSessionState:
    session_id: str | None = None
    active: bool = False
    started_at: datetime | None = None
    ended_at: datetime | None = None
    saved_at: datetime | None = None
    persisted: bool = False
    manual_entry_count: int = 0
    manual_exit_count: int = 0
    system_entry_count: int = 0
    system_exit_count: int = 0
    recent_events: deque[CrossingEvent] = field(default_factory=lambda: deque(maxlen=200))


class EdgeService:
    def __init__(self, settings: Settings, config_path: str | Path | None = None) -> None:
        self.settings = settings
        self.config_path = None if config_path is None else Path(config_path)
        self.camera = CameraSource(settings.camera)
        self.mmwave = MmwaveSource(settings.mmwave)
        self.detector: DetectorBackend = create_detector(settings.detector)
        self.tracker = CentroidTracker()
        self.counter = LineCrossingCounter(
            line=(
                settings.camera.line.x1,
                settings.camera.line.y1,
                settings.camera.line.x2,
                settings.camera.line.y2,
            ),
            cooldown_seconds=settings.camera.crossing_cooldown_seconds,
            hysteresis_px=float(settings.camera.line_hysteresis_px),
            min_track_hits=settings.camera.min_track_hits_for_crossing,
            confirm_frames=settings.camera.crossing_confirm_frames,
        )
        self.storage = StorageWriter(
            sqlite_path=settings.storage.sqlite_path,
            retention_days=settings.storage.retention_days,
        )
        self.sse = SseHub()
        self.state = RuntimeState(started_at=utc_now())
        self._running = threading.Event()
        self._thread: threading.Thread | None = None
        self._events_30s: deque[CrossingEvent] = deque()
        self._recent_events: deque[CrossingEvent] = deque(maxlen=200)
        self._active_track_samples: deque[tuple[datetime, int]] = deque()
        self._detector_run_samples: deque[datetime] = deque()
        self._drop_ratio = RatioWindow(settings.runtime.window_seconds)
        self._thermal_flag = TimedFlag()
        self._undervoltage_flag = TimedFlag()
        self._latest_snapshot: MetricsSnapshot | None = None
        self._latest_status: StatusPayload | None = None
        self._latest_frame: object | None = None
        self._latest_packet: FramePacket | None = None
        self._latest_detections_count: int = 0
        self._latest_tracks: list[TrackObservation] = []
        self._validation_session = ValidationSessionState()
        self._lock = threading.Lock()

    def start(self) -> None:
        self.storage.start()
        # Camera starts OFF; mmwave presence wakes it (edge power-gating)
        self._camera_powered = False
        self.mmwave.start()
        self._running.set()
        self._thread = threading.Thread(target=self._run, name="edge-service", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._running.clear()
        if self._thread:
            self._thread.join(timeout=2)
        if self._camera_powered:
            self.camera.stop()
        self.mmwave.stop()
        self.storage.stop()

    def latest_status(self) -> StatusPayload | None:
        with self._lock:
            return self._latest_status

    def latest_snapshot(self) -> MetricsSnapshot | None:
        with self._lock:
            return self._latest_snapshot

    def recent_events(self, limit: int = 50) -> list[dict]:
        if self._recent_events:
            recent = list(self._recent_events)[-limit:]
            return [event.model_dump(mode="json") for event in reversed(recent)]
        return self.storage.recent_events(limit=limit)

    def history(self, minutes: int) -> list[dict]:
        return self.storage.history(minutes)

    def validation_payload(self, limit: int = 50) -> ValidationSessionPayload:
        with self._lock:
            session = self._validation_session
            state = ValidationState.NOT_STARTED
            if session.started_at is not None:
                state = ValidationState.RUNNING if session.active else ValidationState.COMPLETED
            ended_at = session.ended_at
            now = utc_now()
            duration_source = ended_at or now
            duration_seconds = 0.0
            if session.started_at is not None:
                duration_seconds = max(0.0, (duration_source - session.started_at).total_seconds())
            recent_events = list(session.recent_events)[-limit:]
            manual_total = session.manual_entry_count + session.manual_exit_count
            system_total = session.system_entry_count + session.system_exit_count
            return ValidationSessionPayload(
                schema_version=self.settings.app.schema_version,
                session_id=session.session_id,
                state=state,
                active=session.active,
                started_at=session.started_at,
                ended_at=ended_at,
                saved_at=session.saved_at,
                duration_seconds=duration_seconds,
                manual_entry_count=session.manual_entry_count,
                manual_exit_count=session.manual_exit_count,
                manual_total_count=manual_total,
                system_entry_count=session.system_entry_count,
                system_exit_count=session.system_exit_count,
                system_total_count=system_total,
                entry_error=session.system_entry_count - session.manual_entry_count,
                exit_error=session.system_exit_count - session.manual_exit_count,
                total_error=system_total - manual_total,
                recent_events=list(reversed(recent_events)),
            )

    def start_validation_session(self) -> ValidationSessionPayload:
        with self._lock:
            if self._validation_session.active:
                raise ValueError("Validation session is already running.")
            self._validation_session = ValidationSessionState(
                session_id=f"vs-{uuid4().hex[:12]}",
                active=True,
                started_at=utc_now(),
            )
        return self.validation_payload()

    def stop_validation_session(self) -> ValidationSessionPayload:
        should_persist = False
        with self._lock:
            if self._validation_session.started_at is None:
                raise ValueError("Validation session has not started.")
            if self._validation_session.active:
                self._validation_session.active = False
                self._validation_session.ended_at = utc_now()
            elif self._validation_session.ended_at is None:
                self._validation_session.ended_at = utc_now()
            should_persist = not self._validation_session.persisted
        payload = self.validation_payload()
        if should_persist and payload.session_id is not None:
            saved_at = self._persist_validation_session(payload)
            with self._lock:
                self._validation_session.persisted = True
                self._validation_session.saved_at = saved_at
            payload = self.validation_payload()
        return payload

    def reset_validation_session(self) -> ValidationSessionPayload:
        with self._lock:
            self._validation_session = ValidationSessionState()
        return self.validation_payload()

    def add_manual_validation_count(self, direction: CrossingDirection) -> ValidationSessionPayload:
        with self._lock:
            if not self._validation_session.active:
                raise ValueError("Start validation session first.")
            if direction == CrossingDirection.ENTRY:
                self._validation_session.manual_entry_count += 1
            else:
                self._validation_session.manual_exit_count += 1
        return self.validation_payload()

    def validation_history(self, limit: int = 20) -> list[ValidationSessionRecord]:
        items = self.storage.validation_sessions(limit=limit)
        return [ValidationSessionRecord.model_validate(item) for item in items]

    def settings_payload(self) -> dict:
        return {
            "schema_version": self.settings.app.schema_version,
            "config_path": None if self.config_path is None else str(self.config_path),
            "camera": {
                "source": self.settings.camera.source,
                "backend": self.settings.camera.backend,
                "width": self.settings.camera.width,
                "height": self.settings.camera.height,
                "fps": self.settings.camera.fps,
                "roi": self.settings.camera.roi.model_dump(),
                "line": self.settings.camera.line.model_dump(),
                "detector_fps_normal": self.settings.camera.detector_fps_normal,
                "detector_fps_gated": self.settings.camera.detector_fps_gated,
                "crossing_cooldown_seconds": self.settings.camera.crossing_cooldown_seconds,
                "line_hysteresis_px": self.settings.camera.line_hysteresis_px,
                "min_detection_width_px": self.settings.camera.min_detection_width_px,
                "min_detection_height_px": self.settings.camera.min_detection_height_px,
                "detection_edge_margin_px": self.settings.camera.detection_edge_margin_px,
                "min_track_hits_for_crossing": self.settings.camera.min_track_hits_for_crossing,
                "crossing_confirm_frames": self.settings.camera.crossing_confirm_frames,
                "active_track_promote_threshold": self.settings.camera.active_track_promote_threshold,
                "active_track_promote_seconds": self.settings.camera.active_track_promote_seconds,
            },
            "detector": {
                "backend": self.settings.detector.backend,
                "model_path": self.settings.detector.model_path,
                "confidence_threshold": self.settings.detector.confidence_threshold,
                "imgsz": self.settings.detector.imgsz,
            },
            "runtime": {
                "crossing_band_medium_threshold": self.settings.runtime.crossing_band_medium_threshold,
                "crossing_band_high_threshold": self.settings.runtime.crossing_band_high_threshold,
            },
        }

    def update_editable_settings(self, payload: dict) -> dict:
        with self._lock:
            candidate = self.settings.model_copy(deep=True)
        camera_payload = payload.get("camera", {})
        detector_payload = payload.get("detector", {})
        runtime_payload = payload.get("runtime", {})

        roi_payload = camera_payload.get("roi", {})
        line_payload = camera_payload.get("line", {})

        for field in ("x1", "y1", "x2", "y2"):
            if field in roi_payload:
                setattr(candidate.camera.roi, field, int(roi_payload[field]))
            if field in line_payload:
                setattr(candidate.camera.line, field, int(line_payload[field]))

        for field in (
            "detector_fps_normal",
            "detector_fps_gated",
            "crossing_cooldown_seconds",
            "line_hysteresis_px",
            "min_detection_width_px",
            "min_detection_height_px",
            "detection_edge_margin_px",
            "min_track_hits_for_crossing",
            "crossing_confirm_frames",
            "active_track_promote_threshold",
            "active_track_promote_seconds",
        ):
            if field in camera_payload:
                current = getattr(candidate.camera, field)
                setattr(candidate.camera, field, type(current)(camera_payload[field]))

        for field in ("confidence_threshold", "imgsz"):
            if field in detector_payload:
                current = getattr(candidate.detector, field)
                setattr(candidate.detector, field, type(current)(detector_payload[field]))

        for field in ("crossing_band_medium_threshold", "crossing_band_high_threshold"):
            if field in runtime_payload:
                current = getattr(candidate.runtime, field)
                setattr(candidate.runtime, field, type(current)(runtime_payload[field]))

        self._validate_editable_settings(candidate)
        if self.config_path is not None:
            save_settings(self.config_path, candidate)
        with self._lock:
            self.settings = candidate
            self.counter.cooldown_seconds = candidate.camera.crossing_cooldown_seconds
            self.counter.hysteresis_px = float(candidate.camera.line_hysteresis_px)
            self.counter.min_track_hits = candidate.camera.min_track_hits_for_crossing
            self.counter.confirm_frames = candidate.camera.crossing_confirm_frames
            self.detector.apply_config(candidate.detector)
            return self.settings_payload()

    def subscribe_stream(self) -> Iterator[str]:
        sub_id, q = self.sse.subscribe()
        try:
            while True:
                try:
                    _, payload = q.get(timeout=15.0)
                except queue.Empty:
                    yield ": keep-alive\n\n"
                    continue
                yield f"data: {payload}\n\n"
        finally:
            self.sse.unsubscribe(sub_id)

    def _timings_with_updates(self, **updates: float | None) -> PipelineTimingsMs:
        timings = self.state.latest_timings.model_copy(deep=True)
        for key, value in updates.items():
            if value is None:
                setattr(timings, key, None)
            else:
                setattr(timings, key, round(float(value), 2))
        return timings

    def _run(self) -> None:
        while self._running.is_set():
            now = utc_now()
            self._refresh_mmwave_state(now)
            self._update_camera_power(now)
            self._process_camera(now)
            self._emit_snapshot_if_due(now)
            time.sleep(0.02)

    def _update_camera_power(self, now: datetime) -> None:
        """Power camera on when mmwave detects presence; power off when absent."""
        mmwave_status = self._compute_mmwave_status(now)
        present = (
            mmwave_status == MmwaveStatus.OK
            and self.state.last_mmwave_state == PresenceCorroborationState.PRESENT
        )
        if present and not self._camera_powered:
            self.camera.start()
            self._camera_powered = True
        elif not present and self._camera_powered:
            # Delay power-down until absence is confirmed for low_activity_absent_seconds
            if self._presence_absent_for(now) >= self.settings.runtime.low_activity_absent_seconds:
                self.camera.stop()
                self._camera_powered = False
                self.state.last_processed_frame_id = 0
                self.state.last_detector_run_ts = None

    def _refresh_mmwave_state(self, now: datetime) -> None:
        sample = self.mmwave.latest()
        state = PresenceCorroborationState.UNKNOWN if sample is None else sample.state
        if self.state.mmwave_state_since is None:
            self.state.mmwave_state_since = now
            self.state.last_mmwave_state = state
            return
        if state != self.state.last_mmwave_state:
            self.state.last_mmwave_state = state
            self.state.mmwave_state_since = now

    def _process_camera(self, now: datetime) -> None:
        process_started = time.perf_counter()
        packet = self.camera.latest()
        if packet is None:
            return
        if packet.frame_id == self.state.last_processed_frame_id:
            return
        frame_gap = packet.frame_id - self.state.last_processed_frame_id
        if self.state.last_processed_frame_id != 0 and self.camera.stats.source_kind != "video":
            dropped = max(0, frame_gap - 1)
            self._drop_ratio.add(now, numerator=dropped, denominator=max(frame_gap, 1))
        self.state.last_processed_frame_id = packet.frame_id
        detector_interval = 1.0 / self._current_detector_fps(now)
        if self.state.last_detector_run_ts is not None:
            if (now - self.state.last_detector_run_ts).total_seconds() < detector_interval:
                return
        self.state.last_detector_run_ts = now
        self._detector_run_samples.append(now)
        self.counter.line = self._roi_local_line(packet)
        capture_to_service_ms = max(0.0, (now - packet.ts).total_seconds() * 1000.0)
        detection_packet = self.detector.detect(packet.frame_id, packet.ts, packet.roi_image)
        filter_started = time.perf_counter()
        detection_packet.detections = self._filter_detections(packet, detection_packet.detections)
        filter_ms = (time.perf_counter() - filter_started) * 1000.0
        tracking_started = time.perf_counter()
        observations = self.tracker.update(detection_packet.detections, detection_packet.ts)
        self.counter.prune(self.tracker.active_track_ids())
        tracking_ms = (time.perf_counter() - tracking_started) * 1000.0
        crossing_started = time.perf_counter()
        events = self.counter.update(observations, detection_packet.ts)
        crossing_ms = (time.perf_counter() - crossing_started) * 1000.0
        enqueue_started = time.perf_counter()
        for event in events:
            self._events_30s.append(event)
            self._recent_events.append(event)
            self._record_validation_event(event)
            self.storage.enqueue_event(event)
        event_enqueue_ms = (time.perf_counter() - enqueue_started) * 1000.0
        self._prune_old_windows(now)
        self._active_track_samples.append((now, len(observations)))
        self.state.last_camera_metric_ts = now
        if packet.image is not None:
            self._latest_frame = packet.image.copy()
        self._latest_packet = packet
        self._latest_detections_count = len(detection_packet.detections)
        self._latest_tracks = observations
        self.state.latest_timings = self._timings_with_updates(
            camera_read_ms=self.camera.stats.last_read_ms,
            capture_to_service_ms=capture_to_service_ms,
            detector_preprocess_ms=detection_packet.preprocess_ms,
            detector_inference_ms=detection_packet.inference_ms,
            detector_postprocess_ms=detection_packet.postprocess_ms,
            detector_total_ms=detection_packet.total_ms,
            filter_ms=filter_ms,
            tracking_ms=tracking_ms,
            crossing_ms=crossing_ms,
            event_enqueue_ms=event_enqueue_ms,
            process_camera_total_ms=(time.perf_counter() - process_started) * 1000.0,
        )

    def _prune_old_windows(self, now: datetime) -> None:
        while self._events_30s and (now - self._events_30s[0].ts).total_seconds() > self.settings.runtime.window_seconds:
            self._events_30s.popleft()
        while self._active_track_samples and (
            now - self._active_track_samples[0][0]
        ).total_seconds() > self.settings.runtime.active_track_window_seconds:
            self._active_track_samples.popleft()
        while self._detector_run_samples and (now - self._detector_run_samples[0]).total_seconds() > 1.0:
            self._detector_run_samples.popleft()

    def _current_detector_fps(self, now: datetime) -> float:
        mmwave_status = self._compute_mmwave_status(now)
        presence = (
            self.state.last_mmwave_state
            if mmwave_status == MmwaveStatus.OK
            else PresenceCorroborationState.UNKNOWN
        )
        active_tracks = median_int(count for _, count in self._active_track_samples)
        crossings = len(self._events_30s)
        gated = (
            mmwave_status == MmwaveStatus.OK
            and presence == PresenceCorroborationState.ABSENT
            and active_tracks == 0
            and crossings == 0
            and self._compute_camera_status(now) == CameraStatus.OK
            and self._presence_absent_for(now) >= self.settings.runtime.low_activity_absent_seconds
        )
        self.state.gated_mode = gated
        return (
            self.settings.camera.detector_fps_gated
            if gated
            else self.settings.camera.detector_fps_normal
        )

    def _presence_absent_for(self, now: datetime) -> float:
        if self.state.last_mmwave_state != PresenceCorroborationState.ABSENT or self.state.mmwave_state_since is None:
            return 0.0
        return max(0.0, (now - self.state.mmwave_state_since).total_seconds())

    def _emit_snapshot_if_due(self, now: datetime) -> None:
        if self.state.last_snapshot_ts is not None:
            if (now - self.state.last_snapshot_ts).total_seconds() < self.settings.runtime.snapshot_interval_seconds:
                return
        snapshot = self._build_snapshot(now)
        status = self._build_status(now, snapshot)
        self.storage.enqueue_snapshot(snapshot)
        publish_started = time.perf_counter()
        self.sse.publish(snapshot.model_dump_json())
        sse_publish_ms = (time.perf_counter() - publish_started) * 1000.0
        final_timings = self._timings_with_updates(sse_publish_ms=sse_publish_ms)
        status.timings_ms = final_timings
        with self._lock:
            self.state.latest_timings = final_timings
            self._latest_snapshot = snapshot
            self._latest_status = status
        self.state.last_snapshot_ts = now

    def _build_status(self, now: datetime, snapshot: MetricsSnapshot) -> StatusPayload:
        cpu, ram_mb, temperature_c = self._read_system_metrics()
        target_detector_fps = self._current_detector_fps(now)
        publish_backlog_ms = self._publish_backlog_age_ms()
        return StatusPayload(
            schema_version=self.settings.app.schema_version,
            ts=now,
            camera_status=snapshot.camera_status,
            mmwave_status=snapshot.mmwave_status,
            system_state=snapshot.system_state,
            audio_disabled=True,
            freshness_ms=snapshot.freshness_ms,
            warning_flags=snapshot.warning_flags,
            count_confidence=snapshot.count_confidence,
            camera_source=str(self.settings.camera.source),
            frame_width=snapshot.frame_width,
            frame_height=snapshot.frame_height,
            delivered_fps=self.camera.stats.delivered_fps,
            detector_fps=self._detector_fps(now),
            target_capture_fps=self.camera.stats.expected_fps if self.camera.stats.expected_fps >= 1.0 else float(self.settings.camera.fps),
            target_detector_fps=target_detector_fps,
            drop_ratio_30s=self._drop_ratio.ratio(now),
            publish_backlog_ms=publish_backlog_ms,
            detector_mode=self.settings.detector.backend,
            gated_mode=self.state.gated_mode,
            cpu_percent=cpu,
            ram_mb=ram_mb,
            temperature_c=temperature_c,
            timings_ms=self.state.latest_timings,
        )

    def _build_snapshot(self, now: datetime) -> MetricsSnapshot:
        self._prune_old_windows(now)
        packet = self.camera.latest()
        entry_count = sum(1 for event in self._events_30s if event.direction == CrossingDirection.ENTRY)
        exit_count = sum(1 for event in self._events_30s if event.direction == CrossingDirection.EXIT)
        crossing_count = entry_count + exit_count
        net_count = entry_count - exit_count
        active_tracks_median = median_int(count for _, count in self._active_track_samples)
        base_band = self._crossing_band(crossing_count)
        load_level = self._entrance_load_level(now, base_band, active_tracks_median)
        camera_status = self._compute_camera_status(now)
        mmwave_status = self._compute_mmwave_status(now)
        presence_state = self._presence_state(mmwave_status)
        warning_flags = self._warning_flags(now, camera_status, mmwave_status, active_tracks_median, crossing_count)
        confidence = self._count_confidence(now, camera_status, warning_flags)
        system_state = self._system_state(now, camera_status, mmwave_status)
        freshness_ms = self._freshness_ms(now)
        return MetricsSnapshot(
            schema_version=self.settings.app.schema_version,
            ts=now,
            camera_status=camera_status,
            mmwave_status=mmwave_status,
            system_state=system_state,
            audio_disabled=True,
            freshness_ms=freshness_ms,
            entry_count_30s=entry_count,
            exit_count_30s=exit_count,
            net_count_30s=net_count,
            crossing_count_30s=crossing_count,
            active_tracks_5s_median=active_tracks_median,
            crossing_intensity_band_30s=base_band,
            presence_corroboration_state=presence_state,
            entrance_load_level=load_level,
            count_confidence=confidence,
            warning_flags=warning_flags,
            entry_rate_per_min=entry_count * 2,
            exit_rate_per_min=exit_count * 2,
            net_flow_per_min=net_count * 2,
            frame_width=0 if packet is None else packet.width,
            frame_height=0 if packet is None else packet.height,
            delivered_fps=self.camera.stats.delivered_fps,
            detector_fps=self._detector_fps(now),
            gated_mode=self.state.gated_mode,
        )

    def _freshness_ms(self, now: datetime) -> int:
        if self.state.last_camera_metric_ts is None:
            return self.settings.runtime.camera_disconnect_age_ms + 1
        return int((now - self.state.last_camera_metric_ts).total_seconds() * 1000)

    def _compute_camera_status(self, now: datetime) -> CameraStatus:
        last = self.camera.stats.last_frame_ts
        if last is None:
            return CameraStatus.DISCONNECTED
        age_ms = int((now - last).total_seconds() * 1000)
        if age_ms > self.settings.runtime.camera_disconnect_age_ms:
            return CameraStatus.DISCONNECTED
        if age_ms > self.settings.runtime.camera_stale_age_ms:
            return CameraStatus.STALE
        drop_ratio = self._drop_ratio.ratio(now)
        expected_fps = self.camera.stats.expected_fps if self.camera.stats.expected_fps >= 1.0 else float(self.settings.camera.fps)
        fps_floor = expected_fps * 0.6
        if drop_ratio > self.settings.runtime.high_drop_ratio_threshold or (
            self.camera.stats.delivered_fps > 0 and self.camera.stats.delivered_fps < fps_floor
        ):
            return CameraStatus.DEGRADED
        return CameraStatus.OK

    def _compute_mmwave_status(self, now: datetime) -> MmwaveStatus:
        sample = self.mmwave.latest()
        if sample is None or self.mmwave.stats.last_sample_ts is None:
            return MmwaveStatus.DISCONNECTED
        age_ms = int((now - self.mmwave.stats.last_sample_ts).total_seconds() * 1000)
        if age_ms > self.settings.runtime.mmwave_disconnect_age_ms:
            return MmwaveStatus.DISCONNECTED
        if age_ms > self.settings.runtime.mmwave_stale_age_ms:
            return MmwaveStatus.STALE
        if self.mmwave.error_ratio(now) > 0.05:
            return MmwaveStatus.DEGRADED
        return MmwaveStatus.OK

    def _presence_state(self, mmwave_status: MmwaveStatus) -> PresenceCorroborationState:
        sample = self.mmwave.latest()
        if sample is None or mmwave_status != MmwaveStatus.OK:
            return PresenceCorroborationState.UNKNOWN
        return sample.state

    def _warning_flags(
        self,
        now: datetime,
        camera_status: CameraStatus,
        mmwave_status: MmwaveStatus,
        active_tracks_median: int,
        crossing_count: int,
    ) -> list[WarningFlag]:
        flags: list[WarningFlag] = []
        uptime = (now - self.state.started_at).total_seconds()
        if uptime < self.settings.runtime.warmup_seconds:
            flags.append(WarningFlag.WARMUP_WINDOW)
        if self._drop_ratio.ratio(now) > self.settings.runtime.high_drop_ratio_threshold:
            flags.append(WarningFlag.HIGH_DROP_RATE)
        if camera_status == CameraStatus.STALE:
            flags.append(WarningFlag.CAMERA_STALE)
        if camera_status == CameraStatus.DISCONNECTED:
            flags.append(WarningFlag.CAMERA_DISCONNECTED)
        if mmwave_status == MmwaveStatus.STALE:
            flags.append(WarningFlag.MMWAVE_STALE)
        if self._mmwave_disagreement(now, active_tracks_median, crossing_count, mmwave_status):
            flags.append(WarningFlag.MMWAVE_DISAGREEMENT)
        throttled, undervoltage = self._read_pi_flags()
        if throttled:
            flags.append(WarningFlag.THERMAL_THROTTLE)
        if undervoltage:
            flags.append(WarningFlag.UNDERVOLTAGE)
        if self._publish_backlog_age_ms() > self.settings.runtime.publish_backlog_ms:
            flags.append(WarningFlag.PUBLISH_BACKLOG)
        return flags

    def _mmwave_disagreement(
        self,
        now: datetime,
        active_tracks_median: int,
        crossing_count: int,
        mmwave_status: MmwaveStatus,
    ) -> bool:
        if mmwave_status != MmwaveStatus.OK or self.state.mmwave_state_since is None:
            return False
        absent_for = self._presence_absent_for(now)
        state_for = max(0.0, (now - self.state.mmwave_state_since).total_seconds())
        if (
            self.state.last_mmwave_state == PresenceCorroborationState.PRESENT
            and active_tracks_median == 0
            and crossing_count == 0
            and state_for >= self.settings.runtime.disagreement_present_seconds
        ):
            return True
        if (
            self.state.last_mmwave_state == PresenceCorroborationState.ABSENT
            and active_tracks_median >= 1
            and absent_for >= self.settings.runtime.disagreement_absent_seconds
        ):
            return True
        return False

    def _count_confidence(
        self,
        now: datetime,
        camera_status: CameraStatus,
        warning_flags: list[WarningFlag],
    ) -> CountConfidence:
        freshness_ms = self._freshness_ms(now)
        if camera_status in {CameraStatus.STALE, CameraStatus.DISCONNECTED}:
            return CountConfidence.UNKNOWN
        if freshness_ms > self.settings.runtime.freshness_unknown_ms:
            return CountConfidence.UNKNOWN
        if camera_status == CameraStatus.OK and freshness_ms <= self.settings.runtime.freshness_high_ms:
            if WarningFlag.HIGH_DROP_RATE not in warning_flags and WarningFlag.THERMAL_THROTTLE not in warning_flags and WarningFlag.UNDERVOLTAGE not in warning_flags:
                return CountConfidence.HIGH
        return CountConfidence.REDUCED

    def _system_state(self, now: datetime, camera_status: CameraStatus, mmwave_status: MmwaveStatus) -> SystemState:
        if camera_status == CameraStatus.DISCONNECTED:
            return SystemState.CAMERA_DISCONNECTED
        if self._freshness_ms(now) > self.settings.runtime.freshness_unknown_ms:
            return SystemState.STALE_DATA
        publish_backlog_age = self._publish_backlog_age_ms()
        if publish_backlog_age > self.settings.runtime.publish_backlog_ms:
            if self.state.publish_backlog_since is None:
                self.state.publish_backlog_since = now
            self.state.publish_recover_since = None
            if (now - self.state.publish_backlog_since).total_seconds() >= 5:
                self.state.publish_degraded_active = True
        else:
            self.state.publish_backlog_since = None
            if self.state.publish_degraded_active:
                if publish_backlog_age <= self.settings.runtime.publish_recover_ms:
                    if self.state.publish_recover_since is None:
                        self.state.publish_recover_since = now
                    elif (
                        now - self.state.publish_recover_since
                    ).total_seconds() >= self.settings.runtime.publish_recover_seconds:
                        self.state.publish_degraded_active = False
                        self.state.publish_recover_since = None
                else:
                    self.state.publish_recover_since = None
        if self.state.publish_degraded_active:
            return SystemState.PUBLISH_DEGRADED
        if camera_status == CameraStatus.DEGRADED:
            return SystemState.CAMERA_DEGRADED
        if mmwave_status == MmwaveStatus.DISCONNECTED:
            return SystemState.MMWAVE_DISCONNECTED
        if mmwave_status in {MmwaveStatus.DEGRADED, MmwaveStatus.STALE}:
            return SystemState.MMWAVE_DEGRADED
        return SystemState.NORMAL

    def _publish_backlog_age_ms(self) -> int:
        return max(self.sse.backlog_age_ms(), self.storage.backlog_age_ms())

    def _record_validation_event(self, event: CrossingEvent) -> None:
        with self._lock:
            if not self._validation_session.active:
                return
            self._validation_session.recent_events.append(event)
            if event.direction == CrossingDirection.ENTRY:
                self._validation_session.system_entry_count += 1
            else:
                self._validation_session.system_exit_count += 1

    def _persist_validation_session(self, payload: ValidationSessionPayload) -> datetime:
        saved_at = utc_now()
        config_snapshot = settings_to_dict(self.settings)
        if self.config_path is not None:
            config_snapshot["config_path"] = str(self.config_path)
        self.storage.save_validation_session(
            payload=payload.model_dump(mode="json"),
            config_snapshot=config_snapshot,
            saved_at=isoformat(saved_at),
        )
        return saved_at

    def _roi_local_line(self, packet: FramePacket) -> tuple[int, int, int, int]:
        x1 = max(0, min(packet.roi_width - 1, packet.line_x1 - packet.roi_x1))
        y1 = max(0, min(packet.roi_height - 1, packet.line_y1 - packet.roi_y1))
        x2 = max(0, min(packet.roi_width - 1, packet.line_x2 - packet.roi_x1))
        y2 = max(0, min(packet.roi_height - 1, packet.line_y2 - packet.roi_y1))
        return x1, y1, x2, y2

    def _filter_detections(self, packet: FramePacket, detections: list) -> list:
        configured_roi_width = max(1, self.settings.camera.roi.x2 - self.settings.camera.roi.x1)
        configured_roi_height = max(1, self.settings.camera.roi.y2 - self.settings.camera.roi.y1)
        width_scale = packet.roi_width / configured_roi_width
        height_scale = packet.roi_height / configured_roi_height
        min_width = max(1, int(round(self.settings.camera.min_detection_width_px * width_scale)))
        min_height = max(1, int(round(self.settings.camera.min_detection_height_px * height_scale)))
        edge_margin = max(0, int(round(self.settings.camera.detection_edge_margin_px * width_scale)))
        filtered = []
        for detection in detections:
            width = detection.bbox.x2 - detection.bbox.x1
            height = detection.bbox.y2 - detection.bbox.y1
            if width < min_width or height < min_height:
                continue
            if edge_margin > 0:
                left_clipped = detection.bbox.x1 <= edge_margin
                right_clipped = detection.bbox.x2 >= packet.roi_width - edge_margin
                if left_clipped or right_clipped:
                    continue
            filtered.append(detection)
        return filtered

    def _validate_editable_settings(self, settings: Settings | None = None) -> None:
        settings = self.settings if settings is None else settings
        if settings.camera.roi.x2 <= settings.camera.roi.x1:
            raise ValueError("ROI x2 must be greater than x1.")
        if settings.camera.roi.y2 <= settings.camera.roi.y1:
            raise ValueError("ROI y2 must be greater than y1.")
        if settings.runtime.crossing_band_high_threshold <= settings.runtime.crossing_band_medium_threshold:
            raise ValueError("High busyness threshold must be greater than medium threshold.")
        if settings.camera.crossing_cooldown_seconds < 0.0:
            raise ValueError("Crossing cooldown must be non-negative.")
        if settings.camera.line_hysteresis_px < 0:
            raise ValueError("Line hysteresis must be non-negative.")
        if settings.camera.min_detection_width_px < 1:
            raise ValueError("Minimum detection width must be at least 1 px.")
        if settings.camera.min_detection_height_px < 1:
            raise ValueError("Minimum detection height must be at least 1 px.")
        if settings.camera.detection_edge_margin_px < 0:
            raise ValueError("Detection edge margin must be non-negative.")
        if settings.camera.min_track_hits_for_crossing < 1:
            raise ValueError("Minimum track hits for crossing must be at least 1.")
        if settings.camera.crossing_confirm_frames < 1:
            raise ValueError("Crossing confirm frames must be at least 1.")

    def _detector_fps(self, now: datetime) -> float:
        while self._detector_run_samples and (now - self._detector_run_samples[0]).total_seconds() > 1.0:
            self._detector_run_samples.popleft()
        return float(len(self._detector_run_samples))

    def _crossing_band(self, crossings: int) -> CrossingIntensityBand:
        if crossings >= self.settings.runtime.crossing_band_high_threshold:
            return CrossingIntensityBand.HIGH
        if crossings >= self.settings.runtime.crossing_band_medium_threshold:
            return CrossingIntensityBand.MEDIUM
        return CrossingIntensityBand.LOW

    def _entrance_load_level(
        self,
        now: datetime,
        base_band: CrossingIntensityBand,
        active_tracks_median: int,
    ) -> EntranceLoadLevel:
        if base_band == CrossingIntensityBand.HIGH:
            return EntranceLoadLevel.HIGH
        if (
            active_tracks_median >= self.settings.camera.active_track_promote_threshold
            and self._active_tracks_above_threshold_for(
                now,
                self.settings.camera.active_track_promote_threshold,
                self.settings.camera.active_track_promote_seconds,
            )
        ):
            return EntranceLoadLevel.HIGH if base_band == CrossingIntensityBand.MEDIUM else EntranceLoadLevel.MEDIUM
        return EntranceLoadLevel(base_band.value)

    def _active_tracks_above_threshold_for(self, now: datetime, threshold: int, seconds: int) -> bool:
        cutoff = now - timedelta(seconds=seconds)
        samples = [(ts, count) for ts, count in self._active_track_samples if ts >= cutoff]
        if not samples:
            return False
        if (now - samples[0][0]).total_seconds() < seconds:
            return False
        return min(count for _, count in samples) >= threshold

    def _read_system_metrics(self) -> tuple[float, float, float | None]:
        cpu = psutil.cpu_percent(interval=None) if psutil else 0.0
        ram_mb = 0.0
        if psutil:
            ram_mb = psutil.virtual_memory().used / (1024 * 1024)
        temperature_c = None
        thermal_file = Path("/sys/class/thermal/thermal_zone0/temp")
        try:
            if thermal_file.exists():
                temperature_c = int(thermal_file.read_text(encoding="utf-8").strip()) / 1000.0
        except Exception:
            temperature_c = None
        return cpu, ram_mb, temperature_c

    def _read_pi_flags(self) -> tuple[bool, bool]:
        throttled = False
        undervoltage = False
        try:
            import subprocess

            result = subprocess.run(
                ["vcgencmd", "get_throttled"],
                capture_output=True,
                text=True,
                check=False,
            )
            if result.returncode == 0 and "0x" in result.stdout:
                raw = int(result.stdout.strip().split("=", 1)[1], 16)
                throttled = bool(raw & 0x4) or bool(raw & 0x2)
                undervoltage = bool(raw & 0x1)
        except Exception:
            pass
        return throttled, undervoltage

    def _draw_line_direction_guides(self, frame, packet: FramePacket) -> None:
        dx = packet.line_x2 - packet.line_x1
        dy = packet.line_y2 - packet.line_y1
        length = math.hypot(dx, dy)
        if length <= 0.0:
            return
        tangent_x = dx / length
        tangent_y = dy / length
        normal_x = -dy / length
        normal_y = dx / length
        mid_x = int(round((packet.line_x1 + packet.line_x2) / 2))
        mid_y = int(round((packet.line_y1 + packet.line_y2) / 2))
        line_half = max(18, min(40, int(length * 0.18)))
        arrow_len = 44

        entry_anchor = (
            int(round(mid_x - tangent_x * line_half)),
            int(round(mid_y - tangent_y * line_half)),
        )
        exit_anchor = (
            int(round(mid_x + tangent_x * line_half)),
            int(round(mid_y + tangent_y * line_half)),
        )
        entry_tip = (
            int(round(entry_anchor[0] + normal_x * arrow_len)),
            int(round(entry_anchor[1] + normal_y * arrow_len)),
        )
        exit_tip = (
            int(round(exit_anchor[0] - normal_x * arrow_len)),
            int(round(exit_anchor[1] - normal_y * arrow_len)),
        )

        cv2.arrowedLine(frame, entry_anchor, entry_tip, (60, 220, 120), 2, tipLength=0.25)
        cv2.arrowedLine(frame, exit_anchor, exit_tip, (0, 190, 255), 2, tipLength=0.25)

        entry_label_pos = (
            max(10, min(frame.shape[1] - 80, entry_tip[0] + int(normal_x * 10))),
            max(24, min(frame.shape[0] - 10, entry_tip[1] + int(normal_y * 10))),
        )
        exit_label_pos = (
            max(10, min(frame.shape[1] - 70, exit_tip[0] - int(normal_x * 18))),
            max(24, min(frame.shape[0] - 10, exit_tip[1] - int(normal_y * 18))),
        )

        cv2.putText(
            frame,
            "ENTRY",
            entry_label_pos,
            cv2.FONT_HERSHEY_SIMPLEX,
            0.55,
            (60, 220, 120),
            2,
        )
        cv2.putText(
            frame,
            "EXIT",
            exit_label_pos,
            cv2.FONT_HERSHEY_SIMPLEX,
            0.55,
            (0, 190, 255),
            2,
        )

    def debug_frame_jpeg(self) -> bytes | None:
        if self._latest_frame is None or self._latest_packet is None:
            return None
        frame = self._latest_frame.copy()
        packet = self._latest_packet
        cv2.rectangle(
            frame,
            (packet.roi_x1, packet.roi_y1),
            (packet.roi_x2, packet.roi_y2),
            (255, 200, 0),
            2,
        )
        cv2.line(
            frame,
            (packet.line_x1, packet.line_y1),
            (packet.line_x2, packet.line_y2),
            (0, 0, 255),
            2,
        )
        self._draw_line_direction_guides(frame, packet)
        for obs in self._latest_tracks:
            bbox = obs.bbox
            x1 = bbox.x1 + packet.roi_x1
            x2 = bbox.x2 + packet.roi_x1
            y1 = bbox.y1 + packet.roi_y1
            y2 = bbox.y2 + packet.roi_y1
            cv2.rectangle(frame, (x1, y1), (x2, y2), (0, 255, 0), 2)
            cv2.putText(
                frame,
                f"ID {obs.track_id}",
                (x1, max(20, y1 - 5)),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.6,
                (0, 255, 0),
                2,
            )
        if self._latest_snapshot is not None:
            cv2.putText(
                frame,
                f"Load {self._latest_snapshot.entrance_load_level.value} | Tracks {self._latest_snapshot.active_tracks_5s_median}",
                (20, 35),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.8,
                (255, 255, 255),
                2,
            )
            cv2.putText(
                frame,
                f"Crossings30s {self._latest_snapshot.crossing_count_30s} | Gated {self._latest_snapshot.gated_mode}",
                (20, 70),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.8,
                (255, 255, 255),
                2,
            )
        ok, encoded = cv2.imencode(".jpg", frame)
        if not ok:
            return None
        return encoded.tobytes()
