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

# ---------------------------------------------------------------------------
# MR24HPC1 binary protocol constants (standard presence mode)
# The sensor sends variable-length frames with this structure:
#   [0x53][0x59] [ctrl] [cmd] [len_hi][len_lo] [data...] [checksum][0x54][0x43]
# We care about control=0x80, command=0x03 (movement signs report):
#   data[0] == 0x00 → no one present
#   data[0] == 0x01 → someone present, stationary
#   data[0] >= 0x06 → someone present, moving
#
# In small/enclosed rooms the sensor picks up background at 0x01-0x06 even
# when nobody is at the entrance. We use a sliding window majority vote:
# only declare PRESENT if enough recent samples exceed ACTIVITY_THRESHOLD,
# and only declare ABSENT if enough recent samples are below it.
# ---------------------------------------------------------------------------
_FRAME_HEADER = bytes([0x53, 0x59])
_FRAME_TAIL = bytes([0x54, 0x43])
_CTRL_PRESENCE = 0x80
_CMD_PRESENCE = 0x03

# Samples >= this are counted as "active" votes
_ACTIVITY_THRESHOLD = 0x08

# Sliding window: keep samples from the last N seconds
_WINDOW_SECONDS = 5.0

# Fraction of samples in the window that must be "active" to flip to PRESENT
_PRESENT_VOTE_RATIO = 0.4

# Fraction of samples that must be "inactive" to flip to ABSENT
_ABSENT_VOTE_RATIO = 0.7

_MAX_FRAME_LEN = 256


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
        # Sliding window of (monotonic_time, value) tuples for voting
        self._vote_window: deque[tuple[float, int]] = deque()
        self._voted_state: PresenceCorroborationState = PresenceCorroborationState.UNKNOWN

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
                    # Restore standard presence mode on every connect.
                    # The MR24HPC1 can drift into raw data mode; this ensures
                    # ctrl=0x80 cmd=0x03 presence frames are always output.
                    _restore = bytearray([0x53, 0x59, 0x08, 0x00, 0x00, 0x01, 0x00])
                    _restore += bytearray([sum(_restore) & 0xFF, 0x54, 0x43])
                    ser.write(_restore)
                    time.sleep(1.0)  # give sensor time to switch mode
                    buf = bytearray()
                    while self._running.is_set():
                        chunk = ser.read(64)
                        if not chunk:
                            continue
                        buf.extend(chunk)
                        now = utc_now()
                        raw_value, buf = self._drain_frames(buf)
                        if raw_value is not None:
                            state = self._vote(raw_value)
                            sample = MmwaveSample(
                                ts=now,
                                state=state,
                                valid=True,
                                raw=str(raw_value),
                            )
                            self.stats.last_sample_ts = now
                            self._record_result(now, invalid=False)
                            self._set_latest(sample)
                        if len(buf) > _MAX_FRAME_LEN * 4:
                            buf = buf[-_MAX_FRAME_LEN:]
            except Exception:
                now = utc_now()
                self._record_result(now, invalid=True)
                self._set_latest(MmwaveSample(ts=now, state=PresenceCorroborationState.UNKNOWN, valid=False))
                time.sleep(2.0)

    def _vote(self, raw_value: int) -> PresenceCorroborationState:
        """
        Sliding window majority vote to smooth noisy sensor output.
        Prevents false triggers from background activity in small rooms.
        """
        now_mono = time.monotonic()
        self._vote_window.append((now_mono, raw_value))
        cutoff = now_mono - _WINDOW_SECONDS
        while self._vote_window and self._vote_window[0][0] < cutoff:
            self._vote_window.popleft()

        total = len(self._vote_window)
        if total == 0:
            return self._voted_state

        active = sum(1 for _, v in self._vote_window if v >= _ACTIVITY_THRESHOLD)
        active_ratio = active / total
        inactive_ratio = 1.0 - active_ratio

        if inactive_ratio >= _PRESENT_VOTE_RATIO:
            self._voted_state = PresenceCorroborationState.PRESENT
        elif active_ratio >= _ABSENT_VOTE_RATIO:
            self._voted_state = PresenceCorroborationState.ABSENT

        return self._voted_state

    def _drain_frames(self, buf: bytearray) -> tuple[int | None, bytearray]:
        last_value: int | None = None
        while True:
            idx = buf.find(_FRAME_HEADER)
            if idx == -1:
                buf = buf[-1:] if buf else bytearray()
                break
            if idx > 0:
                buf = buf[idx:]
            if len(buf) < 6:
                break
            ctrl = buf[2]
            cmd = buf[3]
            data_len = (buf[4] << 8) | buf[5]
            total = 6 + data_len + 3
            if total > _MAX_FRAME_LEN:
                buf = buf[2:]
                continue
            if len(buf) < total:
                break
            tail_start = 6 + data_len + 1
            if buf[tail_start: tail_start + 2] != _FRAME_TAIL:
                buf = buf[2:]
                continue
            if ctrl == _CTRL_PRESENCE and cmd == _CMD_PRESENCE and data_len >= 1:
                last_value = buf[6]
            buf = buf[total:]
        return last_value, buf
