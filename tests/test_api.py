import time
from pathlib import Path

from fastapi.testclient import TestClient

from entrance_monitor.api import create_app
from entrance_monitor.config import load_settings
from entrance_monitor.service import EdgeService


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
        assert client.get("/").status_code == 200
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
        payload["runtime"]["crossing_band_high_threshold"] = 9
        payload["detector"]["confidence_threshold"] = 0.45
        updated = client.post("/api/v1/settings", json=payload)
        assert updated.status_code == 200
        body = updated.json()
        assert body["camera"]["roi"]["x1"] == 200
        assert body["runtime"]["crossing_band_high_threshold"] == 9
        persisted = config_path.read_text(encoding="utf-8")
        assert "x1: 200" in persisted
        assert "crossing_band_high_threshold: 9" in persisted
        assert "confidence_threshold: 0.45" in persisted
    finally:
        service.stop()
