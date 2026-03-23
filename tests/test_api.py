import json
import sqlite3
import time
from datetime import timedelta
from pathlib import Path

from fastapi.testclient import TestClient

from entrance_monitor.api import create_app
from entrance_monitor.config import load_settings
from entrance_monitor.service import EdgeService
from entrance_monitor.utils import isoformat, utc_now


def test_api_endpoints_bootstrap_with_mock_pipeline():
    settings = load_settings("config/default.yaml")
    service = EdgeService(settings)
    service.start()
    try:
        deadline = time.time() + 5
        while service.latest_snapshot() is None and time.time() < deadline:
            time.sleep(0.2)
        assert service.latest_snapshot() is not None
        client = TestClient(create_app(service))
        assert client.get("/api/v1/status").status_code == 200
        assert client.get("/api/v1/metrics/latest").status_code == 200
        assert client.get("/api/v1/events/recent").status_code == 200
        assert client.get("/api/v1/metrics/history?minutes=1").status_code == 200
        assert client.get("/api/v1/validation").status_code == 200
        assert client.get("/").status_code == 200
        assert client.get("/validation").status_code == 200
    finally:
        service.stop()


def test_settings_page_updates_and_persists_config(tmp_path):
    config_path = tmp_path / "settings.yaml"
    config_path.write_text(Path("config/default.yaml").read_text(encoding="utf-8"), encoding="utf-8")
    settings = load_settings(config_path)
    service = EdgeService(settings, config_path=config_path)
    service.start()
    try:
        deadline = time.time() + 5
        while service.latest_snapshot() is None and time.time() < deadline:
            time.sleep(0.2)
        client = TestClient(create_app(service))
        assert client.get("/settings").status_code == 200
        before = client.get("/api/v1/settings")
        assert before.status_code == 200
        payload = before.json()
        payload["camera"]["roi"]["x1"] = 200
        payload["camera"]["min_detection_width_px"] = 18
        payload["camera"]["min_track_hits_for_crossing"] = 2
        payload["runtime"]["crossing_band_high_threshold"] = 9
        payload["detector"]["confidence_threshold"] = 0.45
        updated = client.post("/api/v1/settings", json=payload)
        assert updated.status_code == 200
        body = updated.json()
        assert body["camera"]["roi"]["x1"] == 200
        assert body["camera"]["min_detection_width_px"] == 18
        assert body["camera"]["min_track_hits_for_crossing"] == 2
        assert body["runtime"]["crossing_band_high_threshold"] == 9
        assert service.settings.camera.roi.x1 == 200
        assert service.settings.camera.min_detection_width_px == 18
        assert service.settings.camera.min_track_hits_for_crossing == 2
        assert service.settings.runtime.crossing_band_high_threshold == 9
        assert service.counter.min_track_hits == 2
        persisted = config_path.read_text(encoding="utf-8")
        assert "x1: 200" in persisted
        assert "min_detection_width_px: 18" in persisted
        assert "min_track_hits_for_crossing: 2" in persisted
        assert "crossing_band_high_threshold: 9" in persisted
        assert "confidence_threshold: 0.45" in persisted
        invalid_payload = body
        invalid_payload["runtime"]["crossing_band_high_threshold"] = invalid_payload["runtime"]["crossing_band_medium_threshold"]
        before_invalid = config_path.read_text(encoding="utf-8")
        invalid = client.post("/api/v1/settings", json=invalid_payload)
        assert invalid.status_code == 400
        assert service.settings.runtime.crossing_band_high_threshold == 9
        assert service.settings.camera.roi.x1 == 200
        assert service.counter.min_track_hits == 2
        assert config_path.read_text(encoding="utf-8") == before_invalid
    finally:
        service.stop()


def test_validation_session_controls(tmp_path):
    settings = load_settings("config/default.yaml")
    settings.storage.sqlite_path = tmp_path / "validation_api.db"
    service = EdgeService(settings)
    service.start()
    try:
        deadline = time.time() + 5
        while service.latest_snapshot() is None and time.time() < deadline:
            time.sleep(0.2)
        client = TestClient(create_app(service))
        started = client.post("/api/v1/validation/start")
        assert started.status_code == 200
        assert started.json()["state"] == "RUNNING"
        assert started.json()["active"] is True
        duplicate_start = client.post("/api/v1/validation/start")
        assert duplicate_start.status_code == 400

        manual_entry = client.post("/api/v1/validation/manual-entry")
        assert manual_entry.status_code == 200
        manual_exit = client.post("/api/v1/validation/manual-exit")
        assert manual_exit.status_code == 200

        current = client.get("/api/v1/validation")
        assert current.status_code == 200
        payload = current.json()
        assert payload["manual_entry_count"] == 1
        assert payload["manual_exit_count"] == 1
        assert payload["manual_total_count"] == 2

        stopped = client.post("/api/v1/validation/stop")
        assert stopped.status_code == 200
        assert stopped.json()["state"] == "COMPLETED"
        assert stopped.json()["active"] is False
        assert stopped.json()["saved_at"] is not None

        history = client.get("/api/v1/validation/history?limit=5")
        assert history.status_code == 200
        items = history.json()["items"]
        assert len(items) == 1
        assert items[0]["session_id"] == stopped.json()["session_id"]
        assert items[0]["config_snapshot"]["detector"]["backend"] == settings.detector.backend

        export = client.get("/api/v1/validation/export.csv?limit=5")
        assert export.status_code == 200
        assert export.headers["content-type"].startswith("text/csv")
        assert "session_id" in export.text
        assert "min_detection_width_px" in export.text
        assert "min_track_hits_for_crossing" in export.text
        assert "crossing_confirm_frames" in export.text
        assert stopped.json()["session_id"] in export.text

        reset = client.post("/api/v1/validation/reset")
        assert reset.status_code == 200
        assert reset.json()["state"] == "NOT_STARTED"
        assert reset.json()["manual_total_count"] == 0
    finally:
        service.stop()


def test_metrics_history_supports_ranges_beyond_two_hours(tmp_path):
    settings = load_settings("config/default.yaml")
    settings.storage.sqlite_path = tmp_path / "history_range.db"
    service = EdgeService(settings)
    old_ts = isoformat(utc_now() - timedelta(minutes=300))
    payload = {
        "schema_version": settings.app.schema_version,
        "ts": old_ts,
        "entry_count_30s": 1,
        "exit_count_30s": 0,
        "crossing_count_30s": 1,
    }
    with sqlite3.connect(settings.storage.sqlite_path) as conn:
        conn.execute(
            "INSERT OR REPLACE INTO snapshots(ts, payload) VALUES(?, ?)",
            (old_ts, json.dumps(payload)),
        )
    client = TestClient(create_app(service))
    response = client.get("/api/v1/metrics/history?minutes=500")
    assert response.status_code == 200
    items = response.json()["items"]
    assert len(items) == 1
    assert items[0]["ts"] == old_ts
