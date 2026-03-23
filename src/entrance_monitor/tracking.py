from __future__ import annotations

from dataclasses import dataclass, field
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
    miss_count: int = 0
    previous_side: float | None = None
    committed_side: str | None = None
    last_cross_ts: datetime | None = None


class CentroidTracker:
    def __init__(self, max_distance: float = 120.0, max_misses: int = 15) -> None:
        self.max_distance = max_distance
        self.max_misses = max_misses
        self.tracks: dict[int, TrackState] = {}
        self.next_track_id = 1

    def update(self, detections: list[Detection], ts: datetime) -> list[TrackObservation]:
        unmatched_tracks = set(self.tracks.keys())
        observations: list[TrackObservation] = []
        assigned: set[int] = set()
        for det in detections:
            cx = (det.bbox.x1 + det.bbox.x2) / 2.0
            cy = (det.bbox.y1 + det.bbox.y2) / 2.0
            best_track_id: int | None = None
            best_distance = self.max_distance
            for track_id, track in self.tracks.items():
                if track_id in assigned:
                    continue
                dist = euclidean_distance(cx, cy, track.centroid_x, track.centroid_y)
                if dist < best_distance:
                    best_distance = dist
                    best_track_id = track_id
            if best_track_id is None:
                best_track_id = self.next_track_id
                self.next_track_id += 1
                self.tracks[best_track_id] = TrackState(
                    track_id=best_track_id,
                    bbox=det.bbox,
                    centroid_x=cx,
                    centroid_y=cy,
                    last_seen=ts,
                )
            else:
                track = self.tracks[best_track_id]
                track.bbox = det.bbox
                track.centroid_x = cx
                track.centroid_y = cy
                track.last_seen = ts
                track.miss_count = 0
            assigned.add(best_track_id)
            unmatched_tracks.discard(best_track_id)
            observations.append(
                TrackObservation(
                    track_id=best_track_id,
                    bbox=det.bbox,
                    centroid_x=cx,
                    centroid_y=cy,
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
        return observations

    def active_track_count(self) -> int:
        return len(self.tracks)


class LineCrossingCounter:
    def __init__(
        self,
        line: tuple[int, int, int, int],
        cooldown_seconds: float = 1.5,
        hysteresis_px: float = 24.0,
    ) -> None:
        self.line = line
        self.cooldown_seconds = cooldown_seconds
        self.hysteresis_px = hysteresis_px
        self.track_regions: dict[int, int] = {}
        self.committed_sides: dict[int, int] = {}
        self.last_cross_ts: dict[int, datetime] = {}

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
                self.committed_sides[obs.track_id] = current_region
                continue

            if current_region == committed_side:
                continue

            if previous_region == current_region:
                continue

            last_cross = self.last_cross_ts.get(obs.track_id)
            if last_cross is not None and (ts - last_cross).total_seconds() < self.cooldown_seconds:
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
            events.append(event)
        return events

    def _region(self, signed_distance: float) -> int:
        if signed_distance > self.hysteresis_px:
            return 1
        if signed_distance < -self.hysteresis_px:
            return -1
        return 0
