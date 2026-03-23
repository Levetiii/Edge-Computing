from __future__ import annotations

from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, Field, model_validator


class LineConfig(BaseModel):
    x1: int
    y1: int
    x2: int
    y2: int


class RoiConfig(BaseModel):
    x1: int
    y1: int
    x2: int
    y2: int


class AppConfig(BaseModel):
    host: str = "127.0.0.1"
    port: int = 8000
    schema_version: str = "1.0.0"
    data_dir: Path = Path("data")
    local_debug_only: bool = True


class CameraConfig(BaseModel):
    source: str | int = "0"
    backend: Literal["auto", "v4l2", "msmf", "dshow", "any"] = "auto"
    width: int = 1280
    height: int = 720
    fps: int = 30
    warmup_seconds: float = 2.0
    reconnect_seconds: float = 5.0
    roi: RoiConfig
    line: LineConfig
    detector_fps_normal: float = 10.0
    detector_fps_gated: float = 3.0
    crossing_cooldown_seconds: float = 1.5
    line_hysteresis_px: int = 24
    min_detection_width_px: int = 28
    min_detection_height_px: int = 56
    detection_edge_margin_px: int = 12
    min_track_hits_for_crossing: int = 3
    crossing_confirm_frames: int = 2
    active_track_promote_threshold: int = 3
    active_track_promote_seconds: int = 5

    @model_validator(mode="after")
    def normalize_source(self) -> "CameraConfig":
        if isinstance(self.source, str) and self.source.isdigit():
            self.source = int(self.source)
        return self


class MmwaveConfig(BaseModel):
    mode: Literal["mock", "serial"] = "mock"
    port: str = "COM3"
    baudrate: int = 256000
    mock_present_seconds: int = 8
    mock_absent_seconds: int = 12


class DetectorConfig(BaseModel):
    backend: Literal["hog", "ultralytics"] = "hog"
    model_path: str = ""
    confidence_threshold: float = 0.35
    iou_threshold: float = 0.4
    imgsz: int = 416


class StorageConfig(BaseModel):
    sqlite_path: Path = Path("data/entrance_monitor.db")
    retention_days: int = 7
    max_log_files: int = 5
    max_log_file_mb: int = 10


class RuntimeConfig(BaseModel):
    warmup_seconds: int = 30
    camera_ok_age_ms: int = 1000
    camera_stale_age_ms: int = 2000
    camera_disconnect_age_ms: int = 5000
    mmwave_ok_age_ms: int = 1000
    mmwave_stale_age_ms: int = 2000
    mmwave_disconnect_age_ms: int = 5000
    high_drop_ratio_threshold: float = 0.10
    degraded_drop_ratio_threshold: float = 0.20
    publish_backlog_ms: int = 2000
    publish_recover_ms: int = 500
    publish_recover_seconds: int = 10
    freshness_high_ms: int = 1000
    freshness_unknown_ms: int = 2000
    low_activity_absent_seconds: int = 10
    disagreement_present_seconds: int = 10
    disagreement_absent_seconds: int = 5
    window_seconds: int = 30
    active_track_window_seconds: int = 5
    snapshot_interval_seconds: int = 1
    crossing_band_medium_threshold: int = 4
    crossing_band_high_threshold: int = 8

    @model_validator(mode="after")
    def validate_band_thresholds(self) -> "RuntimeConfig":
        if self.crossing_band_high_threshold <= self.crossing_band_medium_threshold:
            raise ValueError("crossing_band_high_threshold must be greater than crossing_band_medium_threshold")
        return self


class DashboardConfig(BaseModel):
    history_minutes_default: int = 15


class Settings(BaseModel):
    app: AppConfig
    camera: CameraConfig
    mmwave: MmwaveConfig
    detector: DetectorConfig
    storage: StorageConfig
    runtime: RuntimeConfig
    dashboard: DashboardConfig


def settings_to_dict(settings: Settings) -> dict:
    return _serialize(settings.model_dump(mode="python"))


def save_settings(path: str | Path, settings: Settings) -> None:
    payload = settings_to_dict(settings)
    Path(path).write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")


def load_settings(path: str | Path) -> Settings:
    raw = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    settings = Settings.model_validate(raw)
    settings.app.data_dir.mkdir(parents=True, exist_ok=True)
    settings.storage.sqlite_path.parent.mkdir(parents=True, exist_ok=True)
    return settings


def _serialize(value):
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, dict):
        return {key: _serialize(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_serialize(item) for item in value]
    return value
