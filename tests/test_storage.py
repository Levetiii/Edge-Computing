from pathlib import Path

from entrance_monitor.models import (
    CameraStatus,
    CountConfidence,
    CrossingDirection,
    CrossingEvent,
    CrossingIntensityBand,
    EntranceLoadLevel,
    MetricsSnapshot,
    MmwaveStatus,
    PresenceCorroborationState,
    SystemState,
)
from entrance_monitor.storage import StorageWriter
from entrance_monitor.utils import utc_now


def test_storage_writer_flushes_pending_queue_on_stop(tmp_path):
    sqlite_path = tmp_path / "storage_flush.db"
    writer = StorageWriter(sqlite_path=sqlite_path, retention_days=7)
    snapshot = MetricsSnapshot(
        schema_version="1.0.0",
        ts=utc_now(),
        camera_status=CameraStatus.OK,
        mmwave_status=MmwaveStatus.OK,
        system_state=SystemState.NORMAL,
        freshness_ms=80,
        entry_count_30s=1,
        exit_count_30s=0,
        net_count_30s=1,
        crossing_count_30s=1,
        active_tracks_5s_median=1,
        crossing_intensity_band_30s=CrossingIntensityBand.LOW,
        presence_corroboration_state=PresenceCorroborationState.UNKNOWN,
        entrance_load_level=EntranceLoadLevel.LOW,
        count_confidence=CountConfidence.HIGH,
        warning_flags=[],
        entry_rate_per_min=2,
        exit_rate_per_min=0,
        net_flow_per_min=2,
        frame_width=640,
        frame_height=480,
        delivered_fps=20.0,
        detector_fps=8.0,
        gated_mode=False,
    )
    event = CrossingEvent(
        event_id="flush-event",
        ts=utc_now(),
        direction=CrossingDirection.ENTRY,
        track_id=3,
    )

    writer.start()
    writer.enqueue_snapshot(snapshot)
    writer.enqueue_event(event)
    writer.stop()

    history = writer.history(minutes=5)
    events = writer.recent_events(limit=5)
    assert len(history) == 1
    assert history[0]["entry_count_30s"] == 1
    assert len(events) == 1
    assert events[0]["event_id"] == "flush-event"
