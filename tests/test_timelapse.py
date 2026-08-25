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


# ---------------------------------------------------------------------------
# THE DEFECT (issue st-8gpxr8, D1): a writer that could not open must not be
# reported as a success. `build_timelapse` never checked
# `VideoWriter.isOpened()`, so it logged "Wrote <path> ..." and returned
# normally even when no file existed at all.
# ---------------------------------------------------------------------------

def test_build_timelapse_unopenable_writer_does_not_report_success(tmp_path, caplog):
    """fps=0 is one of two ordinary ways cv2.VideoWriter refuses to open (the
    other is a missing parent directory, covered below). No file must be
    created and the failure must be logged, not silently swallowed."""
    frame = tmp_path / "webcam_1.jpg"
    _write_jpg(frame)
    output = tmp_path / "out.mp4"

    with caplog.at_level("ERROR"):
        build_timelapse([frame], output, fps=0, resolution=None)

    assert not output.exists()
    assert any("Could not open" in r.message for r in caplog.records)
    assert not any("Wrote" in r.message for r in caplog.records), \
        "a writer that never opened must not be reported as written"


def test_build_timelapse_creates_missing_parent_directory(tmp_path):
    """The other D1 trigger: an --output whose parent does not exist yet.
    capture.py's own convention (`_compress_and_save`) is to mkdir the parent
    before saving; build_timelapse must do the same rather than fail to open."""
    frame = tmp_path / "webcam_1.jpg"
    _write_jpg(frame)
    output = tmp_path / "videos" / "out.mp4"
    assert not output.parent.exists()

    build_timelapse([frame], output, fps=30, resolution=None)

    assert output.exists()
    assert output.stat().st_size > 0


def test_build_timelapse_control_valid_write_still_logs_wrote(tmp_path, caplog):
    """CONTROL. Without this, a fix that never reports success at all would
    also pass the two failure arms above."""
    frame = tmp_path / "webcam_1.jpg"
    _write_jpg(frame)
    output = tmp_path / "out.mp4"

    with caplog.at_level("INFO"):
        build_timelapse([frame], output, fps=30, resolution=None)

    assert output.exists()
    assert any("Wrote" in r.message for r in caplog.records)
