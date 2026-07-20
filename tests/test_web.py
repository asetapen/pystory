from pystory.web import list_days, list_ticks_for_day


def _touch(path):
    path.write_bytes(b"x")


def test_list_days_returns_distinct_days_newest_first(tmp_path):
    _touch(tmp_path / "screenshot_20260101_100000.jpg")
    _touch(tmp_path / "webcam_20260101_100000.jpg")
    _touch(tmp_path / "screenshot_20260103_090000.jpg")
    _touch(tmp_path / "screenshot_20260102_120000.jpg")

    assert list_days(tmp_path) == ["20260103", "20260102", "20260101"]


def test_list_days_ignores_non_capture_files(tmp_path):
    _touch(tmp_path / "face_encodings.json")
    _touch(tmp_path / "timelapse_webcam.mp4")

    assert list_days(tmp_path) == []


def test_list_ticks_for_day_pairs_screenshot_and_webcam(tmp_path):
    _touch(tmp_path / "screenshot_20260101_100000.jpg")
    _touch(tmp_path / "webcam_20260101_100000.jpg")

    ticks = list_ticks_for_day(tmp_path, "20260101")

    assert ticks == [{
        "time": "100000",
        "screenshot": "screenshot_20260101_100000.jpg",
        "webcam": "webcam_20260101_100000.jpg",
    }]


def test_list_ticks_for_day_handles_missing_half_of_a_tick(tmp_path):
    _touch(tmp_path / "screenshot_20260101_100000.jpg")

    ticks = list_ticks_for_day(tmp_path, "20260101")

    assert ticks == [{"time": "100000", "screenshot": "screenshot_20260101_100000.jpg"}]


def test_list_ticks_for_day_sorted_and_scoped_to_day(tmp_path):
    _touch(tmp_path / "webcam_20260101_100500.jpg")
    _touch(tmp_path / "webcam_20260101_100000.jpg")
    _touch(tmp_path / "webcam_20260102_090000.jpg")

    ticks = list_ticks_for_day(tmp_path, "20260101")

    assert [t["time"] for t in ticks] == ["100000", "100500"]
