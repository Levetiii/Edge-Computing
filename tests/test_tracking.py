from datetime import timedelta

from entrance_monitor.models import BoundingBox, CrossingDirection, Detection, TrackObservation
from entrance_monitor.tracking import CentroidTracker, LineCrossingCounter
from entrance_monitor.utils import utc_now


def test_line_crossing_emits_event():
    tracker = CentroidTracker(max_distance=500.0, max_misses=5)
    counter = LineCrossingCounter(
        line=(50, 0, 50, 100),
        cooldown_seconds=0.1,
        hysteresis_px=8.0,
        min_track_hits=1,
        confirm_frames=1,
    )
    now = utc_now()

    det_a = [Detection(bbox=BoundingBox(x1=10, y1=10, x2=30, y2=60))]
    obs_a = tracker.update(det_a, now)
    assert counter.update(obs_a, now) == []

    det_b = [Detection(bbox=BoundingBox(x1=70, y1=10, x2=90, y2=60))]
    later = now + timedelta(seconds=1)
    obs_b = tracker.update(det_b, later)
    events = counter.update(obs_b, later)
    assert len(events) == 1


def test_tracker_keeps_same_id_for_nearby_detections():
    tracker = CentroidTracker(max_distance=100.0, max_misses=5)
    now = utc_now()
    obs_a = tracker.update(
        [Detection(bbox=BoundingBox(x1=10, y1=10, x2=30, y2=40))],
        now,
    )
    obs_b = tracker.update(
        [Detection(bbox=BoundingBox(x1=14, y1=12, x2=34, y2=42))],
        now + timedelta(milliseconds=100),
    )
    assert obs_a[0].track_id == obs_b[0].track_id


def test_tracker_preserves_ids_when_detection_order_flips():
    tracker = CentroidTracker(max_distance=120.0, max_misses=5)
    now = utc_now()
    first_pass = tracker.update(
        [
            Detection(bbox=BoundingBox(x1=10, y1=10, x2=40, y2=70)),
            Detection(bbox=BoundingBox(x1=80, y1=12, x2=110, y2=72)),
        ],
        now,
    )
    second_pass = tracker.update(
        [
            Detection(bbox=BoundingBox(x1=84, y1=12, x2=114, y2=72)),
            Detection(bbox=BoundingBox(x1=14, y1=10, x2=44, y2=70)),
        ],
        now + timedelta(milliseconds=100),
    )

    first_centroids = {round(obs.centroid_x): obs.track_id for obs in first_pass}
    second_centroids = {round(obs.centroid_x): obs.track_id for obs in second_pass}

    assert first_centroids[25] == second_centroids[29]
    assert first_centroids[95] == second_centroids[99]


def test_line_crossing_hysteresis_prevents_double_count_on_jitter():
    counter = LineCrossingCounter(
        line=(50, 0, 50, 100),
        cooldown_seconds=0.1,
        hysteresis_px=8.0,
        min_track_hits=1,
        confirm_frames=2,
    )
    now = utc_now()

    observations = [
        TrackObservation(track_id=1, bbox=BoundingBox(x1=10, y1=10, x2=30, y2=60), centroid_x=20, centroid_y=35, hit_count=3),
        TrackObservation(track_id=1, bbox=BoundingBox(x1=38, y1=10, x2=58, y2=60), centroid_x=48, centroid_y=35, hit_count=4),
        TrackObservation(track_id=1, bbox=BoundingBox(x1=42, y1=10, x2=62, y2=60), centroid_x=52, centroid_y=35, hit_count=5),
        TrackObservation(track_id=1, bbox=BoundingBox(x1=60, y1=10, x2=80, y2=60), centroid_x=70, centroid_y=35, hit_count=6),
        TrackObservation(track_id=1, bbox=BoundingBox(x1=43, y1=10, x2=63, y2=60), centroid_x=53, centroid_y=35, hit_count=7),
        TrackObservation(track_id=1, bbox=BoundingBox(x1=61, y1=10, x2=81, y2=60), centroid_x=71, centroid_y=35, hit_count=8),
    ]

    events = []
    for index, obs in enumerate(observations):
        events.extend(counter.update([obs], now + timedelta(milliseconds=250 * index)))

    assert len(events) == 1
    assert events[0].direction.value == "EXIT"


def test_line_crossing_requires_confirmed_frames_on_far_side():
    counter = LineCrossingCounter(
        line=(50, 0, 50, 100),
        cooldown_seconds=0.1,
        hysteresis_px=8.0,
        min_track_hits=1,
        confirm_frames=2,
    )
    now = utc_now()
    first = TrackObservation(
        track_id=4,
        bbox=BoundingBox(x1=10, y1=10, x2=30, y2=60),
        centroid_x=20,
        centroid_y=35,
        hit_count=3,
    )
    second = TrackObservation(
        track_id=4,
        bbox=BoundingBox(x1=60, y1=10, x2=80, y2=60),
        centroid_x=70,
        centroid_y=35,
        hit_count=4,
    )
    third = TrackObservation(
        track_id=4,
        bbox=BoundingBox(x1=62, y1=10, x2=82, y2=60),
        centroid_x=72,
        centroid_y=35,
        hit_count=5,
    )

    assert counter.update([first], now) == []
    assert counter.update([second], now + timedelta(milliseconds=250)) == []
    events = counter.update([third], now + timedelta(milliseconds=500))
    assert len(events) == 1


def test_reversing_line_endpoints_flips_crossing_direction():
    now = utc_now()
    left = TrackObservation(
        track_id=11,
        bbox=BoundingBox(x1=10, y1=10, x2=30, y2=60),
        centroid_x=20,
        centroid_y=35,
        hit_count=2,
    )
    right = TrackObservation(
        track_id=11,
        bbox=BoundingBox(x1=60, y1=10, x2=80, y2=60),
        centroid_x=70,
        centroid_y=35,
        hit_count=3,
    )

    forward_counter = LineCrossingCounter(
        line=(50, 0, 50, 100),
        cooldown_seconds=0.1,
        hysteresis_px=8.0,
        min_track_hits=1,
        confirm_frames=1,
    )
    reverse_counter = LineCrossingCounter(
        line=(50, 100, 50, 0),
        cooldown_seconds=0.1,
        hysteresis_px=8.0,
        min_track_hits=1,
        confirm_frames=1,
    )

    assert forward_counter.update([left], now) == []
    assert reverse_counter.update([left], now) == []
    forward_events = forward_counter.update([right], now + timedelta(seconds=1))
    reverse_events = reverse_counter.update([right], now + timedelta(seconds=1))

    assert len(forward_events) == 1
    assert len(reverse_events) == 1
    assert forward_events[0].direction == CrossingDirection.EXIT
    assert reverse_events[0].direction == CrossingDirection.ENTRY
