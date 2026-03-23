# Entrance Monitor

Edge-first entrance flow and busyness monitoring prototype for Raspberry Pi 5.

Current development webcam: `Logi C270 HD` over USB/UVC.

## What this includes

- USB webcam first capture path using OpenCV/V4L2
- mmWave adapter with serial and mock modes
- Person detection backend abstraction with:
  - ONNX Runtime YOLO path for live detection
  - synthetic mock detector for hardware-free regression testing
- Lightweight centroid tracker and virtual line crossing
- Rolling metrics, closed state enums, warning flags, and confidence logic
- FastAPI read-only REST API
- SSE live stream
- Operator dashboard and local-only debug/calibration view
- Local-only settings page for live ROI/line/threshold edits
- SQLite storage for metrics snapshots and events

## What this does not assume

- It does not upload raw media.
- It does not require cloud inference.
- It does not require a specific mmWave module to start; mock mode is supported.

## Current scope and limitations

- Camera is the only source of truth for `entry`, `exit`, and `net flow`.
- mmWave is currently advisory only and is still a placeholder integration until the real module protocol is implemented.
- Windows and Raspberry Pi now share the same ONNX Runtime detector path, so the app no longer depends on the `torch` or `ultralytics` runtime stack.
- Tracking is still a lightweight prototype tracker. It is good enough for calibration and basic demos, but not yet equivalent to a production-grade ByteTrack-style association flow.
- The normal dashboard is metrics-first. `/debug` and `/settings` are local-only and are the only places where raw annotated frames or calibration controls should appear.
- The current top KPI cards are proposal-facing rates. They are derived from the rolling 30-second counts, so `1 crossing in 30s` will display as `2 / min`.

## Quick start

1. Create a virtual environment and install:

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -e .[dev,serial]
```

2. Run the current Windows development setup:

```powershell
entrance-monitor --config config/windows-webcam.yaml
```

3. For the hardware-free mock pipeline instead, run:

```powershell
entrance-monitor --config config/default.yaml
```

4. Open:

- Operator dashboard: `http://127.0.0.1:8000/`
- Local debug view: `http://127.0.0.1:8000/debug`
- Local settings page: `http://127.0.0.1:8000/settings`
- Local validation page: `http://127.0.0.1:8000/validation`

## Config files

- `config/default.yaml` is the mock baseline:
  - mock camera
  - mock mmWave
  - mock detector
- `config/windows-webcam.yaml` is the current Windows development setup:
  - real webcam
  - ONNX Runtime YOLO detector
  - mock mmWave
- `config/windows-video.sample.yaml` is the tracked sample for recorded video playback.
- `config/pi.sample.yaml` is the tracked Raspberry Pi sample for real camera, serial mmWave, and ONNX YOLO.
- `config/windows-video.yaml` and `config/*.local.yaml` are ignored on purpose so machine-specific paths and device settings do not get committed.

You can also tune ROI, line, detector confidence, cooldown, and busyness thresholds from the local-only settings page at `/settings`. Changes are applied immediately and saved back to the active YAML config.

- Set `camera.source` to:
  - an integer webcam index such as `0`
  - a file path for recorded video
  - `"mock"` for synthetic frames
- Set `mmwave.mode` to:
  - `"serial"` for a real sensor
  - `"mock"` for generated presence events
- Set `detector.backend` to:
  - `"onnx"` for the current webcam and Pi setup
  - `"mock"` for the synthetic regression path

## Proposal KPI mapping

The API exposes exact rolling counts:

- `entry_count_30s`
- `exit_count_30s`
- `net_count_30s`
- `crossing_count_30s`

The dashboard also shows derived proposal-facing KPIs:

- `entry_rate_per_min = entry_count_30s * 2`
- `exit_rate_per_min = exit_count_30s * 2`
- `net_flow_per_min = net_count_30s * 2`
- `busyness_level = entrance_load_level`

This is why the rate cards can look doubled during manual testing:

- `1 entry in the last 30s -> 2 / min`
- `3 entries in the last 30s -> 6 / min`

When validating the system, compare against the raw `*_count_30s` fields first, then treat the `*_rate_per_min` cards as an estimated pace indicator.

## Research-backed implementation priorities

The most important next changes, based on current product and technique research, are:

1. Add raw `30s` counts directly beside the KPI rate cards.
2. Add trend/history charts from `/api/v1/metrics/history`.
3. Add CSV export and richer result reporting to the validation workflow.
4. Harden settings persistence with atomic save, rollback, and a settings audit trail.
5. Benchmark the ONNX Runtime path for `YOLO11n` on the Pi and tune confidence/imgsz if needed.
6. Replace the lightweight centroid tracker with a stronger tracker.
7. Keep mmWave advisory only until the real protocol and calibration flow are implemented.

## Validation guidance

Use a calibration-first workflow:

1. Align ROI and line in `/settings` and `/debug`.
2. Use `/validation` to start a session, record manual entries/exits, and compare against the live system counts.
3. Run a pilot of `20-30` crossings per direction.
4. For formal validation, record the raw `30s` counts, recent events, and manual ground truth.
5. Do not report a single universal accuracy number; report by condition:
   - normal walking
   - back-and-forth
   - loitering near the line
   - grouped crossings
   - low light / occlusion

Commercial products such as Axis and VIVOTEK treat validation as a first-class workflow, not just a screenshot exercise.

## Security and privacy posture

- Keep the normal service bound to `127.0.0.1` unless you intentionally set up LAN access.
- Do not expose `/debug` or `/settings` beyond the local machine.
- No raw video or audio should be stored or published by the normal dashboard/API.
- If you later expose the dashboard on a LAN, add authentication before doing so.

## Setup guides

### Windows development

Use `config/windows-webcam.yaml` for the current setup:

- `camera.source: 0`
- `camera.backend: "dshow"`
- `detector.backend: "onnx"`
- `detector.model_path: "yolo11n.onnx"`
- `mmwave.mode: "mock"`

Run:

```powershell
entrance-monitor --config config/windows-webcam.yaml
```

Tracked webcam config:

```yaml
camera:
  source: 0
  backend: "dshow"
detector:
  backend: "onnx"
  model_path: "yolo11n.onnx"
mmwave:
  mode: "mock"
```

Notes:

- Current development webcam: `Logi C270 HD`
- If your camera index changes, test `0` and `1` first.
- Export or copy your ONNX model to `yolo11n.onnx`, or update `detector.model_path` to wherever your exported model lives.
- This is now the primary development path for the project.
- Raspberry Pi-only telemetry such as `vcgencmd` thermal and undervoltage flags is not available on Windows.

Use `config/default.yaml` when you want the mock regression path:

```powershell
entrance-monitor --config config/default.yaml
```

That keeps the full pipeline hardware-free for regression testing.

Use a recorded entrance video:

```powershell
Copy-Item config/windows-video.sample.yaml config/windows-video.yaml
entrance-monitor --config config/windows-video.yaml
```

Then edit `config/windows-video.yaml` and set:

```yaml
camera:
  source: "path/to/your/entrance-video.mp4"
```

Notes:

- `config/windows-video.yaml` is intentionally ignored so you can keep a machine-local video path there.
- Keep `mmwave.mode: "mock"` unless you have the real sensor connected.
- This is useful for ROI tuning, line placement, and repeatable offline testing.

### Raspberry Pi deployment

Install system packages:

```bash
sudo apt update
sudo apt install -y python3 python3-venv python3-pip git libcap-dev v4l-utils
sudo apt install -y htop sqlite3
```

Clone and install:

```bash
git clone <your-repo-url> edge
cd edge
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e .[dev,serial]
```

Check the webcam and serial device:

```bash
v4l2-ctl --list-devices
v4l2-ctl --list-formats-ext -d /dev/video0
ls /dev/tty*
```

Create a Pi-specific local config from `config/pi.sample.yaml`:

```bash
cp config/pi.sample.yaml config/pi.local.yaml
```

Then update `config/pi.local.yaml`:

```yaml
camera:
  source: 0
  backend: "auto"

mmwave:
  mode: "serial"
  port: "/dev/ttyUSB0"

detector:
  backend: "onnx"
  model_path: "yolo11n.onnx"
```

Notes:

- Start from `config/pi.sample.yaml`, not `config/windows-webcam.yaml`.
- Keep `config/default.yaml` for mock regression testing only.
- Tune ROI and line coordinates on the Pi after the real camera is mounted.
- Change `/dev/ttyUSB0` if your mmWave sensor appears under a different device name.
- The Pi expects an exported ONNX model file. The repo no longer installs the Ultralytics runtime.

Then run:

```bash
entrance-monitor --config config/pi.local.yaml
```

Verify:

- camera capture is stable
- mmWave samples arrive and parse correctly
- CPU, temperature, and FPS are acceptable
- no raw media is stored
- the dashboard and API still work during local network interruptions
