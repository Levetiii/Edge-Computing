# Entrance Monitor

Entrance Monitor is an edge analytics project for the `INF2009: Edge Computing & Analytics` module. It is designed to monitor entrance activity in real time using on-device processing on a Raspberry Pi 5 deployment target.

The system combines camera-based person detection and tracking with mmWave sensing to estimate entrance flow, busyness, and recent crossing activity. Results are exposed through a local dashboard, API, and validation workflow for calibration and evaluation. The validated hardware configuration uses a `Logi C270 HD` webcam over USB/UVC and an `MR24HPC1` mmWave sensor connected through GPIO UART.

## Core features

- Vision pipeline:
  - webcam or recorded video input
  - ONNX Runtime person detection (YOLOv11n)
  - centroid tracking and virtual line crossing
- mmWave integration:
  - serial mode for MR24HPC1 sensor input via GPIO UART
  - sliding window vote-based smoothing for noisy presence readings
  - mock mode for hardware-independent testing
- Edge service and dashboard:
  - rolling metrics and recent events
  - live dashboard and SSE stream
  - local calibration, configuration, and validation pages
- Local persistence:
  - SQLite storage for snapshots, events, and validation sessions

## Repository layout

```text
/edge
├── README.md                         # Project overview, deployment guide, and measured Pi 5 results
├── pyproject.toml                    # Python package metadata, dependencies, and optional extras
├── yolo11n.onnx                      # Deployed ONNX model used by the detector runtime
│
├── /assets
│   └── system-architecture.svg       # System architecture diagram used in this README
│
├── /config
│   ├── default.yaml                  # Fully mocked configuration for regression testing
│   ├── pi.yaml                       # Main Raspberry Pi deployment configuration
│   ├── pi.sample.yaml                # Pi test configuration used during mock mmWave workflows
│   ├── windows-webcam.yaml           # Windows development configuration with webcam input
│   └── windows-video.sample.yaml     # Sample configuration for recorded video input
│
├── /evidence
│   ├── PASO_DIAGNOSTIC_20260329T051145Z.md   # Primary PASO diagnostic report
│   ├── summary.md                    # 30-second benchmark summary
│   ├── summary.json                  # Machine-readable benchmark summary
│   ├── samples.csv                   # Benchmark status samples in CSV format
│   ├── samples.jsonl                 # Benchmark status samples in JSONL format
│   ├── image_2026-03-29_11-51-28.png         # perf stat screenshot
│   ├── image_2026-03-29_11-51-28 (2).png     # perf report screenshot
│   └── image_2026-03-29_11-51-28 (3).png     # cProfile screenshot
│
├── /scripts
│   ├── export_onnx.py                # Exports the PyTorch model to ONNX
│   ├── paso_benchmark.py             # Samples runtime status and writes benchmark artifacts
│   ├── compare_benchmarks.py         # Compares multiple benchmark summaries
│   └── quantize_onnx.py              # Optional offline INT8 ONNX quantization utility
│
├── /src
│   └── /entrance_monitor
│       ├── __init__.py               # Package marker
│       ├── main.py                   # Application entry point
│       ├── api.py                    # FastAPI routes, dashboard pages, and SSE endpoints
│       ├── camera.py                 # Camera capture, ROI handling, and reconnect logic
│       ├── config.py                 # Settings models and config loading helpers
│       ├── detector.py               # ONNX preprocessing, inference, and decode logic
│       ├── mmwave.py                 # MR24HPC1 serial/mock sensor handling
│       ├── models.py                 # Shared payload and schema definitions
│       ├── service.py                # Core runtime orchestration and status generation
│       ├── storage.py                # SQLite persistence and async writing
│       ├── tracking.py               # Centroid tracking and line-crossing logic
│       ├── utils.py                  # Shared utility helpers
│       └── /web
│           ├── /static
│           │   ├── app.css           # Dashboard styling
│           │   └── app.js            # Dashboard client-side logic
│           └── /templates
│               ├── index.html        # Main dashboard page
│               ├── debug.html        # Debug visualisation page
│               ├── settings.html     # Settings and calibration page
│               └── validation.html   # Manual validation page
│
└── /tests
    ├── paso_diagnostic.py            # PASO runner for pipeline, resources, and fault handling
    ├── test_api.py                   # API route and payload tests
    ├── test_camera_video.py          # Video-input camera tests
    ├── test_detector.py              # Detector backend tests
    ├── test_paso_benchmark.py        # Benchmark sampling and deduplication tests
    ├── test_service_logic.py         # Runtime service logic tests
    ├── test_storage.py               # SQLite storage tests
    └── test_tracking.py              # Tracker and line-crossing tests
```

## System architecture

![System architecture](assets/system-architecture.svg)

- camera input is processed locally for detection, tracking, and line-crossing estimation
- mmWave input corroborates presence events and supports sensor-assisted runtime control
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

## Measured Raspberry Pi 5 Results

The evidence set in `evidence/` shows that the Raspberry Pi 5 deployment is stable enough for live entrance monitoring in the tested Pi configuration, with a configured `10 FPS` camera cadence and CPU-only ONNX inference.

### PASO diagnostic

Primary PASO file:
- `evidence/PASO_DIAGNOSTIC_20260329T051145Z.md`

Key PASO results from the submission run:
- capture FPS: `10.56`
- detector FPS: `8.0`
- detector total latency: `74.75 ms`
- per-frame processing total: `75.49 ms`
- no observable publish backlog during the PASO run
- healthy samples used: `9/9`
- measured resources during the PASO sample window:
  - CPU: `51.7%`
  - RAM: `1204.375 MB`
  - API temperature: `82.6 C`
  - OS temperature: `83.4 C`
- validation result from the same PASO evidence set:
  - in the recorded validation session, entry counts matched ground truth
  - in the recorded validation session, exit counts matched ground truth
  - in the recorded validation session, total counts matched ground truth
- fault-handling result from the same PASO evidence set:
  - camera unplug/replug: `PASS`
  - mmWave unplug/replug: `PASS`

### 30-second benchmark

Supporting benchmark files:
- `evidence/summary.md`
- `evidence/summary.json`
- `evidence/samples.csv`
- `evidence/samples.jsonl`

Key benchmark results:
- delivered FPS average: `10.4`
- detector FPS average: `8.2`
- drop ratio average: `0.04`
- detector inference average: `59.77 ms`
- detector total average: `64.03 ms`
- per-frame processing total average: `64.77 ms`
- CPU average: `54.81%`
- RAM average: `1347.49 MB`
- temperature average: `82.86 C`

These benchmark results align with the PASO run and support the same conclusion: capture throughput is stable at roughly `10 FPS`, detector throughput is stable at roughly `8 FPS`, and publish overhead is negligible.

### Profiling evidence

The runtime measurements are supported by Linux and Python profiling captures stored in `evidence/`.

`perf stat` result:
- `154,041,310,630` cycles
- `273,896,454,444` instructions
- `1.78` instructions per cycle
- `1.50%` cache-miss rate
- `0.11%` branch-miss rate

Interpretation:
- the process is executing efficiently on the Pi CPU
- there is no obvious sign of pathological cache or branch behavior

`perf report` result:
- most sampled CPU time is inside `onnxruntime_pybind11_state`

Interpretation:
- the dominant hotspot is native ONNX Runtime inference
- the main bottleneck is not the tracker, REST/SSE layer, or storage path

`cProfile` result:
- the main Python-heavy work is startup/import cost
- the hottest Python-side paths are FastAPI, Pydantic, and module loading

Interpretation:
- this capture is dominated by startup and import-time Python work rather than live inference
- there is no strong case for `line_profiler` as the next optimization step from this profile alone

### Evidence screenshots

**perf stat**

![perf stat evidence](evidence/image_2026-03-29_11-51-28.png)

**perf report**

![perf report evidence](evidence/image_2026-03-29_11-51-28%20(2).png)

**cProfile**

![cProfile evidence](evidence/image_2026-03-29_11-51-28%20(3).png)

### Deployment conclusions

Based on the submission evidence set:
- the camera path is stable at approximately `10 FPS`
- the detector sustains approximately `8 FPS` on the Pi 5 in the tested configuration
- the main hotspot is ONNX inference, not the tracker or HTTP layer
- resource usage is within a practical Pi 5 budget for CPU, RAM, and temperature during the measured windows, with historical throttle flags noted in PASO
- camera and mmWave disconnect recovery both work in the tested setup
- the system is suitable as a practical Pi 5 deployment for the project

---

## Raspberry Pi 5 Deployment

### 1. System packages

```bash
sudo apt update
sudo apt install -y python3 python3-venv python3-pip git libcap-dev v4l-utils htop sqlite3 tmux
```

### 2. Enable UART for mmWave sensor

The MR24HPC1 connects to the Pi 5 GPIO UART pins (TX=pin8, RX=pin10).

```bash
sudo raspi-config
# Interface Options -> Serial Port
# -> No to login shell over serial
# -> Yes to serial port hardware enabled
sudo reboot
```

After reboot, confirm the port exists:

```bash
ls -la /dev/ttyAMA0
```

### 3. Clone and install

```bash
git clone <repository-url> edge
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
- camera on `/dev/video0` via `v4l2` at `1280x720` and `10 FPS`
- mmWave on `/dev/ttyAMA0` at `115200` baud in serial mode
- YOLO11n ONNX model

Edit `config/pi.local.yaml` only if your hardware differs.

### 6. Run

```bash
source .venv/bin/activate
entrance-monitor --config config/pi.local.yaml
```

Dashboard available at `http://<pi-ip>:8000` from any device on the same network.

To view the dashboard from a Windows machine on the same network:

```powershell
# Find the Pi IP on Raspberry Pi
hostname -I
```

Then open a browser on Windows and visit:

```text
http://<pi-ip>:8000
```

If `app.local_debug_only` is enabled, only the main dashboard is intended for remote viewing. Calibration-oriented routes such as `/debug`, `/settings`, and `/validation` should be accessed locally on the Pi or only on trusted networks.

### 7. Run headless

Use `tmux` to keep the app running after SSH disconnect:

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

The MR24HPC1 path uses a sliding window voting heuristic to smooth noisy presence readings. Individual frame values can be noisy, especially in small or enclosed spaces.

If the sensor stops producing data or outputs unexpected values, restore standard presence mode:

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

Then power cycle the sensor.

To run without a physical mmWave sensor, use mock mode in your config:

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

- all inference runs locally on the Pi, with no cloud dependency
- only derived non-identifying metrics are intended for normal downstream use
- raw video is not persisted by the default storage pipeline
- the system continues operating during network outages

## Scope and limitations

- single-entrance monitoring only
- counting accuracy may degrade under heavy occlusion or simultaneous side-by-side crossings
- mmWave presence detection sensitivity depends on room size and sensor placement and works best when the sensor is co-located with the camera, pointed directly at the entrance zone
- `/debug`, `/settings`, and `/validation` are calibration-oriented routes and should only be exposed on trusted networks; local-only enforcement depends on `app.local_debug_only`
