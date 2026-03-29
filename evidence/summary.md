# PASO Benchmark Summary
Generated: 2026-03-29T03:26:54Z
Samples: 30
Duration seconds: 30

## Scheduler
- Target capture FPS: `10.0`
- Target detector FPS: `10.0`
- Dominant camera status: `OK`
- Dominant system state: `NORMAL`

## Throughput
- Delivered FPS avg/min/max: `{'avg': 10.4, 'min': 10.0, 'max': 11.0, 'p95': 11.0}`
- Detector FPS avg/min/max: `{'avg': 8.2, 'min': 7.0, 'max': 9.0, 'p95': 9.0}`
- Drop ratio avg/max: `{'avg': 0.04, 'min': 0.0, 'max': 0.05, 'p95': 0.05}`
- Publish backlog avg/max: `{'avg': 0.0, 'min': 0.0, 'max': 0.0, 'p95': 0.0}`

## Resources
- CPU avg/max: `{'avg': 54.81, 'min': 49.0, 'max': 62.9, 'p95': 57.8}`
- RAM avg/max: `{'avg': 1347.49, 'min': 1324.81, 'max': 1386.69, 'p95': 1382.97}`
- Temperature avg/max: `{'avg': 82.86, 'min': 81.5, 'max': 83.7, 'p95': 83.7}`

## Timings
- camera_read_ms: `{'avg': 99.84, 'min': 98.56, 'max': 100.17, 'p95': 100.15}`
- capture_to_service_ms: `{'avg': 14.06, 'min': 1.16, 'max': 19.78, 'p95': 19.45}`
- detector_preprocess_ms: `{'avg': 2.5, 'min': 2.41, 'max': 3.0, 'p95': 2.6}`
- detector_inference_ms: `{'avg': 59.77, 'min': 57.78, 'max': 61.9, 'p95': 61.34}`
- detector_postprocess_ms: `{'avg': 1.75, 'min': 1.67, 'max': 2.01, 'p95': 1.88}`
- detector_total_ms: `{'avg': 64.03, 'min': 61.95, 'max': 66.33, 'p95': 65.54}`
- filter_ms: `{'avg': 0.02, 'min': 0.02, 'max': 0.02, 'p95': 0.02}`
- tracking_ms: `{'avg': 0.02, 'min': 0.02, 'max': 0.02, 'p95': 0.02}`
- crossing_ms: `{'avg': 0.0, 'min': 0.0, 'max': 0.01, 'p95': 0.0}`
- event_enqueue_ms: `{'avg': 0.0, 'min': 0.0, 'max': 0.0, 'p95': 0.0}`
- process_camera_total_ms: `{'avg': 64.77, 'min': 62.67, 'max': 66.99, 'p95': 66.31}`
- sse_publish_ms: `{'avg': 0.03, 'min': 0.03, 'max': 0.03, 'p95': 0.03}`