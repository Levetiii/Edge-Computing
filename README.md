# Entrance Monitor

Entrance Monitor is an edge analytics project for the `INF2009: Edge Computing & Analytics` module. It is designed to monitor entrance activity in real time using on-device processing on a Raspberry Pi 5 class deployment target.

The system combines camera-based person detection and tracking with mmWave sensing to estimate entrance flow, busyness, and recent crossing activity. Results are exposed through a local dashboard, API, and validation workflow for calibration and demonstration. The reference development webcam is `Logi C270 HD` over USB/UVC.

## Core features

The project integrates these main capabilities:

- Vision pipeline:
  - webcam or recorded video input
  - ONNX Runtime person detection
  - centroid tracking and virtual line crossing
- mmWave integration:
  - serial mode for sensor input
  - mock mode for hardware-independent testing
  - presence sensing and warning logic
- Edge service and dashboard:
  - rolling metrics and recent events
  - live dashboard and SSE stream
  - local calibration, configuration, and validation pages
- Local persistence:
  - SQLite storage for snapshots, events, and validation sessions

## Repository layout

- `config/`: sample and environment-specific configuration files
- `scripts/`: helper scripts for model and project utilities
- `src/entrance_monitor/`: runtime, API, storage, and web application code
- `tests/`: automated test suite

## System architecture

![System architecture](assets/system-architecture.svg)

The implementation follows a single-edge-node architecture:

- camera input is processed locally for detection, tracking, and line-crossing estimation
- mmWave input provides an additional sensing stream for presence-related logic and system monitoring
- metrics and events are stored locally in SQLite and published through REST, SSE, and the web dashboard
- calibration and validation workflows are provided through local routes for configuration and testing

## Hardware and software selection

- Edge platform: Raspberry Pi 5
  Purpose: primary deployment target for on-device analytics.
- Vision sensor: USB webcam
  Purpose: entrance monitoring and person detection input.
- Auxiliary sensor: mmWave module
  Purpose: additional sensing stream for presence-related logic.
- Inference runtime: ONNX Runtime
  Purpose: local model execution on both development and deployment paths.
- Backend service: FastAPI
  Purpose: local API, SSE stream, and dashboard backend.
- Local storage: SQLite
  Purpose: embedded persistence for snapshots, events, and validation sessions.

## Team

- Lim Sheng Yang
- Lim Xin Yi
- Hing Zheng Wen
- Lee Ru Yuan

## Scope and limitations

- The present implementation is focused on single-entrance monitoring and calibration workflows.
- The main dashboard is metrics-focused. `/debug` and `/settings` are local routes intended for annotated frames and calibration controls.
- The top KPI cards are derived rate estimates calculated from the rolling 30-second counts.

## System outputs

The system produces these main outputs:

- `entry_count_30s`
- `exit_count_30s`
- `net_count_30s`
- `crossing_count_30s`
- `entry_rate_per_min`
- `exit_rate_per_min`
- `net_flow_per_min`
- `busyness_level`
- recent crossing activity and system status indicators

These outputs are presented through the local dashboard and API for monitoring, calibration, and validation.

## Privacy and edge rationale

- inference is performed locally on the edge device rather than in the cloud
- only derived, non-identifying metrics are published through the dashboard and API
- raw video is not intended to be stored or transmitted as part of the normal monitoring workflow
- the system is designed for continued local operation without depending on cloud inference

## Evaluation

The project is evaluated using both system performance and counting reliability criteria:

- sustained inference FPS and end-to-end responsiveness from capture to dashboard update
- CPU temperature and runtime stability during continuous operation
- entry and exit counting accuracy against manual ground truth
- stress conditions such as grouped crossings, occlusion, lighting variation, and repeated crossings near the line
- validation workflows supported by the local validation interface and stored session records

## Deployment guides

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

Run:

```bash
entrance-monitor --config config/pi.local.yaml
```

Verify:

- camera capture is stable
- mmWave samples arrive and parse correctly
- CPU, temperature, and FPS are acceptable
- no raw media is stored
- the dashboard and API remain available during local network interruptions

### Windows development

Use `config/windows-webcam.yaml` for the Windows development setup:

- `camera.source: 0`
- `camera.backend: "dshow"`
- `detector.backend: "onnx"`
- `detector.model_path: "yolo11n.onnx"`
- `mmwave.mode: "mock"`

Run:

```powershell
entrance-monitor --config config/windows-webcam.yaml
```

Reference configuration:

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

- If your camera index changes, test `0` and `1` first.
- Ensure that `yolo11n.onnx` is available at the configured model path.
- Raspberry Pi-only telemetry such as `vcgencmd` thermal and undervoltage flags is not available on Windows.

Use `config/default.yaml` for the mock regression path:

```powershell
entrance-monitor --config config/default.yaml
```

This supports end-to-end regression testing without requiring connected hardware.

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

- `config/windows-video.yaml` is excluded from version control so that machine-local video paths can be used safely.
- Keep `mmwave.mode: "mock"` unless a physical sensor is connected.
- This path is useful for ROI tuning, line placement, and repeatable offline testing.
