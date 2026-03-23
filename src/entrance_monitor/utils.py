from __future__ import annotations

import math
from collections import deque
from datetime import UTC, datetime
from typing import Iterable


def utc_now() -> datetime:
    return datetime.now(UTC)


def isoformat(dt: datetime) -> str:
    return dt.astimezone(UTC).isoformat().replace("+00:00", "Z")


def line_side(x1: int, y1: int, x2: int, y2: int, px: float, py: float) -> float:
    return (x2 - x1) * (py - y1) - (y2 - y1) * (px - x1)


def median_int(values: Iterable[int]) -> int:
    ordered = sorted(values)
    if not ordered:
        return 0
    mid = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[mid]
    return int(round((ordered[mid - 1] + ordered[mid]) / 2))


class TimedFlag:
    def __init__(self) -> None:
        self._active_since: datetime | None = None

    def update(self, is_active: bool, now: datetime) -> None:
        if is_active:
            if self._active_since is None:
                self._active_since = now
        else:
            self._active_since = None

    def active_for_seconds(self, now: datetime) -> float:
        if self._active_since is None:
            return 0.0
        return max(0.0, (now - self._active_since).total_seconds())


class RatioWindow:
    def __init__(self, window_seconds: int) -> None:
        self.window_seconds = window_seconds
        self.samples: deque[tuple[datetime, int, int]] = deque()

    def add(self, now: datetime, numerator: int, denominator: int) -> None:
        self.samples.append((now, numerator, denominator))
        self.prune(now)

    def prune(self, now: datetime) -> None:
        while self.samples and (now - self.samples[0][0]).total_seconds() > self.window_seconds:
            self.samples.popleft()

    def ratio(self, now: datetime) -> float:
        self.prune(now)
        num = sum(item[1] for item in self.samples)
        den = sum(item[2] for item in self.samples)
        if den <= 0:
            return 0.0
        return num / den


def clamp(value: int, low: int, high: int) -> int:
    return max(low, min(high, value))


def euclidean_distance(x1: float, y1: float, x2: float, y2: float) -> float:
    return math.sqrt((x1 - x2) ** 2 + (y1 - y2) ** 2)
