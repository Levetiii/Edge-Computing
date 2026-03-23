# Entrance Monitor

Edge-first entrance flow and busyness monitoring prototype for Raspberry Pi 5.

Current development webcam: `Logi C270 HD` over USB/UVC.

## What this includes

- USB webcam first capture path using OpenCV/V4L2
- mmWave adapter with serial and mock modes
- Person detection backend abstraction with:
  - active Ultralytics YOLO webcam path for live detection
  - HOG fallback detector if you need a no-weights baseline
- Lightweight centroid tracker and virtual line crossing
- Rolling metrics, closed state enums, warning flags, and confidence logic
- FastAPI read-only REST API
- SSE live stream
- Operator dashboard and local-only debug/calibration view
- SQLite storage for metrics snapshots and events

## What this does not assume

- It does not upload raw media.
- It does not require cloud inference.
- It does not require a specific mmWave module to start; mock mode is supported.

## Quick start

1. Create a virtual environment and install:

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -e .[dev,serial,yolo]
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

## Config files

- `config/default.yaml` is the mock baseline:
  - mock camera
  - mock mmWave
  - HOG detector
- `config/windows-webcam.yaml` is the current Windows development setup:
  - real webcam
  - Ultralytics YOLO detector
  - mock mmWave
- `config/windows-video.sample.yaml` is the tracked sample for recorded video playback.
- `config/pi.sample.yaml` is the tracked Raspberry Pi sample for real camera, serial mmWave, and YOLO.
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
  - `"ultralytics"` for the current webcam setup
  - `"hog"` for the built-in baseline fallback

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

## Setup guides

### Windows development

Use `config/windows-webcam.yaml` for the current setup:

- `camera.source: 0`
- `camera.backend: "dshow"`
- `detector.backend: "ultralytics"`
- `detector.model_path: "yolo11n.pt"`
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
  backend: "ultralytics"
  model_path: "yolo11n.pt"
mmwave:
  mode: "mock"
```

Notes:

- Current development webcam: `Logi C270 HD`
- If your camera index changes, test `0` and `1` first.
- The first Ultralytics run may download `yolo11n.pt`; that file is ignored by Git.
- This is now the primary development path for the project.
- Raspberry Pi-only telemetry such as `vcgencmd` thermal and undervoltage flags is not available on Windows.

Use `config/default.yaml` when you want the old mock/HOG path:

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
python -m pip install -e .[dev,serial,yolo]
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
  backend: "ultralytics"
  model_path: "yolo11n.pt"
```

Notes:

- Start from `config/pi.sample.yaml`, not `config/windows-webcam.yaml`.
- Keep `config/default.yaml` for mock/HOG testing only.
- Tune ROI and line coordinates on the Pi after the real camera is mounted.
- Change `/dev/ttyUSB0` if your mmWave sensor appears under a different device name.

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
