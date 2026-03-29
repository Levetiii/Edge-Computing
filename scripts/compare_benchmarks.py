#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path


DEFAULT_METRICS = (
    "delivered_fps",
    "detector_fps",
    "drop_ratio_30s",
    "cpu_percent",
    "ram_mb",
    "temperature_c",
    "detector_inference_ms",
    "detector_total_ms",
    "process_camera_total_ms",
)


def load_summary(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def metric_cell(run: dict, metric: str) -> str:
    stats = (run.get("metrics") or {}).get(metric) or {}
    avg = stats.get("avg")
    p95 = stats.get("p95")
    max_value = stats.get("max")
    if avg is None and p95 is None and max_value is None:
        return "N/A"
    parts = []
    if avg is not None:
        parts.append(f"avg={avg}")
    if p95 is not None:
        parts.append(f"p95={p95}")
    if max_value is not None:
        parts.append(f"max={max_value}")
    return ", ".join(parts)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Compare multiple PASO benchmark summary.json files."
    )
    parser.add_argument(
        "summaries",
        nargs="+",
        help="Paths to summary.json files produced by scripts/paso_benchmark.py",
    )
    parser.add_argument(
        "--labels",
        nargs="*",
        help="Optional labels to use instead of parent directory names.",
    )
    parser.add_argument(
        "--output",
        help="Output Markdown path. Defaults to benchmark_comparison.md beside the first summary.",
    )
    args = parser.parse_args()

    summary_paths = [Path(item) for item in args.summaries]
    runs = [load_summary(path) for path in summary_paths]

    if args.labels and len(args.labels) != len(summary_paths):
        raise ValueError("--labels must match the number of summary files.")

    labels = args.labels or [path.parent.name for path in summary_paths]
    output_path = (
        Path(args.output)
        if args.output
        else summary_paths[0].parent / "benchmark_comparison.md"
    )

    lines = [
        "# PASO Benchmark Comparison",
        "",
        "| Run | Target capture FPS | Target detector FPS | Dominant camera status | Dominant system state |",
        "|-----|--------------------|---------------------|------------------------|-----------------------|",
    ]
    for label, run in zip(labels, runs, strict=False):
        targets = run.get("targets") or {}
        dominant = run.get("dominant_status") or {}
        lines.append(
            f"| {label} | {targets.get('target_capture_fps', 'N/A')} | "
            f"{targets.get('target_detector_fps', 'N/A')} | "
            f"{dominant.get('camera_status', 'N/A')} | "
            f"{dominant.get('system_state', 'N/A')} |"
        )

    lines.extend(
        [
            "",
            "| Metric | " + " | ".join(labels) + " |",
            "|--------|" + "|".join(["---"] * len(labels)) + "|",
        ]
    )
    for metric in DEFAULT_METRICS:
        row = [metric]
        for run in runs:
            row.append(metric_cell(run, metric))
        lines.append("| " + " | ".join(row) + " |")

    output_path.write_text("\n".join(lines), encoding="utf-8")
    print(str(output_path.resolve()))


if __name__ == "__main__":
    main()
