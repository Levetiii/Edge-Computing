from entrance_monitor.camera import CameraSource
from entrance_monitor.config import load_settings
from entrance_monitor.models import BoundingBox, CameraStatus, CrossingDirection, CrossingEvent, CrossingIntensityBand, Detection, FramePacket, PresenceCorroborationState
from entrance_monitor.service import EdgeService
from entrance_monitor.utils import utc_now


def test_crossing_band_thresholds():
    settings = load_settings("config/default.yaml")
    service = EdgeService(settings)
    assert service._crossing_band(0) == CrossingIntensityBand.LOW
    assert service._crossing_band(4) == CrossingIntensityBand.MEDIUM
    assert service._crossing_band(8) == CrossingIntensityBand.HIGH


def test_presence_unknown_when_mmwave_not_ok():
    settings = load_settings("config/default.yaml")
    service = EdgeService(settings)
    assert service._presence_state(service._compute_mmwave_status(utc_now())) in {
        PresenceCorroborationState.PRESENT,
        PresenceCorroborationState.ABSENT,
        PresenceCorroborationState.UNKNOWN,
    }


def test_camera_status_disconnected_without_frames():
    settings = load_settings("config/default.yaml")
    service = EdgeService(settings)
    assert service._compute_camera_status(utc_now()) == CameraStatus.DISCONNECTED


def test_camera_status_uses_negotiated_fps_floor():
    settings = load_settings("config/default.yaml")
    service = EdgeService(settings)
    now = utc_now()
    service.camera.stats.last_frame_ts = now
    service.camera.stats.expected_fps = 10.0
    service.camera.stats.delivered_fps = 8.0
    assert service._compute_camera_status(now) == CameraStatus.OK


def test_scaled_roi_and_line_fit_actual_frame():
    settings = load_settings("config/windows-webcam.yaml")
    camera = CameraSource(settings.camera)
    assert camera._scaled_roi_bounds(640, 480) == (20, 27, 620, 467)
    assert camera._scaled_line(640, 480) == (425, 467, 425, 53)


def test_validation_session_records_system_events(tmp_path):
    settings = load_settings("config/default.yaml")
    settings.storage.sqlite_path = tmp_path / "validation_logic.db"
    service = EdgeService(settings)
    started = service.start_validation_session()
    event = CrossingEvent(
        event_id="t1",
        ts=utc_now(),
        direction=CrossingDirection.ENTRY,
        track_id=7,
    )
    service._record_validation_event(event)
    payload = service.validation_payload()
    assert started.session_id is not None
    assert payload.session_id == started.session_id
    assert payload.system_entry_count == 1
    assert payload.system_total_count == 1
    assert len(payload.recent_events) == 1


def test_validation_session_persists_completed_runs(tmp_path):
    settings = load_settings("config/default.yaml")
    settings.storage.sqlite_path = tmp_path / "validation_history.db"
    service = EdgeService(settings)
    started = service.start_validation_session()
    service.add_manual_validation_count(CrossingDirection.ENTRY)
    service._record_validation_event(
        CrossingEvent(
            event_id="t2",
            ts=utc_now(),
            direction=CrossingDirection.ENTRY,
            track_id=9,
        )
    )
    stopped = service.stop_validation_session()
    history = service.validation_history(limit=10)
    assert stopped.saved_at is not None
    assert len(history) == 1
    assert history[0].session_id == started.session_id
    assert history[0].manual_total_count == 1
    assert history[0].system_total_count == 1
    assert history[0].config_snapshot["detector"]["backend"] == settings.detector.backend


def test_detection_filter_ignores_small_and_edge_clipped_boxes():
    settings = load_settings("config/default.yaml")
    service = EdgeService(settings)
    packet = FramePacket(
        frame_id=1,
        ts=utc_now(),
        width=1280,
        height=720,
        roi_x1=0,
        roi_y1=0,
        roi_x2=960,
        roi_y2=560,
        roi_width=960,
        roi_height=560,
        line_x1=480,
        line_y1=0,
        line_x2=480,
        line_y2=560,
    )
    detections = [
        Detection(bbox=BoundingBox(x1=4, y1=40, x2=80, y2=150)),
        Detection(bbox=BoundingBox(x1=100, y1=100, x2=120, y2=140)),
        Detection(bbox=BoundingBox(x1=120, y1=120, x2=220, y2=320)),
        Detection(bbox=BoundingBox(x1=240, y1=300, x2=320, y2=558)),
    ]
    filtered = service._filter_detections(packet, detections)
    assert len(filtered) == 2
    assert filtered[0].bbox.x1 == 120
    assert filtered[1].bbox.x1 == 240


def test_detection_filter_scales_thresholds_with_actual_roi():
    settings = load_settings("config/default.yaml")
    service = EdgeService(settings)
    packet = FramePacket(
        frame_id=2,
        ts=utc_now(),
        width=640,
        height=360,
        roi_x1=80,
        roi_y1=60,
        roi_x2=560,
        roi_y2=340,
        roi_width=480,
        roi_height=280,
        line_x1=320,
        line_y1=75,
        line_x2=320,
        line_y2=325,
    )
    detections = [
        Detection(bbox=BoundingBox(x1=10, y1=20, x2=30, y2=64)),
        Detection(bbox=BoundingBox(x1=10, y1=20, x2=22, y2=64)),
        Detection(bbox=BoundingBox(x1=4, y1=24, x2=28, y2=78)),
    ]
    filtered = service._filter_detections(packet, detections)
    assert len(filtered) == 1
    assert filtered[0].bbox.x1 == 10
