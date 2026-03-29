#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path
from typing import Iterator

import cv2
import numpy as np


IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".bmp", ".webp"}


def resolve_input_size(model_path: Path, fallback_imgsz: int) -> tuple[int, int]:
    import onnxruntime as ort  # type: ignore

    session = ort.InferenceSession(str(model_path), providers=["CPUExecutionProvider"])
    inputs = session.get_inputs()
    if not inputs:
        raise RuntimeError("ONNX model has no inputs.")
    shape = inputs[0].shape
    if len(shape) >= 4:
        height = shape[2] if isinstance(shape[2], int) and shape[2] > 0 else None
        width = shape[3] if isinstance(shape[3], int) and shape[3] > 0 else None
        if width and height:
            return int(width), int(height)
    return fallback_imgsz, fallback_imgsz


def prepare_input(image: np.ndarray, target_width: int, target_height: int) -> np.ndarray:
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
    return np.ascontiguousarray(np.transpose(rgb, (2, 0, 1))[np.newaxis, ...])


def iter_calibration_images(root: Path) -> Iterator[Path]:
    for path in sorted(root.rglob("*")):
        if path.is_file() and path.suffix.lower() in IMAGE_EXTENSIONS:
            yield path


class ImageCalibrationReader:
    def __init__(
        self,
        input_name: str,
        image_paths: list[Path],
        *,
        input_width: int,
        input_height: int,
    ) -> None:
        self.input_name = input_name
        self.image_paths = image_paths
        self.input_width = input_width
        self.input_height = input_height
        self._index = 0

    def get_next(self) -> dict[str, np.ndarray] | None:
        if self._index >= len(self.image_paths):
            return None
        path = self.image_paths[self._index]
        self._index += 1
        image = cv2.imread(str(path))
        if image is None:
            return self.get_next()
        return {
            self.input_name: prepare_input(
                image,
                target_width=self.input_width,
                target_height=self.input_height,
            )
        }

    def rewind(self) -> None:
        self._index = 0


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Offline static INT8 quantization for the ONNX detector model."
    )
    parser.add_argument("--input", default="yolo11n.onnx", help="Path to the fp32 ONNX model.")
    parser.add_argument("--output", default="yolo11n.int8.onnx", help="Path for the INT8 ONNX model.")
    parser.add_argument(
        "--calibration-dir",
        required=True,
        help="Directory containing representative doorway images for calibration.",
    )
    parser.add_argument(
        "--imgsz",
        type=int,
        default=320,
        help="Fallback square input size when the ONNX model input shape is dynamic.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=200,
        help="Maximum number of calibration images to use.",
    )
    parser.add_argument(
        "--per-channel",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Enable per-channel weight quantization.",
    )
    args = parser.parse_args()

    model_input = Path(args.input)
    model_output = Path(args.output)
    calibration_dir = Path(args.calibration_dir)

    if not model_input.exists():
        raise FileNotFoundError(model_input)
    if not calibration_dir.exists():
        raise FileNotFoundError(calibration_dir)

    try:
        import onnxruntime as ort  # type: ignore
        from onnxruntime.quantization import (  # type: ignore
            CalibrationDataReader,
            QuantFormat,
            QuantType,
            quantize_static,
        )
    except ImportError as exc:
        raise RuntimeError(
            "Quantization requires onnxruntime quantization support and the onnx package. "
            "Install with: pip install -e .[export]"
        ) from exc

    session = ort.InferenceSession(str(model_input), providers=["CPUExecutionProvider"])
    inputs = session.get_inputs()
    if not inputs:
        raise RuntimeError("ONNX model has no inputs.")
    input_name = inputs[0].name
    input_width, input_height = resolve_input_size(model_input, args.imgsz)

    image_paths = list(iter_calibration_images(calibration_dir))
    if not image_paths:
        raise RuntimeError(f"No calibration images found in {calibration_dir}")
    if args.limit > 0:
        image_paths = image_paths[: args.limit]

    class Reader(CalibrationDataReader):
        def __init__(self) -> None:
            self._reader = ImageCalibrationReader(
                input_name=input_name,
                image_paths=image_paths,
                input_width=input_width,
                input_height=input_height,
            )

        def get_next(self) -> dict[str, np.ndarray] | None:
            return self._reader.get_next()

        def rewind(self) -> None:
            self._reader.rewind()

    quantize_static(
        model_input=str(model_input),
        model_output=str(model_output),
        calibration_data_reader=Reader(),
        quant_format=QuantFormat.QDQ,
        activation_type=QuantType.QUInt8,
        weight_type=QuantType.QInt8,
        per_channel=args.per_channel,
    )

    print(str(model_output.resolve()))


if __name__ == "__main__":
    main()
