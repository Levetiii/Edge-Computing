from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime
from pathlib import Path
from typing import Any

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


class MockPersonDetector(DetectorBackend):
    def detect(self, frame_id: int, ts: datetime, image: np.ndarray) -> DetectionPacket:
        start = cv2.getTickCount()
        mask = cv2.inRange(image, (0, 180, 0), (90, 255, 90))
        contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        detections: list[Detection] = []
        for contour in contours:
            x, y, w, h = cv2.boundingRect(contour)
            area = float(w * h)
            if area < 1200:
                continue
            detections.append(
                Detection(
                    bbox=BoundingBox(
                        x1=int(x),
                        y1=int(y),
                        x2=int(x + w),
                        y2=int(y + h),
                        confidence=0.99,
                    )
                )
            )
        elapsed = (cv2.getTickCount() - start) * 1000.0 / cv2.getTickFrequency()
        return DetectionPacket(frame_id=frame_id, ts=ts, detections=detections, inference_ms=elapsed)


class OnnxDetector(DetectorBackend):
    def __init__(self, model_path: str, imgsz: int, conf: float, iou: float) -> None:
        try:
            import onnxruntime as ort  # type: ignore
        except ImportError as exc:
            raise RuntimeError("ONNX backend requested but onnxruntime is not installed.") from exc
        if not model_path:
            raise ValueError("ONNX backend requires detector.model_path.")
        path = Path(model_path)
        if not path.exists():
            raise FileNotFoundError(model_path)
        self.session = ort.InferenceSession(
            str(path),
            sess_options=ort.SessionOptions(),
            providers=["CPUExecutionProvider"],
        )
        inputs = self.session.get_inputs()
        if not inputs:
            raise RuntimeError("ONNX model has no inputs.")
        self.input_name = inputs[0].name
        self.output_names = [output.name for output in self.session.get_outputs()]
        self.static_input_width, self.static_input_height = self._resolve_input_size(inputs[0].shape)
        self.requested_imgsz = imgsz
        self.conf = conf
        self.iou_threshold = iou

    def detect(self, frame_id: int, ts: datetime, image: np.ndarray) -> DetectionPacket:
        start = cv2.getTickCount()
        input_width, input_height = self._input_size()
        tensor, scale, pad_left, pad_top = self._prepare_input(image, input_width, input_height)
        outputs = self.session.run(
            self.output_names,
            {self.input_name: tensor},
        )
        detections = self._decode_detections(
            outputs,
            image_width=image.shape[1],
            image_height=image.shape[0],
            scale=scale,
            pad_left=pad_left,
            pad_top=pad_top,
            input_width=input_width,
            input_height=input_height,
        )
        elapsed = (cv2.getTickCount() - start) * 1000.0 / cv2.getTickFrequency()
        return DetectionPacket(frame_id=frame_id, ts=ts, detections=detections, inference_ms=elapsed)

    def apply_config(self, config: DetectorConfig) -> None:
        self.requested_imgsz = config.imgsz
        self.conf = config.confidence_threshold
        self.iou_threshold = config.iou_threshold

    def _input_size(self) -> tuple[int, int]:
        if self.static_input_width is not None and self.static_input_height is not None:
            return self.static_input_width, self.static_input_height
        return self.requested_imgsz, self.requested_imgsz

    def _prepare_input(
        self,
        image: np.ndarray,
        target_width: int,
        target_height: int,
    ) -> tuple[np.ndarray, float, int, int]:
        image_height, image_width = image.shape[:2]
        scale = min(target_width / image_width, target_height / image_height)
        resized_width = max(1, int(round(image_width * scale)))
        resized_height = max(1, int(round(image_height * scale)))
        resized = cv2.resize(image, (resized_width, resized_height), interpolation=cv2.INTER_LINEAR)

        pad_left = (target_width - resized_width) // 2
        pad_top = (target_height - resized_height) // 2
        canvas = np.full((target_height, target_width, 3), 114, dtype=np.uint8)
        canvas[pad_top : pad_top + resized_height, pad_left : pad_left + resized_width] = resized

        rgb = cv2.cvtColor(canvas, cv2.COLOR_BGR2RGB).astype(np.float32) / 255.0
        tensor = np.ascontiguousarray(np.transpose(rgb, (2, 0, 1))[np.newaxis, ...])
        return tensor, scale, pad_left, pad_top

    def _decode_detections(
        self,
        outputs: list[np.ndarray] | tuple[np.ndarray, ...],
        *,
        image_width: int,
        image_height: int,
        scale: float,
        pad_left: int,
        pad_top: int,
        input_width: int,
        input_height: int,
    ) -> list[Detection]:
        output = self._pick_primary_output(outputs)
        candidates = self._decode_output_array(
            output,
            image_width=image_width,
            image_height=image_height,
            scale=scale,
            pad_left=pad_left,
            pad_top=pad_top,
            input_width=input_width,
            input_height=input_height,
        )
        filtered = self._nms(candidates)
        detections: list[Detection] = []
        for x1, y1, x2, y2, confidence in filtered:
            detections.append(
                Detection(
                    bbox=BoundingBox(
                        x1=int(round(x1)),
                        y1=int(round(y1)),
                        x2=int(round(x2)),
                        y2=int(round(y2)),
                        confidence=float(confidence),
                    )
                )
            )
        return detections

    def _decode_output_array(
        self,
        output: np.ndarray,
        *,
        image_width: int,
        image_height: int,
        scale: float,
        pad_left: int,
        pad_top: int,
        input_width: int,
        input_height: int,
    ) -> list[tuple[float, float, float, float, float]]:
        array = np.asarray(output)
        if array.ndim == 3 and array.shape[0] == 1:
            array = array[0]
        if array.ndim == 1:
            array = array[np.newaxis, :]
        if array.ndim != 2:
            raise RuntimeError(f"Unsupported ONNX output shape: {array.shape!r}")
        if array.shape[0] in (84, 85) or (array.shape[0] in (6, 7) and array.shape[1] > array.shape[0]):
            array = array.T
        if array.shape[1] in (6, 7):
            return self._decode_nms_output(
                array,
                image_width=image_width,
                image_height=image_height,
                scale=scale,
                pad_left=pad_left,
                pad_top=pad_top,
                input_width=input_width,
                input_height=input_height,
            )
        return self._decode_raw_output(
            array,
            image_width=image_width,
            image_height=image_height,
            scale=scale,
            pad_left=pad_left,
            pad_top=pad_top,
            input_width=input_width,
            input_height=input_height,
        )

    def _decode_raw_output(
        self,
        predictions: np.ndarray,
        *,
        image_width: int,
        image_height: int,
        scale: float,
        pad_left: int,
        pad_top: int,
        input_width: int,
        input_height: int,
    ) -> list[tuple[float, float, float, float, float]]:
        if predictions.shape[1] < 6:
            return []
        if predictions.shape[1] >= 85:
            class_scores = predictions[:, 5:]
            objectness = predictions[:, 4]
            best_class = np.argmax(class_scores, axis=1)
            best_score = objectness * class_scores[np.arange(len(predictions)), best_class]
        else:
            class_scores = predictions[:, 4:]
            best_class = np.argmax(class_scores, axis=1)
            best_score = class_scores[np.arange(len(predictions)), best_class]
        keep_mask = (best_class == 0) & (best_score >= self.conf)
        selected = predictions[keep_mask]
        scores = best_score[keep_mask]
        candidates: list[tuple[float, float, float, float, float]] = []
        for row, score in zip(selected, scores, strict=False):
            cx, cy, width, height = [float(value) for value in row[:4]]
            if max(abs(cx), abs(cy), abs(width), abs(height)) <= 2.0:
                cx *= input_width
                cy *= input_height
                width *= input_width
                height *= input_height
            x1 = cx - width / 2.0
            y1 = cy - height / 2.0
            x2 = cx + width / 2.0
            y2 = cy + height / 2.0
            restored = self._restore_box(
                x1,
                y1,
                x2,
                y2,
                score=float(score),
                image_width=image_width,
                image_height=image_height,
                scale=scale,
                pad_left=pad_left,
                pad_top=pad_top,
                input_width=input_width,
                input_height=input_height,
            )
            if restored is not None:
                candidates.append(restored)
        return candidates

    def _decode_nms_output(
        self,
        predictions: np.ndarray,
        *,
        image_width: int,
        image_height: int,
        scale: float,
        pad_left: int,
        pad_top: int,
        input_width: int,
        input_height: int,
    ) -> list[tuple[float, float, float, float, float]]:
        candidates: list[tuple[float, float, float, float, float]] = []
        for row in predictions:
            if len(row) == 6:
                x1, y1, x2, y2, score, class_id = [float(value) for value in row]
            elif len(row) >= 7 and abs(row[0] - round(row[0])) < 1e-6:
                _, x1, y1, x2, y2, class_id, score = [float(value) for value in row[:7]]
            else:
                x1, y1, x2, y2, score, class_id = [float(value) for value in row[:6]]
            if int(round(class_id)) != 0 or score < self.conf:
                continue
            restored = self._restore_box(
                x1,
                y1,
                x2,
                y2,
                score=score,
                image_width=image_width,
                image_height=image_height,
                scale=scale,
                pad_left=pad_left,
                pad_top=pad_top,
                input_width=input_width,
                input_height=input_height,
            )
            if restored is not None:
                candidates.append(restored)
        return candidates

    def _restore_box(
        self,
        x1: float,
        y1: float,
        x2: float,
        y2: float,
        *,
        score: float,
        image_width: int,
        image_height: int,
        scale: float,
        pad_left: int,
        pad_top: int,
        input_width: int,
        input_height: int,
    ) -> tuple[float, float, float, float, float] | None:
        if max(abs(x1), abs(y1), abs(x2), abs(y2)) <= 2.0:
            x1 *= input_width
            y1 *= input_height
            x2 *= input_width
            y2 *= input_height
        x1 = (x1 - pad_left) / scale
        y1 = (y1 - pad_top) / scale
        x2 = (x2 - pad_left) / scale
        y2 = (y2 - pad_top) / scale
        x1 = float(np.clip(x1, 0, image_width))
        y1 = float(np.clip(y1, 0, image_height))
        x2 = float(np.clip(x2, 0, image_width))
        y2 = float(np.clip(y2, 0, image_height))
        if x2 <= x1 or y2 <= y1:
            return None
        return x1, y1, x2, y2, score

    def _nms(
        self,
        candidates: list[tuple[float, float, float, float, float]],
    ) -> list[tuple[float, float, float, float, float]]:
        if not candidates:
            return []
        boxes = np.asarray([candidate[:4] for candidate in candidates], dtype=np.float32)
        scores = np.asarray([candidate[4] for candidate in candidates], dtype=np.float32)
        order = scores.argsort()[::-1]
        kept: list[tuple[float, float, float, float, float]] = []
        while order.size > 0:
            current = int(order[0])
            kept.append(candidates[current])
            if order.size == 1:
                break
            remaining = order[1:]
            ious = self._iou(boxes[current], boxes[remaining])
            order = remaining[ious <= self.iou_threshold]
        return kept

    @staticmethod
    def _iou(box: np.ndarray, boxes: np.ndarray) -> np.ndarray:
        if boxes.size == 0:
            return np.asarray([], dtype=np.float32)
        x1 = np.maximum(box[0], boxes[:, 0])
        y1 = np.maximum(box[1], boxes[:, 1])
        x2 = np.minimum(box[2], boxes[:, 2])
        y2 = np.minimum(box[3], boxes[:, 3])
        intersection = np.maximum(0.0, x2 - x1) * np.maximum(0.0, y2 - y1)
        box_area = max(0.0, box[2] - box[0]) * max(0.0, box[3] - box[1])
        boxes_area = np.maximum(0.0, boxes[:, 2] - boxes[:, 0]) * np.maximum(0.0, boxes[:, 3] - boxes[:, 1])
        union = box_area + boxes_area - intersection
        return np.divide(intersection, union, out=np.zeros_like(intersection), where=union > 0)

    @staticmethod
    def _pick_primary_output(outputs: list[np.ndarray] | tuple[np.ndarray, ...]) -> np.ndarray:
        arrays = [np.asarray(output) for output in outputs if isinstance(output, np.ndarray)]
        if not arrays:
            raise RuntimeError("ONNX detector returned no ndarray outputs.")
        return max(arrays, key=lambda item: (item.ndim, item.size))

    @staticmethod
    def _resolve_input_size(shape: list[Any] | tuple[Any, ...]) -> tuple[int | None, int | None]:
        if len(shape) < 4:
            return None, None
        height = OnnxDetector._positive_int(shape[2])
        width = OnnxDetector._positive_int(shape[3])
        return width, height

    @staticmethod
    def _positive_int(value: Any) -> int | None:
        if isinstance(value, (int, np.integer)) and int(value) > 0:
            return int(value)
        return None


def create_detector(config: DetectorConfig) -> DetectorBackend:
    if config.backend == "onnx":
        return OnnxDetector(
            model_path=config.model_path,
            imgsz=config.imgsz,
            conf=config.confidence_threshold,
            iou=config.iou_threshold,
        )
    return MockPersonDetector()
