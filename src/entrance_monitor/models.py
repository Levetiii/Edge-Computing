from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Literal

from pydantic import BaseModel, Field


def utc_now() -> datetime:
    return datetime.utcnow()


class CameraStatus(str, Enum):
    OK = "OK"
    DEGRADED = "DEGRADED"
    STALE = "STALE"
    DISCONNECTED = "DISCONNECTED"


class MmwaveStatus(str, Enum):
    OK = "OK"
    DEGRADED = "DEGRADED"
    STALE = "STALE"
    DISCONNECTED = "DISCONNECTED"


class SystemState(str, Enum):
    NORMAL = "NORMAL"
    CAMERA_DEGRADED = "CAMERA_DEGRADED"
    CAMERA_DISCONNECTED = "CAMERA_DISCONNECTED"
    MMWAVE_DEGRADED = "MMWAVE_DEGRADED"
    MMWAVE_DISCONNECTED = "MMWAVE_DISCONNECTED"
    PUBLISH_DEGRADED = "PUBLISH_DEGRADED"
    STALE_DATA = "STALE_DATA"
    UNKNOWN = "UNKNOWN"


class PresenceCorroborationState(str, Enum):
    PRESENT = "PRESENT"
    ABSENT = "ABSENT"
    UNKNOWN = "UNKNOWN"


class CountConfidence(str, Enum):
    HIGH = "HIGH"
    REDUCED = "REDUCED"
    UNKNOWN = "UNKNOWN"


class WarningFlag(str, Enum):
    WARMUP_WINDOW = "warmup_window"
    HIGH_DROP_RATE = "high_drop_rate"
    CAMERA_STALE = "camera_stale"
    CAMERA_DISCONNECTED = "camera_disconnected"
    MMWAVE_STALE = "mmwave_stale"
    MMWAVE_DISAGREEMENT = "mmwave_disagreement"
    THERMAL_THROTTLE = "thermal_throttle"
    UNDERVOLTAGE = "undervoltage"
    PUBLISH_BACKLOG = "publish_backlog"


class CrossingIntensityBand(str, Enum):
    LOW = "Low"
    MEDIUM = "Medium"
    HIGH = "High"


class EntranceLoadLevel(str, Enum):
    LOW = "Low"
    MEDIUM = "Medium"
    HIGH = "High"


class BoundingBox(BaseModel):
    x1: int
    y1: int
    x2: int
    y2: int
    confidence: float = 1.0


class Detection(BaseModel):
    bbox: BoundingBox
    label: str = "person"


class FramePacket(BaseModel):
    frame_id: int
    ts: datetime
    width: int
    height: int
    roi_x1: int
    roi_y1: int
    roi_x2: int
    roi_y2: int
    roi_width: int
    roi_height: int
    line_x1: int
    line_y1: int
    line_x2: int
    line_y2: int
    delivered_fps: float = 0.0
    image: object | None = Field(default=None, exclude=True)
    roi_image: object | None = Field(default=None, exclude=True)

    model_config = {"arbitrary_types_allowed": True}


class DetectionPacket(BaseModel):
    frame_id: int
    ts: datetime
    detections: list[Detection]
    inference_ms: float


class TrackObservation(BaseModel):
    track_id: int
    bbox: BoundingBox
    centroid_x: float
    centroid_y: float
    hit_count: int = 1


class CrossingDirection(str, Enum):
    ENTRY = "ENTRY"
    EXIT = "EXIT"


class CrossingEvent(BaseModel):
    event_id: str
    ts: datetime
    direction: CrossingDirection
    track_id: int


class MmwaveSample(BaseModel):
    ts: datetime
    state: PresenceCorroborationState
    valid: bool = True
    raw: str | None = None


class StatusPayload(BaseModel):
    schema_version: str
    ts: datetime
    camera_status: CameraStatus
    mmwave_status: MmwaveStatus
    system_state: SystemState
    audio_disabled: Literal[True] = True
    freshness_ms: int
    warning_flags: list[WarningFlag]
    count_confidence: CountConfidence
    camera_source: str
    frame_width: int
    frame_height: int
    delivered_fps: float
    detector_fps: float
    detector_mode: str
    gated_mode: bool
    cpu_percent: float = 0.0
    ram_mb: float = 0.0
    temperature_c: float | None = None


class MetricsSnapshot(BaseModel):
    schema_version: str
    ts: datetime
    camera_status: CameraStatus
    mmwave_status: MmwaveStatus
    system_state: SystemState
    audio_disabled: Literal[True] = True
    freshness_ms: int
    entry_count_30s: int
    exit_count_30s: int
    net_count_30s: int
    crossing_count_30s: int
    active_tracks_5s_median: int
    crossing_intensity_band_30s: CrossingIntensityBand
    presence_corroboration_state: PresenceCorroborationState
    entrance_load_level: EntranceLoadLevel
    count_confidence: CountConfidence
    warning_flags: list[WarningFlag]
    entry_rate_per_min: int
    exit_rate_per_min: int
    net_flow_per_min: int
    frame_width: int
    frame_height: int
    delivered_fps: float
    detector_fps: float
    gated_mode: bool


class RecentEventsPayload(BaseModel):
    schema_version: str
    ts: datetime
    events: list[CrossingEvent]


class ValidationState(str, Enum):
    NOT_STARTED = "NOT_STARTED"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"


class ValidationSessionPayload(BaseModel):
    schema_version: str
    session_id: str | None = None
    state: ValidationState
    active: bool
    started_at: datetime | None = None
    ended_at: datetime | None = None
    saved_at: datetime | None = None
    duration_seconds: float = 0.0
    manual_entry_count: int = 0
    manual_exit_count: int = 0
    manual_total_count: int = 0
    system_entry_count: int = 0
    system_exit_count: int = 0
    system_total_count: int = 0
    entry_error: int = 0
    exit_error: int = 0
    total_error: int = 0
    recent_events: list[CrossingEvent] = Field(default_factory=list)


class ValidationSessionRecord(BaseModel):
    session_id: str
    state: ValidationState
    started_at: datetime | None = None
    ended_at: datetime | None = None
    saved_at: datetime
    duration_seconds: float = 0.0
    manual_entry_count: int = 0
    manual_exit_count: int = 0
    manual_total_count: int = 0
    system_entry_count: int = 0
    system_exit_count: int = 0
    system_total_count: int = 0
    entry_error: int = 0
    exit_error: int = 0
    total_error: int = 0
    config_snapshot: dict = Field(default_factory=dict)


class ValidationHistoryPayload(BaseModel):
    schema_version: str
    items: list[ValidationSessionRecord] = Field(default_factory=list)
