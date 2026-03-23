import time

import cv2
import numpy as np

from entrance_monitor.camera import CameraSource
from entrance_monitor.config import load_settings


def test_camera_video_source_emits_packets(tmp_path):
    video_path = tmp_path / "entrance-test.avi"
    writer = cv2.VideoWriter(
        str(video_path),
        cv2.VideoWriter_fourcc(*"MJPG"),
        12.0,
        (320, 240),
    )
    assert writer.isOpened()
    for value in (40, 120, 200):
        frame = np.full((240, 320, 3), value, dtype=np.uint8)
        writer.write(frame)
    writer.release()

    settings = load_settings("config/default.yaml")
    settings.camera.source = str(video_path)
    settings.camera.width = 640
    settings.camera.height = 480
    settings.camera.roi.x1 = 40
    settings.camera.roi.y1 = 30
    settings.camera.roi.x2 = 600
    settings.camera.roi.y2 = 440

    camera = CameraSource(settings.camera)
    camera.start()
    try:
        deadline = time.time() + 3
        packet = None
        while time.time() < deadline:
            packet = camera.latest()
            if packet is not None and packet.frame_id >= 2:
                break
            time.sleep(0.05)
        assert packet is not None
        assert packet.width == 640
        assert packet.height == 480
        assert packet.roi_width == 560
        assert packet.roi_height == 410
        assert camera.stats.expected_fps == 12.0
    finally:
        camera.stop()
