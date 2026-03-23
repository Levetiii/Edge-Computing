from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

import numpy as np

from entrance_monitor.config import DetectorConfig
from entrance_monitor.detector import MockPersonDetector, OnnxDetector, create_detector


class _FakeIoMeta:
    def __init__(self, name: str, shape):
        self.name = name
        self.shape = shape


class _FakeSession:
    output = np.zeros((1, 84, 0), dtype=np.float32)
    last_feed_shape: tuple[int, ...] | None = None

    def __init__(self, model_path: str, sess_options=None, providers=None) -> None:
        self.model_path = model_path
        self.sess_options = sess_options
        self.providers = providers

    def get_inputs(self):
        return [_FakeIoMeta("images", [1, 3, 640, 640])]

    def get_outputs(self):
        return [_FakeIoMeta("output0", [1, 84, 8400])]

    def run(self, output_names, feeds):
        _FakeSession.last_feed_shape = tuple(next(iter(feeds.values())).shape)
        return [self.output]


def test_detector_config_maps_legacy_ultralytics_to_onnx():
    config = DetectorConfig.model_validate(
        {
            "backend": "ultralytics",
            "model_path": "yolo11n.pt",
            "confidence_threshold": 0.25,
            "iou_threshold": 0.4,
            "imgsz": 416,
        }
    )
    assert config.backend == "onnx"
    assert config.model_path == "yolo11n.onnx"


def test_detector_config_maps_legacy_hog_to_mock():
    config = DetectorConfig.model_validate({"backend": "hog"})
    assert config.backend == "mock"


def test_create_detector_supports_onnx_backend(tmp_path, monkeypatch):
    model_path = tmp_path / "model.onnx"
    model_path.write_bytes(b"fake")
    monkeypatch.setitem(
        sys.modules,
        "onnxruntime",
        SimpleNamespace(InferenceSession=_FakeSession, SessionOptions=lambda: object()),
    )
    detector = create_detector(
        DetectorConfig(
            backend="onnx",
            model_path=str(model_path),
            confidence_threshold=0.25,
            iou_threshold=0.4,
            imgsz=416,
        )
    )
    assert isinstance(detector, OnnxDetector)


def test_onnx_detector_decodes_person_output(tmp_path, monkeypatch):
    model_path = tmp_path / "model.onnx"
    model_path.write_bytes(b"fake")
    predictions = np.zeros((1, 84, 2), dtype=np.float32)
    predictions[0, 0, 0] = 320.0
    predictions[0, 1, 0] = 320.0
    predictions[0, 2, 0] = 160.0
    predictions[0, 3, 0] = 200.0
    predictions[0, 4, 0] = 0.92
    predictions[0, 5, 0] = 0.10
    predictions[0, 0, 1] = 120.0
    predictions[0, 1, 1] = 120.0
    predictions[0, 2, 1] = 80.0
    predictions[0, 3, 1] = 100.0
    predictions[0, 4, 1] = 0.10
    predictions[0, 5, 1] = 0.95
    _FakeSession.output = predictions
    _FakeSession.last_feed_shape = None
    monkeypatch.setitem(
        sys.modules,
        "onnxruntime",
        SimpleNamespace(InferenceSession=_FakeSession, SessionOptions=lambda: object()),
    )
    detector = OnnxDetector(
        model_path=str(model_path),
        imgsz=416,
        conf=0.25,
        iou=0.4,
    )
    image = np.zeros((640, 640, 3), dtype=np.uint8)
    packet = detector.detect(frame_id=1, ts=datetime.utcnow(), image=image)
    assert _FakeSession.last_feed_shape == (1, 3, 640, 640)
    assert len(packet.detections) == 1
    bbox = packet.detections[0].bbox
    assert bbox.confidence >= 0.9
    assert (bbox.x1, bbox.y1, bbox.x2, bbox.y2) == (240, 220, 400, 420)


def test_mock_detector_finds_synthetic_person_rectangle():
    detector = MockPersonDetector()
    image = np.zeros((720, 1280, 3), dtype=np.uint8)
    image[200:520, 100:220] = (0, 255, 0)
    packet = detector.detect(frame_id=1, ts=datetime.utcnow(), image=image)
    assert len(packet.detections) == 1
    bbox = packet.detections[0].bbox
    assert (bbox.x1, bbox.y1, bbox.x2, bbox.y2) == (100, 200, 220, 520)


def test_create_detector_returns_mock_for_mock_backend():
    detector = create_detector(DetectorConfig())
    assert isinstance(detector, MockPersonDetector)
