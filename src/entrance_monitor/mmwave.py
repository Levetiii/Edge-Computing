from __future__ import annotations

import threading
import time
from collections import deque
from dataclasses import dataclass
from datetime import datetime

from .config import MmwaveConfig
from .models import MmwaveSample, PresenceCorroborationState
from .utils import utc_now

try:
    import serial  # type: ignore
except ImportError:  # pragma: no cover
    serial = None


@dataclass
class MmwaveStats:
    total_samples: int = 0
    invalid_samples: int = 0
    last_sample_ts: datetime | None = None


class MmwaveSource:
    def __init__(self, config: MmwaveConfig) -> None:
        self.config = config
        self._running = threading.Event()
        self._thread: threading.Thread | None = None
        self._lock = threading.Lock()
        self._latest: MmwaveSample | None = None
        self._errors: deque[tuple[datetime, int, int]] = deque()
        self.stats = MmwaveStats()

    def start(self) -> None:
        self._running.set()
        self._thread = threading.Thread(target=self._run, name="mmwave-source", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._running.clear()
        if self._thread:
            self._thread.join(timeout=2)

    def latest(self) -> MmwaveSample | None:
        with self._lock:
            return self._latest

    def error_ratio(self, now: datetime) -> float:
        while self._errors and (now - self._errors[0][0]).total_seconds() > 30:
            self._errors.popleft()
        num = sum(item[1] for item in self._errors)
        den = sum(item[2] for item in self._errors)
        if den <= 0:
            return 0.0
        return num / den

    def _set_latest(self, sample: MmwaveSample) -> None:
        with self._lock:
            self._latest = sample

    def _record_result(self, now: datetime, invalid: bool) -> None:
        self._errors.append((now, 1 if invalid else 0, 1))
        self.stats.total_samples += 1
        if invalid:
            self.stats.invalid_samples += 1

    def _run(self) -> None:
        if self.config.mode == "mock":
            self._run_mock()
        else:
            self._run_serial()

    def _run_mock(self) -> None:
        state = PresenceCorroborationState.PRESENT
        switch_at = time.monotonic() + self.config.mock_present_seconds
        while self._running.is_set():
            now = utc_now()
            sample = MmwaveSample(ts=now, state=state, valid=True, raw=state.value)
            self.stats.last_sample_ts = now
            self._set_latest(sample)
            self._record_result(now, invalid=False)
            if time.monotonic() >= switch_at:
                if state == PresenceCorroborationState.PRESENT:
                    state = PresenceCorroborationState.ABSENT
                    switch_at = time.monotonic() + self.config.mock_absent_seconds
                else:
                    state = PresenceCorroborationState.PRESENT
                    switch_at = time.monotonic() + self.config.mock_present_seconds
            time.sleep(1.0)

    def _run_serial(self) -> None:
        if serial is None:
            while self._running.is_set():
                now = utc_now()
                self._record_result(now, invalid=True)
                self._set_latest(MmwaveSample(ts=now, state=PresenceCorroborationState.UNKNOWN, valid=False))
                time.sleep(1.0)
            return
        while self._running.is_set():
            try:
                with serial.Serial(self.config.port, self.config.baudrate, timeout=1) as ser:
                    while self._running.is_set():
                        line = ser.readline().decode("utf-8", errors="ignore").strip()
                        now = utc_now()
                        if not line:
                            continue
                        state = self._parse_state(line)
                        valid = state is not None
                        sample = MmwaveSample(
                            ts=now,
                            state=state or PresenceCorroborationState.UNKNOWN,
                            valid=valid,
                            raw=line,
                        )
                        self.stats.last_sample_ts = now
                        self._record_result(now, invalid=not valid)
                        self._set_latest(sample)
            except Exception:
                now = utc_now()
                self._record_result(now, invalid=True)
                self._set_latest(MmwaveSample(ts=now, state=PresenceCorroborationState.UNKNOWN, valid=False))
                time.sleep(2.0)

    def _parse_state(self, line: str) -> PresenceCorroborationState | None:
        normalized = line.upper()
        if "PRESENT" in normalized or normalized in {"1", "ON", "TRUE"}:
            return PresenceCorroborationState.PRESENT
        if "ABSENT" in normalized or normalized in {"0", "OFF", "FALSE"}:
            return PresenceCorroborationState.ABSENT
        return None
