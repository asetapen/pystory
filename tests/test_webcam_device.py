"""--webcam-device must actually reach cv2.VideoCapture.

Both `take_webcam_picture` and `capture_and_enroll` used to hardcode
`cv2.VideoCapture(0)`, so with more than one camera attached (e.g. a laptop's
built-in camera plus an external OBSBOT), pystory always opened whichever one
the OS enumerates first -- there was no way to point it at the other one.

`camera_device` is the argparse `type`: cv2.VideoCapture accepts either an
integer index or a device path (`/dev/video2`), and `int('/dev/video2')`
raises, so only a numeric-looking value is coerced to int.
"""

import pytest

import pystory.capture as capture
import pystory.enroll as enroll
import pystory.main as main
from pystory.config import Config


class DeadCamera:
    """Never returns a frame -- both callers give up on the first read, so
    the only thing worth asserting is what index/path they opened with."""

    def __init__(self):
        self.release_calls = 0

    def read(self):
        return False, None

    def release(self):
        self.release_calls += 1


class RecordingCv2:
    def __init__(self):
        self.opened_with = None

    def VideoCapture(self, device):
        self.opened_with = device
        return DeadCamera()

    def destroyAllWindows(self):
        pass


@pytest.mark.parametrize("raw,expected", [("2", 2), ("/dev/video2", "/dev/video2")])
def test_camera_device_parses_index_as_int_and_path_as_str(raw, expected):
    assert main.camera_device(raw) == expected


def test_webcam_device_defaults_to_zero(monkeypatch):
    monkeypatch.setattr("sys.argv", ["pystory"])

    config = main.parse_args()

    assert config.webcam_device == 0


@pytest.mark.parametrize("raw,expected", [("2", 2), ("/dev/video2", "/dev/video2")])
def test_webcam_device_flag_sets_the_field(monkeypatch, raw, expected):
    monkeypatch.setattr("sys.argv", ["pystory", "--webcam-device", raw])

    config = main.parse_args()

    assert config.webcam_device == expected


def test_take_webcam_picture_opens_the_configured_device(monkeypatch, tmp_path):
    fake_cv2 = RecordingCv2()
    monkeypatch.setattr(capture, "cv2", fake_cv2)
    config = Config(storage_dir=tmp_path, webcam_device="/dev/video2")

    capture.take_webcam_picture("20260101_000000", config)

    assert fake_cv2.opened_with == "/dev/video2"


def test_capture_and_enroll_opens_the_configured_device(monkeypatch, tmp_path):
    fake_cv2 = RecordingCv2()
    monkeypatch.setattr(enroll, "cv2", fake_cv2)
    config = Config(storage_dir=tmp_path, webcam_device=3)

    enroll.capture_and_enroll(config, num_samples=2)

    assert fake_cv2.opened_with == 3
