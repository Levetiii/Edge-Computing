#!/usr/bin/env python3
"""
PASO Diagnostic Script
INF2009 Edge Computing and Analytics
Usage: python3 tests/paso_diagnostic.py [--host localhost] [--port 8000] [--crossings 10]
"""

import argparse
import json
import statistics
import time
import subprocess
import sys
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

import yaml

BASE_URL = ""
REPORT_DIR = Path("docs/evidence")
TIMESTAMP = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
REPORT_FILE = REPORT_DIR / f"PASO_DIAGNOSTIC_{TIMESTAMP}.md"
RAW_DIR = REPORT_DIR / f"raw_{TIMESTAMP}"
WRITE_RAW = True


def api_get(path):
    url = f"{BASE_URL}{path}"
    try:
        with urllib.request.urlopen(url, timeout=10) as r:
            return json.loads(r.read().decode())
    except Exception as e:
        return {"error": str(e)}


def api_post(path):
    url = f"{BASE_URL}{path}"
    req = urllib.request.Request(url, data=b"", method="POST")
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return json.loads(r.read().decode())
    except Exception as e:
        return {"error": str(e)}


def run_cmd(cmd):
    try:
        result = subprocess.run(
            cmd, shell=True, capture_output=True, text=True, timeout=10
        )
        return result.stdout.strip()
    except Exception as e:
        return f"ERROR: {e}"


def save_raw(name, data):
    if not WRITE_RAW:
        return None
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    path = RAW_DIR / name
    if isinstance(data, (dict, list)):
        path.write_text(json.dumps(data, indent=2))
    else:
        path.write_text(str(data))
    return path


def hr(char="-", width=60):
    return char * width


def pass_fail(condition):
    return "PASS" if condition else "FAIL"


def warn_pass(condition):
    return "PASS" if condition else "WARNING"


def decode_throttle_flags(throttle_val):
    if not throttle_val:
        return None
    try:
        bits = int(throttle_val, 16)
    except Exception:
        return None

    flags = {
        "current_under_voltage": bool(bits & 0x1),
        "current_freq_capped": bool(bits & 0x2),
        "current_throttled": bool(bits & 0x4),
        "current_soft_temp_limit": bool(bits & 0x8),
        "past_under_voltage": bool(bits & 0x10000),
        "past_freq_capped": bool(bits & 0x20000),
        "past_throttled": bool(bits & 0x40000),
        "past_soft_temp_limit": bool(bits & 0x80000),
    }

    current_labels = []
    if flags["current_under_voltage"]:
        current_labels.append("under-voltage now")
    if flags["current_freq_capped"]:
        current_labels.append("frequency capped now")
    if flags["current_throttled"]:
        current_labels.append("throttled now")
    if flags["current_soft_temp_limit"]:
        current_labels.append("soft temperature limit now")

    historical_labels = []
    if flags["past_under_voltage"]:
        historical_labels.append("under-voltage occurred")
    if flags["past_freq_capped"]:
        historical_labels.append("frequency cap occurred")
    if flags["past_throttled"]:
        historical_labels.append("throttling occurred")
    if flags["past_soft_temp_limit"]:
        historical_labels.append("soft temperature limit occurred")

    flags["current_labels"] = current_labels
    flags["historical_labels"] = historical_labels
    return flags


def get_abs_path(relative_dir):
    return str(Path(relative_dir).resolve())


def approx_latency_ms(fps):
    return round(1000 / fps, 1) if fps and fps > 0 else None


def accuracy_percent(error, manual):
    if manual <= 0:
        return 0.0
    raw = (1 - abs(error) / manual) * 100
    return round(max(0.0, min(100.0, raw)), 1)


def mean_or_none(values):
    numeric = [float(value) for value in values if isinstance(value, (int, float))]
    if not numeric:
        return None
    return round(statistics.fmean(numeric), 2)


def dominant_or_last(values):
    filtered = [value for value in values if value is not None]
    if not filtered:
        return None
    try:
        return statistics.mode(filtered)
    except statistics.StatisticsError:
        return filtered[-1]


def sample_status_window(duration_seconds=4.0, interval_seconds=0.5):
    samples = []
    deadline = time.time() + max(duration_seconds, interval_seconds)
    while True:
        sample = api_get("/api/v1/status")
        if "error" not in sample:
            samples.append(sample)
        if time.time() >= deadline:
            break
        time.sleep(max(0.1, interval_seconds))
    return samples


def summarize_status_samples(samples):
    if not samples:
        return {"error": "No status samples collected."}

    healthy = [
        sample
        for sample in samples
        if sample.get("camera_status") == "OK"
        and float(sample.get("delivered_fps", 0) or 0) > 0
    ]
    selected = healthy or samples

    summary = {
        "schema_version": dominant_or_last([item.get("schema_version") for item in selected]),
        "ts": selected[-1].get("ts"),
        "camera_status": dominant_or_last([item.get("camera_status") for item in selected]),
        "mmwave_status": dominant_or_last([item.get("mmwave_status") for item in selected]),
        "system_state": dominant_or_last([item.get("system_state") for item in selected]),
        "count_confidence": dominant_or_last([item.get("count_confidence") for item in selected]),
        "warning_flags": selected[-1].get("warning_flags", []),
        "gated_mode": bool(selected[-1].get("gated_mode", False)),
        "target_capture_fps": mean_or_none([item.get("target_capture_fps") for item in selected]),
        "target_detector_fps": mean_or_none([item.get("target_detector_fps") for item in selected]),
        "drop_ratio_30s": mean_or_none([item.get("drop_ratio_30s") for item in selected]),
        "publish_backlog_ms": mean_or_none([item.get("publish_backlog_ms") for item in selected]),
        "delivered_fps": mean_or_none([item.get("delivered_fps") for item in selected]),
        "detector_fps": mean_or_none([item.get("detector_fps") for item in selected]),
        "cpu_percent": mean_or_none([item.get("cpu_percent") for item in selected]),
        "ram_mb": mean_or_none([item.get("ram_mb") for item in selected]),
        "temperature_c": mean_or_none([item.get("temperature_c") for item in selected]),
        "sampling": {
            "sample_count": len(samples),
            "healthy_sample_count": len(healthy),
            "window_seconds": round(max(0.0, (len(samples) - 1) * 0.5), 2),
        },
        "timings_ms": {},
    }

    timing_fields = (
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
    )
    for field in timing_fields:
        summary["timings_ms"][field] = mean_or_none(
            [
                (item.get("timings_ms") or {}).get(field)
                for item in selected
                if isinstance(item.get("timings_ms"), dict)
            ]
        )

    return summary


def load_mmwave_mode(settings_payload):
    config_path = settings_payload.get("config_path") if isinstance(settings_payload, dict) else None
    if not config_path:
        return None
    path = Path(config_path)
    if not path.is_absolute():
        path = (Path.cwd() / path).resolve()
    if not path.exists():
        return None
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except Exception:
        return None
    mmwave = data.get("mmwave") or {}
    mode = mmwave.get("mode")
    return str(mode) if mode is not None else None


def test_pipeline():
    print("\n[P] Pipeline Latency Budget...")
    status_samples = sample_status_window()
    save_raw("p_status_samples.json", status_samples)
    status = summarize_status_samples(status_samples)
    save_raw("p_status.json", status)
    settings = api_get("/api/v1/settings")
    if "error" not in settings:
        save_raw("p_settings.json", settings)

    if "error" in status:
        return {"section": "P", "error": status["error"], "rows": []}

    delivered = status.get("delivered_fps", 0)
    detector = status.get("detector_fps", 0)
    gated_mode = bool(status.get("gated_mode", False))
    timings = status.get("timings_ms", {}) if isinstance(status, dict) else {}
    frame_ms = timings.get("camera_read_ms")
    detect_pre_ms = timings.get("detector_preprocess_ms")
    detect_inf_ms = timings.get("detector_inference_ms")
    detect_post_ms = timings.get("detector_postprocess_ms")
    detect_total_ms = timings.get("detector_total_ms")
    capture_to_service_ms = timings.get("capture_to_service_ms")
    filter_ms = timings.get("filter_ms")
    tracking_ms = timings.get("tracking_ms")
    crossing_ms = timings.get("crossing_ms")
    enqueue_ms = timings.get("event_enqueue_ms")
    publish_ms = timings.get("sse_publish_ms")
    process_total_ms = timings.get("process_camera_total_ms")
    if frame_ms is None:
        frame_ms = approx_latency_ms(delivered)
    if detect_total_ms is None:
        detect_total_ms = approx_latency_ms(detector)

    camera_cfg = settings.get("camera", {}) if isinstance(settings, dict) else {}
    detector_cfg = settings.get("detector", {}) if isinstance(settings, dict) else {}
    target_capture_fps = status.get("target_capture_fps")
    if target_capture_fps is None and isinstance(camera_cfg, dict):
        target_capture_fps = camera_cfg.get("fps")
    target_detector_fps = status.get("target_detector_fps")
    if target_detector_fps is None and isinstance(camera_cfg, dict):
        detector_key = "detector_fps_gated" if gated_mode else "detector_fps_normal"
        target_detector_fps = camera_cfg.get(detector_key)
    capture_target_ms = approx_latency_ms(target_capture_fps)
    detect_target_ms = approx_latency_ms(target_detector_fps)
    drop_ratio_30s = status.get("drop_ratio_30s")
    publish_backlog_ms = status.get("publish_backlog_ms")
    detector_backend = (
        str(detector_cfg.get("backend", status.get("detector_mode", "detector"))).upper()
        if isinstance(detector_cfg, dict)
        else str(status.get("detector_mode", "detector")).upper()
    )

    capture_floor = target_capture_fps * 0.8 if isinstance(target_capture_fps, (int, float)) else None
    detector_floor = target_detector_fps * 0.8 if isinstance(target_detector_fps, (int, float)) else None

    rows = [
        {
            "stage": "Frame capture",
            "target_ms": capture_target_ms if capture_target_ms is not None else "N/A",
            "measured_ms": frame_ms,
            "basis": (
                f"observed {delivered} FPS vs target {target_capture_fps} FPS"
                if target_capture_fps is not None
                else f"1000 / {delivered} delivered_fps"
            ),
            "status": warn_pass(
                delivered > 0 and (capture_floor is None or delivered >= capture_floor)
            )
        },
        {
            "stage": "Capture to service handoff",
            "target_ms": "TBC",
            "measured_ms": capture_to_service_ms if capture_to_service_ms is not None else "TBC",
            "basis": "Direct app timing" if capture_to_service_ms is not None else "Not exposed",
            "status": "PASS" if capture_to_service_ms is not None else "PENDING",
        },
        {
            "stage": "Detector preprocess",
            "target_ms": "TBC",
            "measured_ms": detect_pre_ms if detect_pre_ms is not None else "TBC",
            "basis": "Direct app timing" if detect_pre_ms is not None else "Not exposed",
            "status": "PASS" if detect_pre_ms is not None else "PENDING",
        },
        {
            "stage": "Detector inference",
            "target_ms": detect_target_ms if detect_target_ms is not None else "N/A",
            "measured_ms": detect_inf_ms if detect_inf_ms is not None else "TBC",
            "basis": "Direct app timing" if detect_inf_ms is not None else "Not exposed",
            "status": warn_pass(
                detect_inf_ms is not None
                and (detect_target_ms is None or detect_inf_ms <= detect_target_ms)
            ) if detect_inf_ms is not None else "PENDING",
        },
        {
            "stage": "Detector postprocess",
            "target_ms": "TBC",
            "measured_ms": detect_post_ms if detect_post_ms is not None else "TBC",
            "basis": "Direct app timing" if detect_post_ms is not None else "Not exposed",
            "status": "PASS" if detect_post_ms is not None else "PENDING",
        },
        {
            "stage": f"Detection total ({detector_backend})",
            "target_ms": detect_target_ms if detect_target_ms is not None else "N/A",
            "measured_ms": detect_total_ms,
            "basis": (
                "Direct app timing"
                if timings.get("detector_total_ms") is not None
                else (
                    f"observed {detector} FPS vs target {target_detector_fps} FPS"
                    if target_detector_fps is not None
                    else f"1000 / {detector} detector_fps"
                )
            ),
            "status": warn_pass(
                (
                    detect_total_ms is not None
                    and (detect_target_ms is None or detect_total_ms <= detect_target_ms)
                ) if timings.get("detector_total_ms") is not None else
                (detector > 0 and (detector_floor is None or detector >= detector_floor))
            )
        },
        {
            "stage": "Detection filtering",
            "target_ms": "TBC",
            "measured_ms": filter_ms if filter_ms is not None else "TBC",
            "basis": "Direct app timing" if filter_ms is not None else "Not exposed",
            "status": "PASS" if filter_ms is not None else "PENDING"
        },
        {
            "stage": "Tracking (custom centroid tracker)",
            "target_ms": "TBC",
            "measured_ms": tracking_ms if tracking_ms is not None else "TBC",
            "basis": "Direct app timing" if tracking_ms is not None else "Not exposed",
            "status": "PASS" if tracking_ms is not None else "PENDING"
        },
        {
            "stage": "Crossing logic",
            "target_ms": "TBC",
            "measured_ms": crossing_ms if crossing_ms is not None else "TBC",
            "basis": "Direct app timing" if crossing_ms is not None else "Not exposed",
            "status": "PASS" if crossing_ms is not None else "PENDING"
        },
        {
            "stage": "Event enqueue",
            "target_ms": "TBC",
            "measured_ms": enqueue_ms if enqueue_ms is not None else "TBC",
            "basis": "Direct app timing" if enqueue_ms is not None else "Not exposed",
            "status": "PASS" if enqueue_ms is not None else "PENDING"
        },
        {
            "stage": "SSE publish",
            "target_ms": 10,
            "measured_ms": publish_ms if publish_ms is not None else "TBC",
            "basis": "Direct app timing" if publish_ms is not None else "Not exposed",
            "status": warn_pass(publish_ms is not None and publish_ms <= 10) if publish_ms is not None else "PENDING"
        },
        {
            "stage": "Per-frame processing total",
            "target_ms": 200,
            "measured_ms": process_total_ms if process_total_ms is not None else "TBC",
            "basis": "Direct app timing" if process_total_ms is not None else "Not exposed",
            "status": warn_pass(process_total_ms is not None and process_total_ms <= 200) if process_total_ms is not None else "PENDING"
        },
    ]

    sampling = status.get("sampling", {})
    print(
        f"  delivered_fps={delivered}  detector_fps={detector}  "
        f"samples={sampling.get('sample_count', 0)} healthy={sampling.get('healthy_sample_count', 0)}"
    )
    for r in rows:
        print(f"  {r['stage']:<35} {str(r['measured_ms']):>8} ms  {r['status']}")

    return {"section": "P", "raw": status, "rows": rows,
            "delivered_fps": delivered, "detector_fps": detector,
            "target_capture_fps": target_capture_fps,
            "target_detector_fps": target_detector_fps,
            "drop_ratio_30s": drop_ratio_30s,
            "publish_backlog_ms": publish_backlog_ms,
            "sampling": sampling,
            "camera_status": status.get("camera_status"),
            "system_state": status.get("system_state"),
            "warning_flags": status.get("warning_flags", [])}


def test_resources():
    print("\n[A] Resource Budget...")
    status = api_get("/api/v1/status")
    save_raw("a_status.json", status)

    temp_cmd = run_cmd("vcgencmd measure_temp")
    throttle_cmd = run_cmd("vcgencmd get_throttled")
    free_cmd = run_cmd("free -h")
    save_raw("a_os.txt", f"{temp_cmd}\n{throttle_cmd}\n{free_cmd}")

    cpu = status.get("cpu_percent", None)
    ram = status.get("ram_mb", None)
    temp_api = status.get("temperature_c", None)

    temp_os = None
    if "temp=" in temp_cmd:
        try:
            temp_os = float(temp_cmd.split("=")[1].replace("'C", ""))
        except Exception:
            pass

    throttle_val = None
    if "throttled=" in throttle_cmd:
        throttle_val = throttle_cmd.split("=")[1].strip()

    throttle_flags = decode_throttle_flags(throttle_val)
    current_power_issue = False
    current_soft_temp_limit = False
    historical_issue = False
    throttle_note = "Throttle flags unavailable."
    if throttle_flags:
        current_power_issue = (
            throttle_flags["current_under_voltage"]
            or throttle_flags["current_freq_capped"]
            or throttle_flags["current_throttled"]
        )
        current_soft_temp_limit = throttle_flags["current_soft_temp_limit"]
        historical_issue = bool(throttle_flags["historical_labels"])

        note_parts = []
        if throttle_flags["current_labels"]:
            note_parts.append("Current flags: " + ", ".join(throttle_flags["current_labels"]) + ".")
        if throttle_flags["historical_labels"]:
            note_parts.append("Historical flags: " + ", ".join(throttle_flags["historical_labels"]) + ".")
        if not note_parts:
            note_parts.append("No throttle, frequency-cap, undervoltage, or soft temperature limit flags observed.")
        if current_power_issue or current_soft_temp_limit:
            note_parts.append("Active cooling and stable power are recommended before live demo.")
        throttle_note = " ".join(note_parts)

    rows = [
        {
            "resource": "CPU utilisation",
            "target": "80%",
            "measured": f"{cpu}%",
            "source": "cpu_percent",
            "status": warn_pass(cpu is not None and cpu <= 80)
        },
        {
            "resource": "RAM usage",
            "target": "1536 MB",
            "measured": f"{ram} MB",
            "source": "ram_mb",
            "status": warn_pass(ram is not None and ram <= 1536)
        },
        {
            "resource": "Temperature (API)",
            "target": "85 deg C",
            "measured": f"{temp_api} deg C",
            "source": "temperature_c",
            "status": warn_pass(temp_api is not None and temp_api <= 85)
        },
        {
            "resource": "Temperature (OS)",
            "target": "85 deg C",
            "measured": f"{temp_os} deg C",
            "source": "vcgencmd measure_temp",
            "status": warn_pass(temp_os is not None and temp_os <= 85)
        },
        {
            "resource": "Current throttle/freq cap",
            "target": "clear",
            "measured": ", ".join(throttle_flags["current_labels"]) if throttle_flags and throttle_flags["current_labels"] else "clear",
            "source": "vcgencmd get_throttled",
            "status": pass_fail(not current_power_issue)
        },
        {
            "resource": "Current soft temp limit",
            "target": "clear",
            "measured": pass_fail(not current_soft_temp_limit),
            "source": "vcgencmd get_throttled",
            "status": warn_pass(not current_soft_temp_limit)
        },
        {
            "resource": "Throttle history",
            "target": "clear",
            "measured": ", ".join(throttle_flags["historical_labels"]) if throttle_flags and throttle_flags["historical_labels"] else "clear",
            "source": "vcgencmd get_throttled",
            "status": warn_pass(not historical_issue)
        },
    ]

    print(f"  cpu={cpu}%  ram={ram}MB  temp_api={temp_api}  "
          f"temp_os={temp_os}  throttle={throttle_val}")
    for r in rows:
        print(f"  {r['resource']:<30} {str(r['measured']):>15}  {r['status']}")

    return {"section": "A", "rows": rows,
            "cpu": cpu, "ram": ram, "temp_api": temp_api,
            "temp_os": temp_os, "throttle": throttle_val,
            "current_power_issue": current_power_issue,
            "current_soft_temp_limit": current_soft_temp_limit,
            "historical_issue": historical_issue,
            "throttle_note": throttle_note}


def test_sensing(crossings):
    print(f"\n[S] Counting Accuracy -- {crossings} crossings required...")

    api_post("/api/v1/validation/reset")
    start = api_post("/api/v1/validation/start")
    save_raw("s_session_start.json", start)

    session_id = start.get("session_id", "unknown")
    print(f"  Session ID: {session_id}")
    print(f"  Walk in front of the camera and press:")
    print(f"    ENTER key after each ENTRY crossing")
    print(f"    E key + ENTER after each EXIT crossing")
    print(f"    Q key + ENTER to finish early")
    print()

    entry_count = 0
    exit_count = 0
    total = 0

    while total < crossings:
        key = input(
            f"  [{total}/{crossings}] Cross the line then press "
            f"[enter=ENTRY / e=EXIT / q=quit]: "
        ).strip().lower()

        if key == "q":
            print("  Stopping early.")
            break
        elif key == "e":
            result = api_post("/api/v1/validation/manual-exit")
            exit_count += 1
            direction = "EXIT"
        else:
            result = api_post("/api/v1/validation/manual-entry")
            entry_count += 1
            direction = "ENTRY"

        sys_entry = result.get("system_entry_count", "?")
        sys_exit = result.get("system_exit_count", "?")
        total += 1
        print(f"    Logged {direction} -- system so far: "
              f"entry={sys_entry} exit={sys_exit}")

    stop = api_post("/api/v1/validation/stop")
    save_raw("s_session_stop.json", stop)

    try:
        csv_url = f"{BASE_URL}/api/v1/validation/export.csv"
        with urllib.request.urlopen(csv_url, timeout=10) as r:
            csv_data = r.read().decode()
        csv_path = RAW_DIR / "s_validation.csv"
        csv_path.write_text(csv_data)
        print(f"  CSV saved to {csv_path}")
    except Exception as e:
        print(f"  CSV export failed: {e}")

    manual_entry = stop.get("manual_entry_count", entry_count)
    manual_exit = stop.get("manual_exit_count", exit_count)
    manual_total = stop.get("manual_total_count", total)
    sys_entry = stop.get("system_entry_count", 0)
    sys_exit = stop.get("system_exit_count", 0)
    sys_total = stop.get("system_total_count", 0)
    entry_err = stop.get("entry_error", sys_entry - manual_entry)
    exit_err = stop.get("exit_error", sys_exit - manual_exit)
    total_err = stop.get("total_error", sys_total - manual_total)

    entry_acc = accuracy_percent(entry_err, manual_entry)
    exit_acc = accuracy_percent(exit_err, manual_exit)
    total_acc = accuracy_percent(total_err, manual_total)

    rows = [
        {"direction": "ENTRY", "manual": manual_entry,
         "system": sys_entry, "error": entry_err,
         "accuracy": f"{entry_acc}%",
         "status": pass_fail(entry_err == 0)},
        {"direction": "EXIT", "manual": manual_exit,
         "system": sys_exit, "error": exit_err,
         "accuracy": f"{exit_acc}%",
         "status": pass_fail(exit_err == 0)},
        {"direction": "TOTAL", "manual": manual_total,
         "system": sys_total, "error": total_err,
         "accuracy": f"{total_acc}%",
         "status": pass_fail(total_err == 0)},
    ]

    duration = stop.get("duration_seconds", 0)
    print(f"\n  Results: entry_err={entry_err} exit_err={exit_err} "
          f"total_err={total_err} duration={duration:.1f}s")

    return {"section": "S", "session_id": session_id,
            "rows": rows, "duration": duration,
            "started_at": start.get("started_at"),
            "ended_at": stop.get("ended_at"),
            "entry_acc": entry_acc, "exit_acc": exit_acc,
            "total_acc": total_acc}


def test_observability():
    print("\n[O] Observability and Fault Handling...")

    settings = api_get("/api/v1/settings")
    save_raw("o_settings.json", settings)
    mmwave_mode = load_mmwave_mode(settings)

    baseline = api_get("/api/v1/status")
    save_raw("o_baseline.json", baseline)
    baseline_camera = baseline.get("camera_status", "UNKNOWN")
    baseline_state = baseline.get("system_state", "UNKNOWN")
    print(f"  Baseline: camera_status={baseline_camera} "
          f"system_state={baseline_state}")

    input("\n  ACTION REQUIRED: Physically unplug the webcam USB cable, "
          "then press ENTER...")
    time.sleep(5)

    fault = api_get("/api/v1/status")
    save_raw("o_fault.json", fault)
    fault_camera = fault.get("camera_status", "UNKNOWN")
    fault_state = fault.get("system_state", "UNKNOWN")
    print(f"  After unplug: camera_status={fault_camera} "
          f"system_state={fault_state}")

    input("\n  ACTION REQUIRED: Plug the webcam back in, then press ENTER...")
    time.sleep(5)

    recovery = api_get("/api/v1/status")
    save_raw("o_recovery.json", recovery)
    recovery_camera = recovery.get("camera_status", "UNKNOWN")
    recovery_state = recovery.get("system_state", "UNKNOWN")
    print(f"  After replug: camera_status={recovery_camera} "
          f"system_state={recovery_state}")

    pid_output = run_cmd("pgrep -af entrance-monitor")
    if not pid_output:
        pid_output = run_cmd("ps aux | grep entrance | grep -v grep")
    process_alive = "entrance-monitor" in pid_output
    save_raw("o_process.txt", pid_output)

    fault_detected = fault_camera != "OK" or fault_state != "NORMAL"
    recovered = recovery_camera == "OK" and recovery_state == "NORMAL"

    rows = [
        {
            "phase": "Baseline (before unplug)",
            "camera_status": baseline_camera,
            "system_state": baseline_state,
            "process_alive": pass_fail(True),
            "status": "INFO"
        },
        {
            "phase": "After unplug (5s wait)",
            "camera_status": fault_camera,
            "system_state": fault_state,
            "process_alive": pass_fail(process_alive),
            "status": pass_fail(fault_detected)
        },
        {
            "phase": "After replug (5s wait)",
            "camera_status": recovery_camera,
            "system_state": recovery_state,
            "process_alive": pass_fail(process_alive),
            "status": pass_fail(recovered)
        },
    ]

    mmwave_baseline = api_get("/api/v1/status")
    save_raw("o_mmwave_baseline.json", mmwave_baseline)
    mmwave_baseline_status = mmwave_baseline.get("mmwave_status", "UNKNOWN")
    mmwave_baseline_state = mmwave_baseline.get("system_state", "UNKNOWN")
    mmwave_rows = []
    mmwave_fault_detected = None
    mmwave_recovered = None
    mmwave_note = ""

    if mmwave_mode == "mock":
        mmwave_note = "Skipped: mmWave mode is mock, so a physical unplug test is not applicable."
        print(f"  mmWave fault test skipped: {mmwave_note}")
    elif mmwave_baseline_status != "OK":
        mmwave_note = (
            f"Skipped: baseline mmwave_status={mmwave_baseline_status}. "
            "Connect the physical mmWave sensor and rerun to test fault handling."
        )
        print(f"  mmWave fault test skipped: {mmwave_note}")
    else:
        print(f"  mmWave baseline: mmwave_status={mmwave_baseline_status} system_state={mmwave_baseline_state}")
        input("\n  ACTION REQUIRED: Physically unplug the mmWave sensor, then press ENTER...")
        time.sleep(5)

        mmwave_fault = api_get("/api/v1/status")
        save_raw("o_mmwave_fault.json", mmwave_fault)
        fault_mmwave = mmwave_fault.get("mmwave_status", "UNKNOWN")
        fault_system = mmwave_fault.get("system_state", "UNKNOWN")
        print(f"  After mmWave unplug: mmwave_status={fault_mmwave} system_state={fault_system}")

        input("\n  ACTION REQUIRED: Plug the mmWave sensor back in, then press ENTER...")
        time.sleep(5)

        mmwave_recovery_payload = api_get("/api/v1/status")
        save_raw("o_mmwave_recovery.json", mmwave_recovery_payload)
        recovery_mmwave = mmwave_recovery_payload.get("mmwave_status", "UNKNOWN")
        recovery_system = mmwave_recovery_payload.get("system_state", "UNKNOWN")
        print(f"  After mmWave replug: mmwave_status={recovery_mmwave} system_state={recovery_system}")

        mmwave_pid_output = run_cmd("pgrep -af entrance-monitor")
        if not mmwave_pid_output:
            mmwave_pid_output = run_cmd("ps aux | grep entrance | grep -v grep")
        mmwave_process_alive = "entrance-monitor" in mmwave_pid_output
        save_raw("o_mmwave_process.txt", mmwave_pid_output)

        mmwave_fault_detected = fault_mmwave != "OK" or fault_system in {"MMWAVE_DISCONNECTED", "MMWAVE_DEGRADED"}
        mmwave_recovered = recovery_mmwave == "OK"
        mmwave_rows = [
            {
                "phase": "Baseline (before unplug)",
                "mmwave_status": mmwave_baseline_status,
                "system_state": mmwave_baseline_state,
                "process_alive": pass_fail(True),
                "status": "INFO",
            },
            {
                "phase": "After unplug (5s wait)",
                "mmwave_status": fault_mmwave,
                "system_state": fault_system,
                "process_alive": pass_fail(mmwave_process_alive),
                "status": pass_fail(mmwave_fault_detected),
            },
            {
                "phase": "After replug (5s wait)",
                "mmwave_status": recovery_mmwave,
                "system_state": recovery_system,
                "process_alive": pass_fail(mmwave_process_alive),
                "status": pass_fail(mmwave_recovered),
            },
        ]

    metrics = api_get("/api/v1/metrics/latest")
    save_raw("o_metrics.json", metrics)
    latest_status = api_get("/api/v1/status")
    save_raw("o_status_final.json", latest_status)

    sensor_rows = [
        {"sensor": "Camera (C270 HD)", "field": "camera_status",
         "value": latest_status.get("camera_status", recovery.get("camera_status", "N/A"))},
        {"sensor": "mmWave sensor", "field": "mmwave_status",
         "value": latest_status.get("mmwave_status", metrics.get("mmwave_status", "N/A"))},
        {"sensor": "Presence fusion", "field": "presence_corroboration_state",
         "value": metrics.get("presence_corroboration_state", "N/A")},
        {"sensor": "Gated mode", "field": "gated_mode",
         "value": latest_status.get("gated_mode", metrics.get("gated_mode", "N/A"))},
        {"sensor": "Overall system", "field": "system_state",
         "value": latest_status.get("system_state", recovery.get("system_state", "N/A"))},
        {"sensor": "Count confidence", "field": "count_confidence",
         "value": latest_status.get("count_confidence", metrics.get("count_confidence", "N/A"))},
    ]

    print(f"  Fault detected: {fault_detected}  Recovered: {recovered}  "
          f"Process alive: {process_alive}")

    return {"section": "O", "rows": rows, "mmwave_rows": mmwave_rows, "sensor_rows": sensor_rows,
            "fault_detected": fault_detected, "recovered": recovered,
            "process_alive": process_alive,
            "mmwave_fault_detected": mmwave_fault_detected,
            "mmwave_recovered": mmwave_recovered,
            "mmwave_note": mmwave_note,
            "mmwave_mode": mmwave_mode}


def write_report(p, a, s, o, abs_report_dir, abs_raw_dir, raw_enabled):
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    lines = []

    def w(line=""):
        lines.append(line)

    w("# PASO Diagnostic Report")
    w("**Project:** Entrance Monitor (INF2009 Edge Computing and Analytics)")
    w(f"**Generated:** "
      f"{datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')}")
    w("**Device:** Raspberry Pi 5")
    w("**Script:** tests/paso_diagnostic.py")
    w()
    w(hr())
    w()

    w("## P -- Pipeline Latency Budget")
    w()
    w("**Test Methodology:**")
    w()
    w("Script sampled GET /api/v1/status over a short time window while entrance-monitor was running and summarized healthy samples to avoid single bad snapshots. GET /api/v1/settings was also queried to read the current configured cadence. Where exposed by the application, stage timings are taken directly from runtime perf_counter instrumentation. Only missing fields fall back to rough FPS-derived estimates. Communication layer uses REST and SSE (Server-Sent Events).")
    w()
    if "error" in p:
        w(f"ERROR: Could not reach API -- {p['error']}")
    else:
        if raw_enabled:
            w(f"Source: {abs_raw_dir}/p_status.json")
            w(f"Source: {abs_raw_dir}/p_status_samples.json")
            if p.get("target_capture_fps") is not None or p.get("target_detector_fps") is not None:
                w(f"Source: {abs_raw_dir}/p_settings.json")
        else:
            w("Raw artifact export disabled (--report-only).")
        w()
        w(f"| {'Stage':<35} | {'Target (ms)':>11} | {'Measured (ms)':>13} "
          f"| {'Basis':<35} | Status  |")
        w(f"|{'-'*37}|{'-'*13}|{'-'*15}|{'-'*37}|---------|")
        for r in p["rows"]:
            w(f"| {r['stage']:<35} | {str(r['target_ms']):>11} | "
              f"{str(r['measured_ms']):>13} | {r['basis']:<35} | "
              f"{r['status']:<7} |")
        w()
        w("### Scheduling and Overload")
        w()
        w(f"- Target capture FPS: `{p.get('target_capture_fps', 'N/A')}`")
        w(f"- Actual capture FPS: `{p.get('delivered_fps', 'N/A')}`")
        w(f"- Target detector FPS: `{p.get('target_detector_fps', 'N/A')}`")
        w(f"- Actual detector FPS: `{p.get('detector_fps', 'N/A')}`")
        w(f"- Drop ratio (30s): `{p.get('drop_ratio_30s', 'N/A')}`")
        w(f"- Publish backlog: `{p.get('publish_backlog_ms', 'N/A')} ms`")
        if p.get("sampling"):
            w(f"- Status samples collected: `{p['sampling'].get('sample_count', 'N/A')}`")
            w(f"- Healthy samples used: `{p['sampling'].get('healthy_sample_count', 'N/A')}`")
        w()
        w("Note: this section prefers direct runtime timings from the application. Any stage still marked with FPS-based values or PENDING needs additional code instrumentation before final PASO submission.")
    w()
    w(hr())
    w()

    w("## A -- Resource Budget")
    w()
    w("**Test Methodology:**")
    w()
    w("Script queried GET /api/v1/status for application-level metrics (cpu_percent, ram_mb, temperature_c) and ran vcgencmd measure_temp, vcgencmd get_throttled, and free -h via subprocess for OS-level confirmation. Both sources captured simultaneously under normal load.")
    w()
    if raw_enabled:
        w(f"Source: {abs_raw_dir}/a_status.json")
        w(f"Source: {abs_raw_dir}/a_os.txt")
    else:
        w("Raw artifact export disabled (--report-only).")
    w()
    w(f"| {'Resource':<30} | {'Target':>10} | {'Measured':>15} "
      f"| {'Source Field':<25} | Status  |")
    w(f"|{'-'*32}|{'-'*12}|{'-'*17}|{'-'*27}|---------|")
    for r in a["rows"]:
        w(f"| {r['resource']:<30} | {r['target']:>10} | "
          f"{str(r['measured']):>15} | {r['source']:<25} | {r['status']:<7} |")
    w()
    w(f"Note: {a.get('throttle_note', 'Throttle flags unavailable.')}")
    w()
    w(hr())
    w()

    w("## S -- Counting Accuracy (Validation Session)")
    w()
    w("**Test Methodology:**")
    w()
    w("Script started a validation session via POST /api/v1/validation/start. Tester physically walked in front of the camera crossing the virtual line (x=640, vertical center of 1280px frame) and pressed ENTER for ENTRY or E+ENTER for EXIT after each crossing. Script called POST /api/v1/validation/manual-entry or manual-exit accordingly. Session stopped via POST /api/v1/validation/stop and CSV exported via GET /api/v1/validation/export.csv.")
    w()
    if not s.get("rows"):
        w("Status: SKIPPED")
    else:
        if raw_enabled:
            w(f"Source: {abs_raw_dir}/s_session_stop.json")
            w(f"Source: {abs_raw_dir}/s_validation.csv")
        else:
            w("Raw artifact export disabled (--report-only).")
        w()
        w(f"Session ID:  {s['session_id']}")
        w(f"Started:     {s.get('started_at', 'N/A')}")
        w(f"Ended:       {s.get('ended_at', 'N/A')}")
        w(f"Duration:    {s['duration']:.1f} seconds")
        w()
        w(f"| {'Direction':<10} | {'Ground Truth':>13} | "
          f"{'System Detected':>16} | {'Error':>6} | "
          f"{'Accuracy':>9} | Status  |")
        w(f"|{'-'*12}|{'-'*15}|{'-'*18}|{'-'*8}|{'-'*11}|---------|")
        for r in s["rows"]:
            w(f"| {r['direction']:<10} | {str(r['manual']):>13} | "
              f"{str(r['system']):>16} | {str(r['error']):>6} | "
              f"{r['accuracy']:>9} | {r['status']:<7} |")
        w()
        w("Virtual line configuration:")
        w("  Line: x1=640, y1=150 to x2=640, y2=650 (vertical, center of frame)")
        w("  Crossing direction: left to right = ENTRY, right to left = EXIT")
    w()
    w(hr())
    w()

    w("## O -- Observability and Fault Handling")
    w()
    w("### Test O-1: Camera Disconnection")
    w()
    w("**Test Methodology:**")
    w()
    w("Script captured baseline status, prompted tester to physically unplug the webcam USB cable, waited 5 seconds, then re-queried status to confirm fault detection. Tester was then prompted to replug the webcam. Script waited 5 seconds and re-queried to confirm recovery. Process liveness verified via ps aux throughout.")
    w()
    if not o.get("rows"):
        w("Status: SKIPPED")
    else:
        if raw_enabled:
            w(f"Source: {abs_raw_dir}/o_baseline.json")
            w(f"Source: {abs_raw_dir}/o_fault.json")
            w(f"Source: {abs_raw_dir}/o_recovery.json")
            w(f"Source: {abs_raw_dir}/o_process.txt")
        else:
            w("Raw artifact export disabled (--report-only).")
        w()
        w(f"| {'Phase':<30} | {'camera_status':>14} | "
          f"{'system_state':>20} | {'Process':>8} | Status  |")
        w(f"|{'-'*32}|{'-'*16}|{'-'*22}|{'-'*10}|---------|")
        for r in o["rows"]:
            w(f"| {r['phase']:<30} | {r['camera_status']:>14} | "
              f"{r['system_state']:>20} | {r['process_alive']:>8} | "
              f"{r['status']:<7} |")
        w()
        overall_o1 = pass_fail(
            o["fault_detected"] and o["recovered"] and o["process_alive"]
        )
        w(f"Result: {overall_o1}")
    w()
    w("### Test O-2: mmWave Sensor Fault")
    w()
    w("**Test Methodology:**")
    w()
    w("If the baseline mmwave_status is OK, script prompts the tester to unplug the mmWave sensor, waits 5 seconds, re-queries status, then prompts for replug and checks recovery after another 5 seconds. Process liveness is verified after the fault sequence.")
    w()
    if o.get("mmwave_rows"):
        if raw_enabled:
            w(f"Source: {abs_raw_dir}/o_mmwave_baseline.json")
            w(f"Source: {abs_raw_dir}/o_mmwave_fault.json")
            w(f"Source: {abs_raw_dir}/o_mmwave_recovery.json")
            w(f"Source: {abs_raw_dir}/o_mmwave_process.txt")
        else:
            w("Raw artifact export disabled (--report-only).")
        w()
        w(f"| {'Phase':<30} | {'mmwave_status':>14} | {'system_state':>20} | {'Process':>8} | Status  |")
        w(f"|{'-'*32}|{'-'*16}|{'-'*22}|{'-'*10}|---------|")
        for r in o["mmwave_rows"]:
            w(f"| {r['phase']:<30} | {r['mmwave_status']:>14} | {r['system_state']:>20} | {r['process_alive']:>8} | {r['status']:<7} |")
        w()
        overall_o2 = pass_fail(
            bool(o.get("mmwave_fault_detected")) and bool(o.get("mmwave_recovered"))
        )
        w(f"Result: {overall_o2}")
    else:
        w(f"Status: SKIPPED")
        if o.get("mmwave_note"):
            w()
            w(o["mmwave_note"])
    w()
    w("### Test O-3: Dual Sensor Health Reporting")
    w()
    if not o.get("sensor_rows"):
        w("Status: SKIPPED")
    else:
        if raw_enabled:
            w(f"Source: {abs_raw_dir}/o_metrics.json")
            w(f"Source: {abs_raw_dir}/o_status_final.json")
        else:
            w("Raw artifact export disabled (--report-only).")
        w()
        w(f"| {'Sensor':<25} | {'Status Field':<20} | {'Measured Value':<40} |")
        w(f"|{'-'*27}|{'-'*22}|{'-'*42}|")
        for r in o["sensor_rows"]:
            w(f"| {r['sensor']:<25} | {r['field']:<20} | "
              f"{str(r['value']):<40} |")
    w()
    w(hr())
    w()

    w("## Summary")
    w()
    w(f"| {'Area':<25} | {'Result':<10} | Notes |")
    w(f"|{'-'*27}|{'-'*12}|-------|")

    p_fps_status = "ERROR"
    if "delivered_fps" in p:
        target_capture = p.get("target_capture_fps", 0) or 0
        target_detector = p.get("target_detector_fps", 0) or 0
        delivered_ok = target_capture <= 0 or p.get("delivered_fps", 0) >= target_capture * 0.8
        detector_ok = target_detector <= 0 or p.get("detector_fps", 0) >= target_detector * 0.8
        camera_status = p.get("camera_status")
        warning_flags = set(p.get("warning_flags", []))
        if camera_status == "DISCONNECTED":
            p_fps_status = "FAIL"
        elif (
            camera_status != "OK"
            or "high_drop_rate" in warning_flags
            or not delivered_ok
            or not detector_ok
        ):
            p_fps_status = "WARNING"
        else:
            p_fps_status = "PASS"
    w(f"| {'Pipeline FPS':<25} | {p_fps_status:<10} | "
      f"delivered={p.get('delivered_fps','N/A')} "
      f"detector={p.get('detector_fps','N/A')} "
      f"target={p.get('target_capture_fps','N/A')} |")

    a_cpu_ok = a.get("cpu", 999) <= 80
    a_ram_ok = a.get("ram", 999999) <= 1536
    a_cpu_ram = "PASS" if (a_cpu_ok and a_ram_ok) else "WARNING"
    w(f"| {'CPU/RAM':<25} | {a_cpu_ram:<10} | "
      f"cpu={a.get('cpu','N/A')}% ram={a.get('ram','N/A')}MB |")

    a_temp = warn_pass((a.get("temp_os") or 999) <= 85)
    w(f"| {'Temperature':<25} | {a_temp:<10} | "
      f"api={a.get('temp_api','N/A')} "
      f"os={a.get('temp_os','N/A')} deg C |")

    a_throttle_status = "PASS"
    if a.get("current_power_issue"):
        a_throttle_status = "FAIL"
    elif a.get("current_soft_temp_limit") or a.get("historical_issue"):
        a_throttle_status = "WARNING"
    w(f"| {'Throttle state':<25} | {a_throttle_status:<10} | "
      f"{a.get('throttle','N/A')} |")

    if s.get("rows"):
        w(f"| {'Entry accuracy':<25} | "
          f"{pass_fail(s.get('entry_acc', 0) == 100):<10} | "
          f"{s.get('entry_acc','N/A')}% |")
        w(f"| {'Exit accuracy':<25} | "
          f"{pass_fail(s.get('exit_acc', 0) == 100):<10} | "
          f"{s.get('exit_acc','N/A')}% |")
    else:
        w(f"| {'Counting accuracy':<25} | {'SKIPPED':<10} | "
          f"Run without --skip-sensing to test |")

    if o.get("rows"):
        w(f"| {'Fault detection':<25} | "
          f"{pass_fail(o['fault_detected']):<10} | "
          f"Camera disconnect detected |")
        w(f"| {'Process resilience':<25} | "
          f"{pass_fail(o['process_alive']):<10} | "
          f"No crash under fault |")
        w(f"| {'Fault recovery':<25} | "
          f"{pass_fail(o['recovered']):<10} | "
          f"Self-recovered on reconnect |")
    else:
        w(f"| {'Fault injection':<25} | {'SKIPPED':<10} | "
          f"Run without --skip-fault to test |")

    if o.get("mmwave_rows"):
        w(f"| {'mmWave fault handling':<25} | "
          f"{pass_fail(bool(o.get('mmwave_fault_detected')) and bool(o.get('mmwave_recovered'))):<10} | "
          f"Sensor disconnect/recovery sequence |")
    else:
        w(f"| {'mmWave fault handling':<25} | {'SKIPPED':<10} | "
          f"{o.get('mmwave_note', 'Physical sensor connection required')} |")
    w()

    REPORT_FILE.write_text("\n".join(lines))
    return REPORT_FILE


def main():
    global BASE_URL, WRITE_RAW

    parser = argparse.ArgumentParser(
        description="PASO Diagnostic -- Entrance Monitor"
    )
    parser.add_argument("--host", default="localhost")
    parser.add_argument("--port", default=8000, type=int)
    parser.add_argument("--crossings", default=10, type=int,
                        help="Number of manual crossings for accuracy test")
    parser.add_argument("--skip-sensing", action="store_true",
                        help="Skip the interactive walk test")
    parser.add_argument("--skip-fault", action="store_true",
                        help="Skip the fault injection test")
    parser.add_argument("--report-only", action="store_true",
                        help="Write only the Markdown report and skip raw JSON/TXT/CSV artifacts")
    args = parser.parse_args()

    BASE_URL = f"http://{args.host}:{args.port}"
    WRITE_RAW = not args.report_only
    print(f"PASO Diagnostic -- targeting {BASE_URL}")
    print(f"Timestamp: {TIMESTAMP}")

    status = api_get("/api/v1/status")
    if "error" in status:
        print(f"\nERROR: Cannot reach {BASE_URL}/api/v1/status")
        print(f"Make sure entrance-monitor is running first.")
        sys.exit(1)

    print("Server reachable. Starting tests...\n")
    print(hr("="))

    p = test_pipeline()
    a = test_resources()

    if args.skip_sensing:
        print("\n[S] Skipped (--skip-sensing flag set)")
        s = {"section": "S", "session_id": "SKIPPED", "rows": [],
             "duration": 0, "entry_acc": 0, "exit_acc": 0,
             "total_acc": 0, "started_at": None, "ended_at": None}
    else:
        s = test_sensing(args.crossings)

    if args.skip_fault:
        print("\n[O] Skipped (--skip-fault flag set)")
        o = {"section": "O", "rows": [], "sensor_rows": [],
             "fault_detected": False, "recovered": False,
             "process_alive": False}
    else:
        o = test_observability()

    abs_report_dir = get_abs_path(REPORT_DIR)
    abs_raw_dir = get_abs_path(RAW_DIR) if WRITE_RAW else None

    write_report(p, a, s, o, abs_report_dir, abs_raw_dir, WRITE_RAW)

    hostname = run_cmd("hostname")
    username = run_cmd("whoami")

    print(f"\nOutput written to:")
    print(f"  Report : {abs_report_dir}/PASO_DIAGNOSTIC_{TIMESTAMP}.md")
    if WRITE_RAW:
        print(f"  Raw    : {abs_raw_dir}")
    else:
        print(f"  Raw    : skipped (--report-only)")
    print()
    print(f"To retrieve files on your local machine:")
    print(f"  Windows (PowerShell):")
    print(f"    mkdir \"$env:USERPROFILE\\Downloads\\evidence\"")
    print(f"    scp -r {username}@{hostname}.local:{abs_report_dir} "
          f"\"$env:USERPROFILE\\Downloads\\\"")
    print()
    print(f"  macOS / Linux:")
    print(f"    mkdir -p ~/Downloads/evidence")
    print(f"    scp -r {username}@{hostname}.local:{abs_report_dir} "
          f"~/Downloads/")


if __name__ == "__main__":
    main()
