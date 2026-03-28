# Entrance Monitor

Entrance Monitor is an edge analytics project for the `INF2009: Edge Computing & Analytics` module. It is designed to monitor entrance activity in real time using on-device processing on a Raspberry Pi 5 class deployment target.

The system combines camera-based person detection and tracking with mmWave sensing to estimate entrance flow, busyness, and recent crossing activity. Results are exposed through a local dashboard, API, and validation workflow for calibration and demonstration. The reference development webcam is `Logi C270 HD` over USB/UVC. The reference mmWave sensor is the `MR24HPC1` connected via GPIO UART.

## Core features

- Vision pipeline:
  - webcam or recorded video input
  - ONNX Runtime person detection (YOLOv11n)
  - centroid tracking and virtual line crossing
- mmWave integration:
  - serial mode for MR24HPC1 sensor input via GPIO UART
  - sliding window majority vote for noise-robust presence detection
  - mock mode for hardware-independent testing
- Edge service and dashboard:
  - rolling metrics and recent events
  - live dashboard and SSE stream
  - local calibration, configuration, and validation pages
- Local persistence:
  - SQLite storage for snapshots, events, and validation sessions

## Repository layout

- `config/` — sample and environment-specific configuration files
- `scripts/` — helper scripts for model and project utilities
- `src/entrance_monitor/` — runtime, API, storage, and web application code
- `tests/` — automated test suite
- `yolo11n.onnx` — bundled ONNX model for person detection

## System architecture

![System architecture](assets/system-architecture.svg)

- camera input is processed locally for detection, tracking, and line-crossing estimation
- mmWave input gates camera power and corroborates presence events
- metrics and events are stored locally in SQLite and published through REST, SSE, and the web dashboard
- calibration and validation workflows are provided through local routes for configuration and testing

## Hardware

- Edge platform: Raspberry Pi 5
- Vision sensor: USB webcam (UVC-compatible, e.g. Logitech C270)
- mmWave sensor: Seeed Studio MR24HPC1, wired to GPIO UART (TX=pin8, RX=pin10) at 115200 baud
- Inference runtime: ONNX Runtime (CPU)
- Backend: FastAPI + Uvicorn
- Storage: SQLite

## Team

- Lim Sheng Yang
- Lim Xin Yi
- Hing Zheng Wen
- Lee Ru Yuan

---

## Raspberry Pi 5 — Quick Start

### 1. System packages

```bash
sudo apt update
sudo apt install -y python3 python3-venv python3-pip git libcap-dev v4l-utils htop sqlite3 tmux
```

### 2. Enable UART for mmWave sensor

The MR24HPC1 connects to the Pi 5 GPIO UART pins (TX=pin8, RX=pin10).

```bash
sudo raspi-config
# Interface Options → Serial Port
# → No to login shell over serial
# → Yes to serial port hardware enabled
sudo reboot
```

After reboot, confirm the port exists:

```bash
ls -la /dev/ttyAMA0
```

### 3. Clone and install

```bash
git clone <your-repo-url> edge
cd edge
python3 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -e ".[dev,serial]"
```

### 4. Check connected hardware

```bash
# Webcam
v4l2-ctl --list-devices

# mmWave serial port
ls /dev/ttyAMA0
```

### 5. Create local config

```bash
cp config/pi.yaml config/pi.local.yaml
```

`config/pi.yaml` is pre-configured for the Pi 5 with:
- Camera on `/dev/video0` via v4l2 at 1280×720 10fps
- mmWave on `/dev/ttyAMA0` at 115200 baud in serial mode
- YOLO11n ONNX model

Edit `config/pi.local.yaml` only if your hardware differs (different camera index, serial port, etc.).

### 6. Run

```bash
source .venv/bin/activate
entrance-monitor --config config/pi.local.yaml
```

Dashboard available at `http://<pi-ip>:8000` from any device on the same network.

### 7. Run headless (no monitor needed)

Use tmux to keep the app running after SSH disconnect:

```bash
tmux new -s monitor
source .venv/bin/activate
entrance-monitor --config config/pi.local.yaml
# Detach: Ctrl+B then D
# Reattach later: tmux attach -t monitor
```

---

## Dashboard routes

| Route | Purpose |
|---|---|
| `/` | Main metrics dashboard |
| `/debug` | Annotated camera frames and pipeline state |
| `/settings` | Line, ROI, and threshold calibration |
| `/validation` | Manual counting validation sessions |

---

## mmWave notes

The MR24HPC1 uses a sliding window majority vote to determine presence — individual frame values are noisy, especially in small or enclosed spaces. The sensor gates camera power: camera turns on when presence is detected, off when absent, reducing unnecessary inference load.

**If the sensor stops producing data or outputs unexpected values**, restore standard presence mode:

```bash
python3 - << 'EOF'
import serial, time
ser = serial.Serial('/dev/ttyAMA0', 115200, timeout=2)
frame = bytearray([0x53, 0x59, 0x08, 0x00, 0x00, 0x01, 0x00])
frame += bytearray([sum(frame) & 0xFF, 0x54, 0x43])
ser.write(frame)
time.sleep(1)
print("Done:", ser.read(64).hex())
EOF
```

Then power cycle the sensor (unplug and replug).

**To run without a physical mmWave sensor**, use mock mode in your config:

```yaml
mmwave:
  mode: "mock"
  mock_present_seconds: 9999
  mock_absent_seconds: 1
```

---

## Windows development

Use `config/windows-webcam.yaml` for development without a Pi:

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

```powershell
entrance-monitor --config config/windows-webcam.yaml
```

Use `config/default.yaml` for fully mocked regression testing (no camera or sensor required):

```powershell
entrance-monitor --config config/default.yaml
```

Use a recorded video file:

```powershell
Copy-Item config/windows-video.sample.yaml config/windows-video.yaml
# Edit windows-video.yaml and set camera.source to your video path
entrance-monitor --config config/windows-video.yaml
```

---

## System outputs

| Metric | Description |
|---|---|
| `entry_count_30s` | Entries in the last 30 seconds |
| `exit_count_30s` | Exits in the last 30 seconds |
| `net_count_30s` | Net flow in the last 30 seconds |
| `crossing_count_30s` | Total crossings in the last 30 seconds |
| `entry_rate_per_min` | Projected entry rate per minute |
| `exit_rate_per_min` | Projected exit rate per minute |
| `net_flow_per_min` | Projected net flow per minute |
| `busyness_level` | Low / Medium / High based on crossing intensity |

---

## Privacy and edge rationale

- all inference runs locally on the Pi, no cloud dependency
- only derived non-identifying metrics leave the device
- raw video is never stored or transmitted
- the system continues operating during network outages

## Scope and limitations

- single-entrance monitoring only
- counting accuracy degrades with heavy occlusion or simultaneous side-by-side crossings
- mmWave presence detection sensitivity depends on room size and sensor placement — works best when sensor is co-located with the camera, pointed directly at the entrance zone
- `/debug` and `/settings` are local-only routes for calibration, not intended for production exposure