from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime
from pathlib import Path

import cv2
import numpy as np

from .config import DetectorConfig
from .models import BoundingBox, Detection, DetectionPacket


class DetectorBackend(ABC):
    @abstractmethod
    def detect(self, frame_id: int, ts: datetime, image: np.ndarray) -> DetectionPacket:
        raise NotImplementedError

    def apply_config(self, config: DetectorConfig) -> None:
        return None


class HogPersonDetector(DetectorBackend):
    def __init__(self) -> None:
        self.hog = cv2.HOGDescriptor()
        self.hog.setSVMDetector(cv2.HOGDescriptor_getDefaultPeopleDetector())

    def detect(self, frame_id: int, ts: datetime, image: np.ndarray) -> DetectionPacket:
        start = cv2.getTickCount()
        rects, weights = self.hog.detectMultiScale(
            image,
            winStride=(8, 8),
            padding=(8, 8),
            scale=1.05,
        )
        detections: list[Detection] = []
        for (x, y, w, h), weight in zip(rects, weights, strict=False):
            detections.append(
                Detection(
                    bbox=BoundingBox(
                        x1=int(x),
                        y1=int(y),
                        x2=int(x + w),
                        y2=int(y + h),
                        confidence=float(weight),
                    )
                )
            )
        elapsed = (cv2.getTickCount() - start) * 1000.0 / cv2.getTickFrequency()
        return DetectionPacket(frame_id=frame_id, ts=ts, detections=detections, inference_ms=elapsed)


class UltralyticsDetector(DetectorBackend):
    def __init__(self, model_path: str, imgsz: int, conf: float) -> None:
        try:
            from ultralytics import YOLO  # type: ignore
        except ImportError as exc:
            raise RuntimeError("Ultralytics backend requested but package is not installed.") from exc
        if not model_path:
            raise ValueError("Ultralytics backend requires detector.model_path.")
        path = Path(model_path)
        if path.exists():
            resolved_model = str(path)
        elif path.parent == Path(".") and path.suffix in {".pt", ".onnx"}:
            # Allow Ultralytics model aliases such as `yolo11n.pt` so the package can
            # resolve/download first-party weights on demand.
            resolved_model = model_path
        else:
            raise FileNotFoundError(model_path)
        self.model = YOLO(resolved_model)
        self.imgsz = imgsz
        self.conf = conf

    def detect(self, frame_id: int, ts: datetime, image: np.ndarray) -> DetectionPacket:
        start = cv2.getTickCount()
        results = self.model.predict(
            source=image,
            imgsz=self.imgsz,
            conf=self.conf,
            classes=[0],
            verbose=False,
            device="cpu",
        )
        detections: list[Detection] = []
        for result in results:
            boxes = getattr(result, "boxes", None)
            if boxes is None:
                continue
            xyxy = boxes.xyxy.cpu().numpy()
            confs = boxes.conf.cpu().numpy()
            for coords, conf in zip(xyxy, confs, strict=False):
                x1, y1, x2, y2 = [int(v) for v in coords.tolist()]
                detections.append(
                    Detection(
                        bbox=BoundingBox(x1=x1, y1=y1, x2=x2, y2=y2, confidence=float(conf))
                    )
                )
        elapsed = (cv2.getTickCount() - start) * 1000.0 / cv2.getTickFrequency()
        return DetectionPacket(frame_id=frame_id, ts=ts, detections=detections, inference_ms=elapsed)

    def apply_config(self, config: DetectorConfig) -> None:
        self.imgsz = config.imgsz
        self.conf = config.confidence_threshold


def create_detector(config: DetectorConfig) -> DetectorBackend:
    if config.backend == "ultralytics":
        return UltralyticsDetector(
            model_path=config.model_path,
            imgsz=config.imgsz,
            conf=config.confidence_threshold,
        )
    return HogPersonDetector()
