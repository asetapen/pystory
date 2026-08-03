import cv2
import numpy as np

from pystory.timelapse import build_timelapse


def _write_jpg(path, width=8, height=8):
    frame = np.zeros((height, width, 3), dtype=np.uint8)
    cv2.imwrite(str(path), frame)


def test_build_timelapse_empty_images_does_not_create_output(tmp_path):
    output = tmp_path / "out.mp4"

    build_timelapse([], output, fps=30, resolution=None)

    assert not output.exists()


def test_build_timelapse_unreadable_first_frame_does_not_create_output(tmp_path):
    bad = tmp_path / "webcam_bad.jpg"
    bad.write_bytes(b"not a real jpg")
    output = tmp_path / "out.mp4"

    build_timelapse([bad], output, fps=30, resolution=None)

    assert not output.exists()


def test_build_timelapse_skips_unreadable_frame_after_first(tmp_path):
    good1 = tmp_path / "webcam_1.jpg"
    bad = tmp_path / "webcam_2.jpg"
    good2 = tmp_path / "webcam_3.jpg"
    _write_jpg(good1)
    bad.write_bytes(b"not a real jpg")
    _write_jpg(good2)
    output = tmp_path / "out.mp4"

    build_timelapse([good1, bad, good2], output, fps=30, resolution=None)

    assert output.exists()
    assert output.stat().st_size > 0


def test_build_timelapse_writes_video_with_explicit_resolution(tmp_path):
    frame = tmp_path / "webcam_1.jpg"
    _write_jpg(frame, width=16, height=16)
    output = tmp_path / "out.mp4"

    build_timelapse([frame], output, fps=10, resolution=(4, 4))

    assert output.exists()
    assert output.stat().st_size > 0
