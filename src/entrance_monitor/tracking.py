from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import math

from .models import BoundingBox, CrossingDirection, CrossingEvent, Detection, TrackObservation
from .utils import euclidean_distance, line_side


@dataclass
class TrackState:
    track_id: int
    bbox: BoundingBox
    centroid_x: float
    centroid_y: float
    last_seen: datetime
    hit_count: int = 1
    miss_count: int = 0
    previous_side: float | None = None
    committed_side: str | None = None
    last_cross_ts: datetime | None = None
    velocity_x: float = 0.0
    velocity_y: float = 0.0


class CentroidTracker:
    def __init__(self, max_distance: float = 120.0, max_misses: int = 15, min_iou: float = 0.05) -> None:
        self.max_distance = max_distance
        self.max_misses = max_misses
        self.min_iou = min_iou
        self.tracks: dict[int, TrackState] = {}
        self.next_track_id = 1

    def update(self, detections: list[Detection], ts: datetime) -> list[TrackObservation]:
        unmatched_tracks = set(self.tracks.keys())
        observations: list[TrackObservation] = []
        prepared_detections = [
            (det, (det.bbox.x1 + det.bbox.x2) / 2.0, (det.bbox.y1 + det.bbox.y2) / 2.0)
            for det in detections
        ]
        assigned_tracks: set[int] = set()
        assigned_detections: set[int] = set()

        candidates = self._candidate_matches(prepared_detections)
        for _, _, track_id, det_index in candidates:
            if track_id in assigned_tracks or det_index in assigned_detections:
                continue
            det, cx, cy = prepared_detections[det_index]
            track = self.tracks[track_id]
            self._update_track(track, det.bbox, cx, cy, ts)
            observations.append(
                TrackObservation(
                    track_id=track_id,
                    bbox=det.bbox,
                    centroid_x=cx,
                    centroid_y=cy,
                    hit_count=track.hit_count,
                )
            )
            assigned_tracks.add(track_id)
            assigned_detections.add(det_index)
            unmatched_tracks.discard(track_id)

        for det_index, (det, cx, cy) in enumerate(prepared_detections):
            if det_index in assigned_detections:
                continue
            track = self._register_new_track(det.bbox, cx, cy, ts)
            observations.append(
                TrackObservation(
                    track_id=track.track_id,
                    bbox=det.bbox,
                    centroid_x=cx,
                    centroid_y=cy,
                    hit_count=track.hit_count,
                )
            )
        expired: list[int] = []
        for track_id in unmatched_tracks:
            track = self.tracks[track_id]
            track.miss_count += 1
            if track.miss_count > self.max_misses:
                expired.append(track_id)
        for track_id in expired:
            self.tracks.pop(track_id, None)
        return sorted(observations, key=lambda obs: obs.track_id)

    def active_track_count(self) -> int:
        return len(self.tracks)

    def active_track_ids(self) -> set[int]:
        return set(self.tracks.keys())

    def _candidate_matches(self, prepared_detections: list[tuple[Detection, float, float]]) -> list[tuple[int, float, int, int]]:
        candidates: list[tuple[int, float, int, int]] = []
        for track_id, track in self.tracks.items():
            predicted_x = track.centroid_x + track.velocity_x
            predicted_y = track.centroid_y + track.velocity_y
            for det_index, (det, cx, cy) in enumerate(prepared_detections):
                overlap = bbox_iou(det.bbox, track.bbox)
                distance = euclidean_distance(cx, cy, predicted_x, predicted_y)
                if overlap < self.min_iou and distance > self.max_distance:
                    continue
                overlap_priority = 0 if overlap >= self.min_iou else 1
                candidates.append((overlap_priority, distance - (overlap * 1000.0), track_id, det_index))
        candidates.sort(key=lambda item: (item[0], item[1], item[2], item[3]))
        return candidates

    def _update_track(self, track: TrackState, bbox: BoundingBox, cx: float, cy: float, ts: datetime) -> None:
        track.velocity_x = cx - track.centroid_x
        track.velocity_y = cy - track.centroid_y
        track.bbox = bbox
        track.centroid_x = cx
        track.centroid_y = cy
        track.last_seen = ts
        track.hit_count += 1
        track.miss_count = 0

    def _register_new_track(self, bbox: BoundingBox, cx: float, cy: float, ts: datetime) -> TrackState:
        track_id = self.next_track_id
        self.next_track_id += 1
        track = TrackState(
            track_id=track_id,
            bbox=bbox,
            centroid_x=cx,
            centroid_y=cy,
            last_seen=ts,
        )
        self.tracks[track_id] = track
        return track


class LineCrossingCounter:
    def __init__(
        self,
        line: tuple[int, int, int, int],
        cooldown_seconds: float = 1.5,
        hysteresis_px: float = 24.0,
        min_track_hits: int = 3,
        confirm_frames: int = 2,
    ) -> None:
        self.line = line
        self.cooldown_seconds = cooldown_seconds
        self.hysteresis_px = hysteresis_px
        self.min_track_hits = min_track_hits
        self.confirm_frames = confirm_frames
        self.track_regions: dict[int, int] = {}
        self.committed_sides: dict[int, int] = {}
        self.last_cross_ts: dict[int, datetime] = {}
        self.pending_sides: dict[int, int] = {}
        self.pending_counts: dict[int, int] = {}

    def update(self, observations: list[TrackObservation], ts: datetime) -> list[CrossingEvent]:
        events: list[CrossingEvent] = []
        x1, y1, x2, y2 = self.line
        line_length = max(1.0, math.hypot(x2 - x1, y2 - y1))
        for obs in observations:
            signed_distance = line_side(x1, y1, x2, y2, obs.centroid_x, obs.centroid_y) / line_length
            current_region = self._region(signed_distance)
            previous_region = self.track_regions.get(obs.track_id)
            self.track_regions[obs.track_id] = current_region
            committed_side = self.committed_sides.get(obs.track_id)

            if current_region == 0:
                continue

            if committed_side is None:
                if obs.hit_count >= self.min_track_hits:
                    self.committed_sides[obs.track_id] = current_region
                continue

            if current_region == committed_side:
                self.pending_sides.pop(obs.track_id, None)
                self.pending_counts.pop(obs.track_id, None)
                continue

            last_cross = self.last_cross_ts.get(obs.track_id)
            if last_cross is not None and (ts - last_cross).total_seconds() < self.cooldown_seconds:
                continue
            if obs.hit_count < self.min_track_hits:
                continue
            pending_side = self.pending_sides.get(obs.track_id)
            if pending_side != current_region:
                self.pending_sides[obs.track_id] = current_region
                self.pending_counts[obs.track_id] = 1
            else:
                self.pending_counts[obs.track_id] = self.pending_counts.get(obs.track_id, 0) + 1
            if self.pending_counts.get(obs.track_id, 0) < self.confirm_frames:
                continue
            direction = (
                CrossingDirection.ENTRY
                if committed_side < 0 < current_region
                else CrossingDirection.EXIT
            )
            event = CrossingEvent(
                event_id=f"{obs.track_id}-{int(ts.timestamp() * 1000)}",
                ts=ts,
                direction=direction,
                track_id=obs.track_id,
            )
            self.last_cross_ts[obs.track_id] = ts
            self.committed_sides[obs.track_id] = current_region
            self.pending_sides.pop(obs.track_id, None)
            self.pending_counts.pop(obs.track_id, None)
            events.append(event)
        return events

    def prune(self, active_track_ids: set[int]) -> None:
        stale_ids = set(self.track_regions) - active_track_ids
        for track_id in stale_ids:
            self.track_regions.pop(track_id, None)
            self.committed_sides.pop(track_id, None)
            self.last_cross_ts.pop(track_id, None)
            self.pending_sides.pop(track_id, None)
            self.pending_counts.pop(track_id, None)

    def _region(self, signed_distance: float) -> int:
        if signed_distance > self.hysteresis_px:
            return 1
        if signed_distance < -self.hysteresis_px:
            return -1
        return 0


def bbox_iou(a: BoundingBox, b: BoundingBox) -> float:
    inter_x1 = max(a.x1, b.x1)
    inter_y1 = max(a.y1, b.y1)
    inter_x2 = min(a.x2, b.x2)
    inter_y2 = min(a.y2, b.y2)
    inter_w = max(0, inter_x2 - inter_x1)
    inter_h = max(0, inter_y2 - inter_y1)
    if inter_w == 0 or inter_h == 0:
        return 0.0
    inter_area = inter_w * inter_h
    area_a = max(1, (a.x2 - a.x1) * (a.y2 - a.y1))
    area_b = max(1, (b.x2 - b.x1) * (b.y2 - b.y1))
    union_area = area_a + area_b - inter_area
    if union_area <= 0:
        return 0.0
    return inter_area / union_area
