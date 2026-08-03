import os
import time

from pystory.config import Config
from pystory.storage import get_storage_size_mb, prune_old_files


def _make_jpg(storage_dir, name, size_bytes, mtime_offset=0):
    path = storage_dir / name
    path.write_bytes(b"\x00" * size_bytes)
    if mtime_offset:
        now = time.time()
        os.utime(path, (now + mtime_offset, now + mtime_offset))
    return path


def test_get_storage_size_mb_empty_dir(tmp_path):
    config = Config(storage_dir=tmp_path)
    assert get_storage_size_mb(config) == 0


def test_get_storage_size_mb_sums_only_jpgs(tmp_path):
    config = Config(storage_dir=tmp_path)
    _make_jpg(tmp_path, "webcam_1.jpg", 1024 * 1024)
    _make_jpg(tmp_path, "webcam_2.jpg", 1024 * 1024)
    (tmp_path / "notes.txt").write_bytes(b"\x00" * 1024 * 1024)

    assert get_storage_size_mb(config) == 2.0


def test_prune_old_files_noop_when_under_limit(tmp_path):
    config = Config(storage_dir=tmp_path, max_history_mb=10)
    _make_jpg(tmp_path, "webcam_1.jpg", 1024 * 1024)

    deleted = prune_old_files(config)

    assert deleted == 0
    assert (tmp_path / "webcam_1.jpg").exists()


def test_prune_old_files_deletes_oldest_first(tmp_path):
    config = Config(storage_dir=tmp_path, max_history_mb=2)
    _make_jpg(tmp_path, "webcam_old.jpg", 1024 * 1024, mtime_offset=-100)
    _make_jpg(tmp_path, "webcam_mid.jpg", 1024 * 1024, mtime_offset=-50)
    _make_jpg(tmp_path, "webcam_new.jpg", 1024 * 1024, mtime_offset=0)

    deleted = prune_old_files(config)

    assert deleted == 1
    assert not (tmp_path / "webcam_old.jpg").exists()
    assert (tmp_path / "webcam_mid.jpg").exists()
    assert (tmp_path / "webcam_new.jpg").exists()


def test_prune_old_files_deletes_until_under_limit(tmp_path):
    config = Config(storage_dir=tmp_path, max_history_mb=1)
    for i in range(5):
        _make_jpg(tmp_path, f"webcam_{i}.jpg", 1024 * 1024, mtime_offset=-i)

    deleted = prune_old_files(config)

    assert deleted == 4
    assert get_storage_size_mb(config) <= 1
    remaining = sorted(tmp_path.glob("*.jpg"))
    assert len(remaining) == 1
    assert remaining[0].name == "webcam_0.jpg"


def test_prune_old_files_stops_if_no_files_left(tmp_path):
    config = Config(storage_dir=tmp_path, max_history_mb=0)

    deleted = prune_old_files(config)

    assert deleted == 0
