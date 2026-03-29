import importlib.util
from pathlib import Path


_SPEC = importlib.util.spec_from_file_location(
    "paso_benchmark",
    Path("scripts/paso_benchmark.py"),
)
assert _SPEC is not None and _SPEC.loader is not None
paso_benchmark = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(paso_benchmark)


def test_is_duplicate_sample_matches_repeated_status_timestamp():
    previous = {"ts": "2026-03-29T02:24:22.425468Z", "delivered_fps": 10.0}
    current = {"ts": "2026-03-29T02:24:22.425468Z", "delivered_fps": 10.0}
    assert paso_benchmark.is_duplicate_sample(previous, current) is True


def test_is_duplicate_sample_allows_newer_status_timestamp():
    previous = {"ts": "2026-03-29T02:24:22.425468Z", "delivered_fps": 10.0}
    current = {"ts": "2026-03-29T02:24:23.488523Z", "delivered_fps": 10.0}
    assert paso_benchmark.is_duplicate_sample(previous, current) is False


def test_is_duplicate_sample_falls_back_to_full_payload_when_timestamp_missing():
    previous = {"ts": None, "delivered_fps": 10.0, "detector_fps": 7.0}
    current = {"ts": None, "delivered_fps": 10.0, "detector_fps": 7.0}
    assert paso_benchmark.is_duplicate_sample(previous, current) is True
