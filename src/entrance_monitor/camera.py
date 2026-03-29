from __future__ import annotations

import platform
import threading
import time
from collections import deque
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Iterable

import cv2
import numpy as np

from .config import CameraConfig
from .models import FramePacket
from .utils import utc_now


@dataclass
class CameraStats:
    attempted_frames: int = 0
    captured_frames: int = 0
    last_frame_ts: datetime | None = None
    delivered_fps: float = 0.0
    expected_fps: float = 0.0
    negotiated_fps: float = 0.0
    negotiated_width: int = 0
    negotiated_height: int = 0
    source_kind: str = "webcam"
    last_read_ms: float | None = None


VIDEO_FILE_EXTENSIONS = {
    ".avi",
    ".m4v",
    ".mkv",
    ".mov",
    ".mp4",
    ".mpeg",
    ".mpg",
    ".webm",
}


class CameraSource:
    def __init__(self, config: CameraConfig) -> None:
        self.config = config
        self._lock = threading.Lock()
        self._latest: FramePacket | None = None
        self._running = threading.Event()
        self._thread: threading.Thread | None = None
        self._frame_id = 0
        self.stats = CameraStats(expected_fps=float(config.fps))
        self._fps_window: deque[datetime] = deque()

    def start(self) -> None:
        self._running.set()
        self._thread = threading.Thread(target=self._run, name="camera-source", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._running.clear()
        if self._thread:
            self._thread.join(timeout=2)

    def latest(self) -> FramePacket | None:
        with self._lock:
            return self._latest

    def _set_latest(self, packet: FramePacket) -> None:
        with self._lock:
            self._latest = packet

    def _run(self) -> None:
        if self.config.source == "mock":
            self._run_mock()
            return
        video_path = self._video_source_path()
        if video_path is not None:
            self._run_video_file(video_path)
            return
        self.stats.source_kind = "webcam"
        while self._running.is_set():
            opened = False
            for backend in self._backend_candidates():
                capture = cv2.VideoCapture(self.config.source, backend)
                if self._should_configure_capture_properties():
                    capture.set(cv2.CAP_PROP_FRAME_WIDTH, self.config.width)
                    capture.set(cv2.CAP_PROP_FRAME_HEIGHT, self.config.height)
                    capture.set(cv2.CAP_PROP_FPS, self.config.fps)
                if not capture.isOpened():
                    capture.release()
                    continue
                self._record_capture_profile(
                    width=int(round(capture.get(cv2.CAP_PROP_FRAME_WIDTH))),
                    height=int(round(capture.get(cv2.CAP_PROP_FRAME_HEIGHT))),
                    fps=float(capture.get(cv2.CAP_PROP_FPS)),
                    clamp_fps=False,
                )
                opened = True
                read_failures = 0
                try:
                    while self._running.is_set():
                        self.stats.attempted_frames += 1
                        read_started = time.perf_counter()
                        ok, frame = capture.read()
                        self.stats.last_read_ms = (time.perf_counter() - read_started) * 1000.0
                        if not ok or frame is None:
                            read_failures += 1
                            if read_failures >= 5:
                                break
                            time.sleep(0.05)
                            continue
                        read_failures = 0
                        self._record_capture_profile(width=frame.shape[1], height=frame.shape[0])
                        self._emit(frame)
                finally:
                    capture.release()
                if not self._running.is_set():
                    return
            time.sleep(self.config.reconnect_seconds if opened else min(2.0, self.config.reconnect_seconds))

    def _run_mock(self) -> None:
        self.stats.source_kind = "mock"
        self.stats.expected_fps = float(self.config.fps)
        self.stats.negotiated_fps = float(self.config.fps)
        self.stats.negotiated_width = self.config.width
        self.stats.negotiated_height = self.config.height
        present = True
        switch_at = time.monotonic() + 4.0
        x = 100
        direction = 12
        while self._running.is_set():
            frame = np.zeros((self.config.height, self.config.width, 3), dtype=np.uint8)
            cv2.putText(
                frame,
                "MOCK CAMERA",
                (20, 40),
                cv2.FONT_HERSHEY_SIMPLEX,
                1.0,
                (255, 255, 255),
                2,
            )
            if present:
                cv2.rectangle(frame, (x, 200), (x + 120, 520), (0, 255, 0), -1)
                x += direction
                if x > self.config.width - 140 or x < 20:
                    direction *= -1
            if time.monotonic() >= switch_at:
                present = not present
                switch_at = time.monotonic() + 6.0
            self._emit(frame)
            time.sleep(max(0.0, 1.0 / max(self.config.fps, 1)))

    def _video_source_path(self) -> Path | None:
        if not isinstance(self.config.source, str):
            return None
        path = Path(self.config.source)
        if path.is_file() and path.suffix.lower() in VIDEO_FILE_EXTENSIONS:
            return path
        return None

    def _run_video_file(self, video_path: Path) -> None:
        self.stats.source_kind = "video"
        while self._running.is_set():
            capture = cv2.VideoCapture(str(video_path), cv2.CAP_ANY)
            if not capture.isOpened():
                capture.release()
                time.sleep(min(2.0, self.config.reconnect_seconds))
                continue
            source_fps = capture.get(cv2.CAP_PROP_FPS)
            self._record_capture_profile(
                width=int(round(capture.get(cv2.CAP_PROP_FRAME_WIDTH))),
                height=int(round(capture.get(cv2.CAP_PROP_FRAME_HEIGHT))),
                fps=float(source_fps),
                clamp_fps=True,
            )
            if self.stats.expected_fps <= 0.0:
                self.stats.expected_fps = float(self.config.fps)
            frame_interval = 1.0 / max(self.stats.expected_fps, 1.0)
            try:
                while self._running.is_set():
                    started = time.monotonic()
                    self.stats.attempted_frames += 1
                    read_started = time.perf_counter()
                    ok, frame = capture.read()
                    self.stats.last_read_ms = (time.perf_counter() - read_started) * 1000.0
                    if not ok or frame is None:
                        break
                    if frame.shape[1] != self.config.width or frame.shape[0] != self.config.height:
                        frame = cv2.resize(frame, (self.config.width, self.config.height))
                    self._record_capture_profile(width=frame.shape[1], height=frame.shape[0])
                    self._emit(frame)
                    elapsed = time.monotonic() - started
                    time.sleep(max(0.0, frame_interval - elapsed))
            finally:
                capture.release()
            if not self._running.is_set():
                return

    def _backend_candidates(self) -> list[int]:
        if self.config.backend == "v4l2":
            return [cv2.CAP_V4L2]
        if self.config.backend == "msmf":
            return [cv2.CAP_MSMF]
        if self.config.backend == "dshow":
            return [cv2.CAP_DSHOW]
        if self.config.backend == "any":
            return [cv2.CAP_ANY]
        system = platform.system().lower()
        if system == "linux":
            return [cv2.CAP_V4L2, cv2.CAP_ANY]
        if system == "windows":
            return [cv2.CAP_DSHOW, cv2.CAP_MSMF, cv2.CAP_ANY]
        return [cv2.CAP_ANY]

    def _should_configure_capture_properties(self) -> bool:
        system = platform.system().lower()
        if system == "windows":
            return False
        return True

    def _emit(self, frame: np.ndarray) -> None:
        now = utc_now()
        self.stats.captured_frames += 1
        self.stats.last_frame_ts = now
        self._fps_window.append(now)
        while self._fps_window and (now - self._fps_window[0]).total_seconds() > 1.0:
            self._fps_window.popleft()
        self.stats.delivered_fps = float(len(self._fps_window))
        self._frame_id += 1
        roi_x1, roi_y1, roi_x2, roi_y2 = self._scaled_roi_bounds(frame.shape[1], frame.shape[0])
        line_x1, line_y1, line_x2, line_y2 = self._scaled_line(frame.shape[1], frame.shape[0])
        roi = frame[roi_y1:roi_y2, roi_x1:roi_x2]
        packet = FramePacket(
            frame_id=self._frame_id,
            ts=now,
            width=frame.shape[1],
            height=frame.shape[0],
            roi_x1=roi_x1,
            roi_y1=roi_y1,
            roi_x2=roi_x2,
            roi_y2=roi_y2,
            roi_width=roi.shape[1],
            roi_height=roi.shape[0],
            line_x1=line_x1,
            line_y1=line_y1,
            line_x2=line_x2,
            line_y2=line_y2,
            delivered_fps=self.stats.delivered_fps,
            image=frame,
            roi_image=roi,
        )
        self._set_latest(packet)

    def _record_capture_profile(
        self,
        *,
        width: int | None = None,
        height: int | None = None,
        fps: float | None = None,
        clamp_fps: bool = False,
    ) -> None:
        if width is not None and width > 0:
            self.stats.negotiated_width = int(width)
        if height is not None and height > 0:
            self.stats.negotiated_height = int(height)
        if fps is None:
            return
        if 1.0 <= fps <= 240.0:
            negotiated_fps = float(fps)
            self.stats.negotiated_fps = negotiated_fps
            self.stats.expected_fps = min(negotiated_fps, float(self.config.fps)) if clamp_fps else negotiated_fps

    def _scaled_roi_bounds(self, frame_width: int, frame_height: int) -> tuple[int, int, int, int]:
        scale_x = frame_width / max(self.config.width, 1)
        scale_y = frame_height / max(self.config.height, 1)
        x1 = self._clamp(round(self.config.roi.x1 * scale_x), 0, max(0, frame_width - 1))
        y1 = self._clamp(round(self.config.roi.y1 * scale_y), 0, max(0, frame_height - 1))
        x2 = self._clamp(round(self.config.roi.x2 * scale_x), x1 + 1, frame_width)
        y2 = self._clamp(round(self.config.roi.y2 * scale_y), y1 + 1, frame_height)
        return x1, y1, x2, y2

    def _scaled_line(self, frame_width: int, frame_height: int) -> tuple[int, int, int, int]:
        scale_x = frame_width / max(self.config.width, 1)
        scale_y = frame_height / max(self.config.height, 1)
        x1 = self._clamp(round(self.config.line.x1 * scale_x), 0, max(0, frame_width - 1))
        y1 = self._clamp(round(self.config.line.y1 * scale_y), 0, max(0, frame_height - 1))
        x2 = self._clamp(round(self.config.line.x2 * scale_x), 0, max(0, frame_width - 1))
        y2 = self._clamp(round(self.config.line.y2 * scale_y), 0, max(0, frame_height - 1))
        return x1, y1, x2, y2

    @staticmethod
    def _clamp(value: int, lower: int, upper: int) -> int:
        return max(lower, min(value, upper))
