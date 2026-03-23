from entrance_monitor.camera import CameraSource
from entrance_monitor.config import load_settings
from entrance_monitor.models import CameraStatus, CrossingIntensityBand, PresenceCorroborationState
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


def test_scaled_roi_and_line_fit_actual_frame():
    settings = load_settings("config/windows-webcam.yaml")
    camera = CameraSource(settings.camera)
    assert camera._scaled_roi_bounds(640, 480) == (20, 27, 620, 467)
    assert camera._scaled_line(640, 480) == (500, 53, 500, 467)
