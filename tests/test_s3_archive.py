import os
import time

from pystory.s3_archive import find_archivable


def _touch_with_age(path, age_seconds):
    path.write_bytes(b"x")
    old_time = time.time() - age_seconds
    os.utime(path, (old_time, old_time))


def test_finds_only_files_older_than_min_age(tmp_path):
    old = tmp_path / "screenshot_20260101_000000.jpg"
    new = tmp_path / "webcam_20260101_000001.jpg"
    _touch_with_age(old, age_seconds=1000)
    _touch_with_age(new, age_seconds=10)

    found = find_archivable(tmp_path, min_age_seconds=600)

    assert found == [old]


def test_ignores_non_capture_files(tmp_path):
    unrelated = tmp_path / "face_encodings.json"
    _touch_with_age(unrelated, age_seconds=10_000)

    found = find_archivable(tmp_path, min_age_seconds=0)

    assert found == []
