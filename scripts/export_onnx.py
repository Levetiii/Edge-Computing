from __future__ import annotations

import argparse
import shutil
from pathlib import Path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Export a pretrained YOLO .pt model to ONNX.")
    parser.add_argument(
        "--weights",
        default="yolo11n.pt",
        help="Path to the pretrained .pt weights file.",
    )
    parser.add_argument(
        "--output",
        default="yolo11n.onnx",
        help="Path for the exported .onnx file.",
    )
    parser.add_argument(
        "--imgsz",
        type=int,
        default=416,
        help="Inference image size to bake into the ONNX export.",
    )
    parser.add_argument(
        "--opset",
        type=int,
        default=12,
        help="ONNX opset version to request from Ultralytics.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    weights_path = Path(args.weights).resolve()
    output_path = Path(args.output).resolve()
    if not weights_path.exists():
        raise FileNotFoundError(weights_path)

    try:
        from ultralytics import YOLO  # type: ignore
    except ImportError as exc:  # pragma: no cover - exercised manually
        raise RuntimeError(
            "Ultralytics is not installed. Install the export toolchain with `pip install -e .[export]`."
        ) from exc

    model = YOLO(str(weights_path))
    exported = Path(
        model.export(
            format="onnx",
            imgsz=args.imgsz,
            opset=args.opset,
            simplify=False,
        )
    ).resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    if exported != output_path:
        shutil.copy2(exported, output_path)
    print(output_path)


if __name__ == "__main__":
    main()
