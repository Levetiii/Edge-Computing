#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import json
import math
import statistics
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path


def utc_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def api_get_json(url: str) -> dict:
    with urllib.request.urlopen(url, timeout=10) as response:
        return json.loads(response.read().decode())


def percentile(values: list[float], pct: float) -> float | None:
    if not values:
        return None
    if len(values) == 1:
        return values[0]
    ordered = sorted(values)
    rank = (len(ordered) - 1) * pct
    lower = math.floor(rank)
    upper = math.ceil(rank)
    if lower == upper:
        return ordered[lower]
    weight = rank - lower
    return ordered[lower] * (1 - weight) + ordered[upper] * weight


def summarize_numeric(samples: list[dict], field: str) -> dict[str, float | None]:
    values = [float(item[field]) for item in samples if item.get(field) is not None]
    if not values:
        return {"avg": None, "min": None, "max": None, "p95": None}
    return {
        "avg": round(statistics.fmean(values), 2),
        "min": round(min(values), 2),
        "max": round(max(values), 2),
        "p95": round(percentile(values, 0.95) or 0.0, 2),
    }


def flatten_status(payload: dict) -> dict:
    timings = payload.get("timings_ms", {}) or {}
    return {
        "ts": payload.get("ts"),
        "camera_status": payload.get("camera_status"),
        "mmwave_status": payload.get("mmwave_status"),
        "system_state": payload.get("system_state"),
        "count_confidence": payload.get("count_confidence"),
        "delivered_fps": payload.get("delivered_fps"),
        "detector_fps": payload.get("detector_fps"),
        "target_capture_fps": payload.get("target_capture_fps"),
        "target_detector_fps": payload.get("target_detector_fps"),
        "drop_ratio_30s": payload.get("drop_ratio_30s"),
        "publish_backlog_ms": payload.get("publish_backlog_ms"),
        "cpu_percent": payload.get("cpu_percent"),
        "ram_mb": payload.get("ram_mb"),
        "temperature_c": payload.get("temperature_c"),
        "camera_read_ms": timings.get("camera_read_ms"),
        "capture_to_service_ms": timings.get("capture_to_service_ms"),
        "detector_preprocess_ms": timings.get("detector_preprocess_ms"),
        "detector_inference_ms": timings.get("detector_inference_ms"),
        "detector_postprocess_ms": timings.get("detector_postprocess_ms"),
        "detector_total_ms": timings.get("detector_total_ms"),
        "filter_ms": timings.get("filter_ms"),
        "tracking_ms": timings.get("tracking_ms"),
        "crossing_ms": timings.get("crossing_ms"),
        "event_enqueue_ms": timings.get("event_enqueue_ms"),
        "process_camera_total_ms": timings.get("process_camera_total_ms"),
        "sse_publish_ms": timings.get("sse_publish_ms"),
    }


def write_summary_md(output_path: Path, summary: dict) -> None:
    lines = [
        "# PASO Benchmark Summary",
        f"Generated: {summary['generated_at']}",
        f"Samples: {summary['sample_count']}",
        f"Duration seconds: {summary['duration_seconds']}",
        "",
        "## Scheduler",
        f"- Target capture FPS: `{summary['targets'].get('target_capture_fps')}`",
        f"- Target detector FPS: `{summary['targets'].get('target_detector_fps')}`",
        f"- Dominant camera status: `{summary['dominant_status'].get('camera_status')}`",
        f"- Dominant system state: `{summary['dominant_status'].get('system_state')}`",
        "",
        "## Throughput",
        f"- Delivered FPS avg/min/max: `{summary['metrics']['delivered_fps']}`",
        f"- Detector FPS avg/min/max: `{summary['metrics']['detector_fps']}`",
        f"- Drop ratio avg/max: `{summary['metrics']['drop_ratio_30s']}`",
        f"- Publish backlog avg/max: `{summary['metrics']['publish_backlog_ms']}`",
        "",
        "## Resources",
        f"- CPU avg/max: `{summary['metrics']['cpu_percent']}`",
        f"- RAM avg/max: `{summary['metrics']['ram_mb']}`",
        f"- Temperature avg/max: `{summary['metrics']['temperature_c']}`",
        "",
        "## Timings",
    ]
    for key in (
        "camera_read_ms",
        "capture_to_service_ms",
        "detector_preprocess_ms",
        "detector_inference_ms",
        "detector_postprocess_ms",
        "detector_total_ms",
        "filter_ms",
        "tracking_ms",
        "crossing_ms",
        "event_enqueue_ms",
        "process_camera_total_ms",
        "sse_publish_ms",
    ):
        lines.append(f"- {key}: `{summary['metrics'][key]}`")
    output_path.write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description="Sample PASO runtime metrics from a live entrance-monitor instance.")
    parser.add_argument("--host", default="localhost")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--duration", type=int, default=30, help="Sampling duration in seconds.")
    parser.add_argument("--interval", type=float, default=1.0, help="Seconds between samples.")
    parser.add_argument("--output-dir", default="docs/evidence", help="Directory for benchmark artifacts.")
    args = parser.parse_args()

    base_url = f"http://{args.host}:{args.port}"
    output_root = Path(args.output_dir)
    run_dir = output_root / f"benchmark_{utc_stamp()}"
    run_dir.mkdir(parents=True, exist_ok=True)

    deadline = time.time() + max(1, args.duration)
    samples: list[dict] = []
    while time.time() < deadline:
        status = api_get_json(f"{base_url}/api/v1/status")
        sample = flatten_status(status)
        samples.append(sample)
        time.sleep(max(0.1, args.interval))

    jsonl_path = run_dir / "samples.jsonl"
    csv_path = run_dir / "samples.csv"
    summary_json_path = run_dir / "summary.json"
    summary_md_path = run_dir / "summary.md"

    jsonl_path.write_text("\n".join(json.dumps(item) for item in samples), encoding="utf-8")

    fieldnames = list(samples[0].keys()) if samples else []
    with csv_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(samples)

    summary = {
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "sample_count": len(samples),
        "duration_seconds": args.duration,
        "targets": {
            "target_capture_fps": samples[-1].get("target_capture_fps") if samples else None,
            "target_detector_fps": samples[-1].get("target_detector_fps") if samples else None,
        },
        "dominant_status": {
            "camera_status": statistics.mode([item["camera_status"] for item in samples]) if samples else None,
            "system_state": statistics.mode([item["system_state"] for item in samples]) if samples else None,
        },
        "metrics": {},
        "artifacts": {
            "samples_jsonl": str(jsonl_path.resolve()),
            "samples_csv": str(csv_path.resolve()),
            "summary_md": str(summary_md_path.resolve()),
        },
    }

    numeric_fields = [
        "delivered_fps",
        "detector_fps",
        "drop_ratio_30s",
        "publish_backlog_ms",
        "cpu_percent",
        "ram_mb",
        "temperature_c",
        "camera_read_ms",
        "capture_to_service_ms",
        "detector_preprocess_ms",
        "detector_inference_ms",
        "detector_postprocess_ms",
        "detector_total_ms",
        "filter_ms",
        "tracking_ms",
        "crossing_ms",
        "event_enqueue_ms",
        "process_camera_total_ms",
        "sse_publish_ms",
    ]
    for field in numeric_fields:
        summary["metrics"][field] = summarize_numeric(samples, field)

    summary_json_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    write_summary_md(summary_md_path, summary)

    print(str(summary_md_path.resolve()))


if __name__ == "__main__":
    main()
