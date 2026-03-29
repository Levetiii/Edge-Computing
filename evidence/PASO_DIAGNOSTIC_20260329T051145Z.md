# PASO Diagnostic Report
**Project:** Entrance Monitor (INF2009 Edge Computing and Analytics)
**Generated:** 2026-03-29T05:13:11Z
**Device:** Raspberry Pi 5
**Script:** tests/paso_diagnostic.py

------------------------------------------------------------

## P -- Pipeline Latency Budget

**Test Methodology:**

Script sampled GET /api/v1/status over a short time window while entrance-monitor was running and summarized healthy samples to avoid single bad snapshots. GET /api/v1/settings was also queried to read the current configured cadence. Where exposed by the application, stage timings are taken directly from runtime perf_counter instrumentation. Only missing fields fall back to rough FPS-derived estimates. Communication layer uses REST and SSE (Server-Sent Events).

Source: /home/raspbpi/Downloads/Edge-Computing/docs/evidence/raw_20260329T051145Z/p_status.json
Source: /home/raspbpi/Downloads/Edge-Computing/docs/evidence/raw_20260329T051145Z/p_status_samples.json
Source: /home/raspbpi/Downloads/Edge-Computing/docs/evidence/raw_20260329T051145Z/p_settings.json

| Stage                               | Target (ms) | Measured (ms) | Basis                               | Status  |
|-------------------------------------|-------------|---------------|-------------------------------------|---------|
| Frame capture                       |       100.0 |        100.31 | observed 10.56 FPS vs target 10.0 FPS | PASS    |
| Capture to service handoff          |         TBC |         16.12 | Direct app timing                   | PASS    |
| Detector preprocess                 |         TBC |          2.64 | Direct app timing                   | PASS    |
| Detector inference                  |       100.0 |         69.98 | Direct app timing                   | PASS    |
| Detector postprocess                |         TBC |          2.13 | Direct app timing                   | PASS    |
| Detection total (ONNX)              |       100.0 |         74.75 | Direct app timing                   | PASS    |
| Detection filtering                 |         TBC |          0.02 | Direct app timing                   | PASS    |
| Tracking (custom centroid tracker)  |         TBC |          0.02 | Direct app timing                   | PASS    |
| Crossing logic                      |         TBC |           0.0 | Direct app timing                   | PASS    |
| Event enqueue                       |         TBC |           0.0 | Direct app timing                   | PASS    |
| SSE publish                         |          10 |          0.05 | Direct app timing                   | PASS    |
| Per-frame processing total          |         200 |         75.49 | Direct app timing                   | PASS    |

### Scheduling and Overload

- Target capture FPS: `10.0`
- Actual capture FPS: `10.56`
- Target detector FPS: `10.0`
- Actual detector FPS: `8.0`
- Drop ratio (30s): `0.01`
- Publish backlog: `0.0 ms`
- Status samples collected: `9`
- Healthy samples used: `9`

Note: this section prefers direct runtime timings from the application. Any stage still marked with FPS-based values or PENDING needs additional code instrumentation before final PASO submission.

------------------------------------------------------------

## A -- Resource Budget

**Test Methodology:**

Script queried GET /api/v1/status for application-level metrics (cpu_percent, ram_mb, temperature_c) and ran vcgencmd measure_temp, vcgencmd get_throttled, and free -h via subprocess for OS-level confirmation. Both sources captured simultaneously under normal load.

Source: /home/raspbpi/Downloads/Edge-Computing/docs/evidence/raw_20260329T051145Z/a_status.json
Source: /home/raspbpi/Downloads/Edge-Computing/docs/evidence/raw_20260329T051145Z/a_os.txt

| Resource                       |     Target |        Measured | Source Field              | Status  |
|--------------------------------|------------|-----------------|---------------------------|---------|
| CPU utilisation                |        80% |           51.7% | cpu_percent               | PASS    |
| RAM usage                      |    1536 MB |     1204.375 MB | ram_mb                    | PASS    |
| Temperature (API)              |   85 deg C |      82.6 deg C | temperature_c             | PASS    |
| Temperature (OS)               |   85 deg C |      83.4 deg C | vcgencmd measure_temp     | PASS    |
| Current throttle/freq cap      |      clear |           clear | vcgencmd get_throttled    | PASS    |
| Current soft temp limit        |      clear |            PASS | vcgencmd get_throttled    | PASS    |
| Throttle history               |      clear | frequency cap occurred, throttling occurred, soft temperature limit occurred | vcgencmd get_throttled    | WARNING |

Note: Historical flags: frequency cap occurred, throttling occurred, soft temperature limit occurred.

------------------------------------------------------------

## S -- Counting Accuracy (Validation Session)

**Test Methodology:**

Script started a validation session via POST /api/v1/validation/start. Tester physically walked in front of the camera crossing the virtual line (x=640, vertical center of 1280px frame) and pressed ENTER for ENTRY or E+ENTER for EXIT after each crossing. Script called POST /api/v1/validation/manual-entry or manual-exit accordingly. Session stopped via POST /api/v1/validation/stop and CSV exported via GET /api/v1/validation/export.csv.

Source: /home/raspbpi/Downloads/Edge-Computing/docs/evidence/raw_20260329T051145Z/s_session_stop.json
Source: /home/raspbpi/Downloads/Edge-Computing/docs/evidence/raw_20260329T051145Z/s_validation.csv

Session ID:  vs-efccb4426a9b
Started:     2026-03-29T04:46:33.266071Z
Ended:       2026-03-29T04:49:19.542095Z
Duration:    166.3 seconds

| Direction  |  Ground Truth |  System Detected |  Error |  Accuracy | Status  |
|------------|---------------|------------------|--------|-----------|---------|
| ENTRY      |            10 |               10 |      0 |    100.0% | PASS    |
| EXIT       |            10 |               10 |      0 |    100.0% | PASS    |
| TOTAL      |            20 |               20 |      0 |    100.0% | PASS    |

Virtual line configuration:
  Line: x1=640, y1=150 to x2=640, y2=650 (vertical, center of frame)
  Crossing direction: left to right = ENTRY, right to left = EXIT


------------------------------------------------------------

## O -- Observability and Fault Handling

### Test O-1: Camera Disconnection

**Test Methodology:**

Script captured baseline status, prompted tester to physically unplug the webcam USB cable, waited 5 seconds, then re-queried status to confirm fault detection. Tester was then prompted to replug the webcam. Script waited 5 seconds and re-queried to confirm recovery. Process liveness verified via ps aux throughout.

Source: /home/raspbpi/Downloads/Edge-Computing/docs/evidence/raw_20260329T051145Z/o_baseline.json
Source: /home/raspbpi/Downloads/Edge-Computing/docs/evidence/raw_20260329T051145Z/o_fault.json
Source: /home/raspbpi/Downloads/Edge-Computing/docs/evidence/raw_20260329T051145Z/o_recovery.json
Source: /home/raspbpi/Downloads/Edge-Computing/docs/evidence/raw_20260329T051145Z/o_process.txt

| Phase                          |  camera_status |         system_state |  Process | Status  |
|--------------------------------|----------------|----------------------|----------|---------|
| Baseline (before unplug)       |             OK |               NORMAL |     PASS | INFO    |
| After unplug (5s wait)         |   DISCONNECTED |  CAMERA_DISCONNECTED |     PASS | PASS    |
| After replug (5s wait)         |             OK |               NORMAL |     PASS | PASS    |

Result: PASS

### Test O-2: mmWave Sensor Fault

**Test Methodology:**

If the baseline mmwave_status is OK, script prompts the tester to unplug the mmWave sensor, waits 5 seconds, re-queries status, then prompts for replug and checks recovery after another 5 seconds. Process liveness is verified after the fault sequence.

Source: /home/raspbpi/Downloads/Edge-Computing/docs/evidence/raw_20260329T051145Z/o_mmwave_baseline.json
Source: /home/raspbpi/Downloads/Edge-Computing/docs/evidence/raw_20260329T051145Z/o_mmwave_fault.json
Source: /home/raspbpi/Downloads/Edge-Computing/docs/evidence/raw_20260329T051145Z/o_mmwave_recovery.json
Source: /home/raspbpi/Downloads/Edge-Computing/docs/evidence/raw_20260329T051145Z/o_mmwave_process.txt

| Phase                          |  mmwave_status |         system_state |  Process | Status  |
|--------------------------------|----------------|----------------------|----------|---------|
| Baseline (before unplug)       |             OK |               NORMAL |     PASS | INFO    |
| After unplug (5s wait)         |   DISCONNECTED |  MMWAVE_DISCONNECTED |     PASS | PASS    |
| After replug (5s wait)         |             OK |               NORMAL |     PASS | PASS    |

Result: PASS

### Test O-3: Dual Sensor Health Reporting

Source: /home/raspbpi/Downloads/Edge-Computing/docs/evidence/raw_20260329T051145Z/o_metrics.json
Source: /home/raspbpi/Downloads/Edge-Computing/docs/evidence/raw_20260329T051145Z/o_status_final.json

| Sensor                    | Status Field         | Measured Value                           |
|---------------------------|----------------------|------------------------------------------|
| Camera (C270 HD)          | camera_status        | OK                                       |
| mmWave sensor             | mmwave_status        | OK                                       |
| Presence fusion           | presence_corroboration_state | PRESENT                                  |
| Gated mode                | gated_mode           | False                                    |
| Overall system            | system_state         | NORMAL                                   |
| Count confidence          | count_confidence     | HIGH                                     |

------------------------------------------------------------

## Summary

| Area                      | Result     | Notes |
|---------------------------|------------|-------|
| Pipeline FPS              | PASS       | delivered=10.56 detector=8.0 target=10.0 |
| CPU/RAM                   | PASS       | cpu=51.7% ram=1204.375MB |
| Temperature               | PASS       | api=82.6 os=83.4 deg C |
| Entry accuracy            | PASS       | 100.0% |
| Exit accuracy             | PASS       | 100.0% |
| Fault detection           | PASS       | Camera disconnect detected |
| Process resilience        | PASS       | No crash under fault |
| Fault recovery            | PASS       | Self-recovered on reconnect |
| mmWave fault handling     | PASS       | Sensor disconnect/recovery sequence |