"""--webcam-device must actually reach cv2.VideoCapture.

Both `take_webcam_picture` and `capture_and_enroll` used to hardcode
`cv2.VideoCapture(0)`, so with more than one camera attached (e.g. a laptop's
built-in camera plus an external OBSBOT), pystory always opened whichever one
the OS enumerates first -- there was no way to point it at the other one.

`camera_device` is the argparse `type`: cv2.VideoCapture accepts either an
integer index or a device path (`/dev/video2`), and `int('/dev/video2')`
raises, so only a numeric-looking value is coerced to int.
"""

import cv2
import numpy as np
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
        self.props = {}

    def set(self, prop, value):
        self.props[prop] = value
        return True

    def read(self):
        return False, None

    def release(self):
        self.release_calls += 1


class RecordingCv2:
    """Stands in for the `cv2` module in capture.py and enroll.py. The property
    constants are the real ones, so a recorded `set` can be checked against cv2."""

    CAP_PROP_FOURCC = cv2.CAP_PROP_FOURCC
    CAP_PROP_FRAME_WIDTH = cv2.CAP_PROP_FRAME_WIDTH
    CAP_PROP_FRAME_HEIGHT = cv2.CAP_PROP_FRAME_HEIGHT
    VideoWriter_fourcc = staticmethod(cv2.VideoWriter_fourcc)

    def __init__(self, camera=None):
        self.opened_with = None
        self.opened_api = None
        self.camera = camera if camera is not None else DeadCamera()

    def VideoCapture(self, device, api=None):
        self.opened_with = device
        self.opened_api = api
        return self.camera

    def destroyAllWindows(self):
        pass


def patch_cv2(monkeypatch, fake):
    # capture_and_enroll opens through capture.open_webcam, so both modules'
    # `cv2` must be the fake or the test would open the real camera.
    monkeypatch.setattr(capture, "cv2", fake)
    monkeypatch.setattr(enroll, "cv2", fake)


@pytest.mark.parametrize("raw,expected", [("2", 2), ("/dev/video2", "/dev/video2")])
def test_camera_device_parses_index_as_int_and_path_as_str(raw, expected):
    assert main.camera_device(raw) == expected


def test_webcam_device_defaults_to_auto(monkeypatch):
    monkeypatch.setattr("sys.argv", ["pystory"])

    config = main.parse_args()

    assert config.webcam_device == "auto"


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
    patch_cv2(monkeypatch, fake_cv2)
    config = Config(storage_dir=tmp_path, webcam_device=3)

    enroll.capture_and_enroll(config, num_samples=2)

    assert fake_cv2.opened_with == 3


# --- "auto": prefer an attached OBSBOT, else index 0 ------------------------
#
# The by-id names below are the real ones from a laptop with an OBSBOT Tiny 2
# Lite attached. `-index1` is the metadata node (no frames), so picking it would
# be a camera that never delivers, which the camera-failure path then turns
# into a lock.

OBSBOT_INDEX0 = "usb-Remo_Tech_Co.__Ltd._OBSBOT_Tiny_2_Lite-video-index0"
OBSBOT_INDEX1 = "usb-Remo_Tech_Co.__Ltd._OBSBOT_Tiny_2_Lite-video-index1"
BUILTIN_INDEX0 = "usb-VN0610HY8LN0058LAK5DA00_Integrated_Webcam_FHD_200901010001-video-index0"
BUILTIN_INDEX1 = "usb-VN0610HY8LN0058LAK5DA00_Integrated_Webcam_FHD_200901010001-video-index1"


def make_by_id(tmp_path, links):
    """Build a fake /dev/v4l/by-id: each name is a symlink to its own fake node."""
    dev = tmp_path / "dev"
    by_id = dev / "v4l" / "by-id"
    by_id.mkdir(parents=True)
    for name, node in links.items():
        (dev / node).touch()
        (by_id / name).symlink_to(dev / node)
    return dev, by_id


def test_auto_picks_the_obsbot_capture_node(tmp_path):
    dev, by_id = make_by_id(tmp_path, {
        BUILTIN_INDEX0: "video0", BUILTIN_INDEX1: "video1",
        OBSBOT_INDEX0: "video3", OBSBOT_INDEX1: "video4",
    })

    assert capture.resolve_webcam_device("auto", by_id) == str(dev / "video3")


def test_auto_falls_back_to_zero_without_an_obsbot(tmp_path):
    _, by_id = make_by_id(tmp_path, {BUILTIN_INDEX0: "video0", BUILTIN_INDEX1: "video1"})

    assert capture.resolve_webcam_device("auto", by_id) == 0


def test_auto_never_picks_the_obsbot_metadata_node(tmp_path):
    # Sorting alone would put index0 first, so this arm is what binds the
    # suffix check: with only the metadata node present, auto must not open it.
    _, by_id = make_by_id(tmp_path, {BUILTIN_INDEX0: "video0", OBSBOT_INDEX1: "video4"})

    assert capture.resolve_webcam_device("auto", by_id) == 0


def test_auto_falls_back_to_zero_when_by_id_is_missing(tmp_path):
    # No USB video device at all: udev does not create the directory.
    assert capture.resolve_webcam_device("auto", tmp_path / "absent") == 0


@pytest.mark.parametrize("explicit", [0, 2, "/dev/video42"])
def test_explicit_device_is_never_overridden_by_auto(tmp_path, explicit):
    _, by_id = make_by_id(tmp_path, {OBSBOT_INDEX0: "video3"})

    assert capture.resolve_webcam_device(explicit, by_id) == explicit


def test_take_webcam_picture_opens_the_obsbot_by_default(monkeypatch, tmp_path):
    dev, by_id = make_by_id(tmp_path, {BUILTIN_INDEX0: "video0", OBSBOT_INDEX0: "video3"})
    monkeypatch.setattr(capture.resolve_webcam_device, "__defaults__", (by_id,))
    fake_cv2 = RecordingCv2()
    monkeypatch.setattr(capture, "cv2", fake_cv2)

    capture.take_webcam_picture("20260101_000000", Config(storage_dir=tmp_path))

    assert fake_cv2.opened_with == str(dev / "video3")


def test_capture_and_enroll_opens_the_obsbot_by_default(monkeypatch, tmp_path):
    dev, by_id = make_by_id(tmp_path, {BUILTIN_INDEX0: "video0", OBSBOT_INDEX0: "video3"})
    monkeypatch.setattr(capture.resolve_webcam_device, "__defaults__", (by_id,))
    fake_cv2 = RecordingCv2()
    patch_cv2(monkeypatch, fake_cv2)

    enroll.capture_and_enroll(Config(storage_dir=tmp_path), num_samples=2)

    assert fake_cv2.opened_with == str(dev / "video3")


# --- the backend ------------------------------------------------------------
#
# Bound at the call sites because the failure is the backend OpenCV CHOOSES:
# with no API preference a path goes to FFMPEG, whose reads fail on the OBSBOT.
# A unit test cannot reproduce that without the camera, so this binds that both
# callers ask for V4L2 rather than the hardware behaviour itself.

@pytest.mark.parametrize("device", ["/dev/video3", 0])
def test_take_webcam_picture_opens_through_v4l2(monkeypatch, tmp_path, device):
    fake_cv2 = RecordingCv2()
    monkeypatch.setattr(capture, "cv2", fake_cv2)

    capture.take_webcam_picture("20260101_000000", Config(storage_dir=tmp_path, webcam_device=device))

    assert fake_cv2.opened_api == cv2.CAP_V4L2


@pytest.mark.parametrize("device", ["/dev/video3", 0])
def test_capture_and_enroll_opens_through_v4l2(monkeypatch, tmp_path, device):
    fake_cv2 = RecordingCv2()
    patch_cv2(monkeypatch, fake_cv2)

    enroll.capture_and_enroll(Config(storage_dir=tmp_path, webcam_device=device), num_samples=2)

    assert fake_cv2.opened_api == cv2.CAP_V4L2


# --- warm-up ----------------------------------------------------------------
#
# The real camera's first frames are dark (see take_webcam_picture), so the
# frame that is saved and returned must be the one AFTER the warm-up frames.

class CountingCamera(DeadCamera):
    """Frame i is the integer i, so the returned frame says which read it was."""

    def __init__(self, fail_at=None):
        super().__init__()
        self.reads = 0
        self.fail_at = fail_at

    def read(self):
        i = self.reads
        self.reads += 1
        if i == self.fail_at:
            return False, None
        return True, np.full((4, 4, 3), i, dtype=np.uint8)



def open_counting(monkeypatch, camera):
    monkeypatch.setattr(capture, "cv2", RecordingCv2(camera))
    monkeypatch.setattr(capture, "Image", type("I", (), {"fromarray": staticmethod(lambda a: None)}))
    monkeypatch.setattr(capture, "_compress_and_save", lambda img, path, config: None)


@pytest.mark.parametrize("warmup", [0, 1, 10])
def test_take_webcam_picture_returns_the_frame_after_the_warmup(monkeypatch, tmp_path, warmup):
    camera = CountingCamera()
    open_counting(monkeypatch, camera)
    monkeypatch.setattr(capture.cv2, "cvtColor", lambda f, code: f, raising=False)
    monkeypatch.setattr(capture.cv2, "COLOR_BGR2RGB", 0, raising=False)

    path, frame = capture.take_webcam_picture("t", Config(storage_dir=tmp_path, webcam_warmup_frames=warmup))

    assert path is not None
    assert camera.reads == warmup + 1
    assert int(frame[0, 0, 0]) == warmup


def test_a_failed_read_during_the_warmup_is_no_frame(monkeypatch, tmp_path):
    camera = CountingCamera(fail_at=3)
    open_counting(monkeypatch, camera)

    path, frame = capture.take_webcam_picture("t", Config(storage_dir=tmp_path, webcam_warmup_frames=10))

    assert (path, frame) == (None, None)


def test_webcam_warmup_frames_defaults_to_twenty_and_the_flag_sets_it(monkeypatch):
    monkeypatch.setattr("sys.argv", ["pystory"])
    assert main.parse_args().webcam_warmup_frames == 20
    monkeypatch.setattr("sys.argv", ["pystory", "--webcam-warmup-frames", "0"])
    assert main.parse_args().webcam_warmup_frames == 0


# --- 1080p ------------------------------------------------------------------

def test_take_webcam_picture_requests_1080p_mjpg(monkeypatch, tmp_path):
    fake_cv2 = RecordingCv2()
    monkeypatch.setattr(capture, "cv2", fake_cv2)

    capture.take_webcam_picture("t", Config(storage_dir=tmp_path, webcam_device=0))

    assert fake_cv2.camera.props == {
        cv2.CAP_PROP_FOURCC: cv2.VideoWriter_fourcc(*"MJPG"),
        cv2.CAP_PROP_FRAME_WIDTH: 1920,
        cv2.CAP_PROP_FRAME_HEIGHT: 1080,
    }


def test_capture_and_enroll_requests_1080p(monkeypatch, tmp_path):
    fake_cv2 = RecordingCv2()
    patch_cv2(monkeypatch, fake_cv2)

    enroll.capture_and_enroll(Config(storage_dir=tmp_path, webcam_device=0), num_samples=1)

    assert fake_cv2.camera.props[cv2.CAP_PROP_FRAME_WIDTH] == 1920
    assert fake_cv2.camera.props[cv2.CAP_PROP_FRAME_HEIGHT] == 1080
