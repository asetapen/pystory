"""`pystory-enroll --reset` must not delete before it captures (issue st-8313af).

`main()` used to unlink the encodings file and only THEN call
`capture_and_enroll`, so a dead camera, an ESC, or `--samples 0` left the file
deleted at exit 0 with no error -- and post-st-5ca1n6, an empty enrollment set
makes `main.tick` fall back to detecting ANY face, so a wiped enrollment is now
a silent security downgrade rather than the loud lockout it used to be.

The fix moves the delete out of `main()` entirely: `capture_and_enroll` takes a
`reset` flag and only replaces the old encodings once a new set has actually
been captured, so a run that captures nothing leaves the previous enrollment
on disk untouched. `--samples` is also bounded at 1, since an unbounded
`--samples 0` was the other route to the same pre-delete.

`test_r1`/`test_r2`/`test_r5` drive the real `main()` end to end -- the defect
lived in the ORDER two calls inside `main()` ran in, so a test that calls
`capture_and_enroll` directly (which never had the delete) could not see it.
`test_r3`/`test_r4` unit-test the replace-vs-append semantics `reset` gives
`capture_and_enroll` once inside it. What is doubled throughout is the
third-party boundary only (`cv2.VideoCapture` and the loop's other `cv2`
calls, plus `encode_face`, which needs a real dlib model to return anything);
`load_encodings`/`save_encodings` run for real against `tmp_path` so the
on-disk file is the thing actually asserted on.
"""

import numpy as np
import pytest

import pystory.enroll as enroll
import pystory.recognition as recognition
from pystory.config import Config

FRAME = np.zeros((4, 4, 3), dtype=np.uint8)
EXISTING = [[1.0] * 128, [2.0] * 128]
NEW = np.array([9.0] * 128)


class FakeCamera:
    """`read()` replays the given (ret, frame) pairs, then reports a dead feed --
    the exhausted-queue default matters, since a test that only stubs the
    first frame must not hang if `capture_and_enroll` reads again."""

    def __init__(self, reads=()):
        self._reads = list(reads)
        self.release_calls = 0

    def read(self):
        if self._reads:
            return self._reads.pop(0)
        return (False, None)

    def release(self):
        self.release_calls += 1


class FakeCv2:
    FONT_HERSHEY_SIMPLEX = 0

    def __init__(self, camera, keys=()):
        self._camera = camera
        self._keys = list(keys)
        self.destroy_calls = 0

    def VideoCapture(self, index):
        return self._camera

    def putText(self, *args, **kwargs):
        pass

    def imshow(self, *args, **kwargs):
        pass

    def waitKey(self, delay):
        return self._keys.pop(0) if self._keys else 255

    def destroyAllWindows(self):
        self.destroy_calls += 1


def seed(config):
    """Write an existing enrollment, the way a real prior run would."""
    recognition.save_encodings([np.array(e) for e in EXISTING], config)


def install(monkeypatch, reads=(), keys=(), encoding=NEW):
    camera = FakeCamera(reads)
    fake_cv2 = FakeCv2(camera, keys)
    monkeypatch.setattr(enroll, "cv2", fake_cv2)
    monkeypatch.setattr(enroll, "encode_face", lambda frame: encoding)
    return camera, fake_cv2


def run_main(monkeypatch, tmp_path, argv, reads=(), keys=(), encoding=NEW):
    install(monkeypatch, reads, keys, encoding)
    monkeypatch.setattr("sys.argv", ["pystory-enroll", "--storage-dir", str(tmp_path), *argv])
    enroll.main()


# ---------------------------------------------------------------------------
# The defect: a failed/cancelled --reset must not touch the old enrollment
# ---------------------------------------------------------------------------

def test_r1_dead_camera_with_reset_leaves_existing_enrollment(monkeypatch, tmp_path):
    """THE DEFECT. A camera that never reads a frame must not wipe the file."""
    config = Config(storage_dir=tmp_path)
    seed(config)

    run_main(monkeypatch, tmp_path, ["--reset", "--samples", "2"], reads=[])

    loaded = recognition.load_encodings(config)
    assert len(loaded) == 2, "the pre-existing enrollment must survive a failed reset"


def test_r2_esc_with_reset_leaves_existing_enrollment(monkeypatch, tmp_path, capsys):
    """R2 from the filed row: ESC prints 'Cancelled.' AFTER the old unlink had
    already happened, so the one message the user got asserted a no-op that was
    actually destructive. The fix must make that message true."""
    config = Config(storage_dir=tmp_path)
    seed(config)

    run_main(monkeypatch, tmp_path, ["--reset", "--samples", "2"], reads=[(True, FRAME)], keys=[27])

    assert "Cancelled." in capsys.readouterr().out
    loaded = recognition.load_encodings(config)
    assert len(loaded) == 2


def test_r5_zero_samples_with_reset_is_refused_and_leaves_existing_enrollment(monkeypatch, tmp_path):
    """`--reset --samples 0` used to be the (undocumented) way to wipe an
    enrollment via the pre-delete, with the camera never even opened. The fix
    refuses `--samples 0` by name instead of letting it reach the field."""
    config = Config(storage_dir=tmp_path)
    seed(config)

    with pytest.raises(SystemExit) as exit_info:
        run_main(monkeypatch, tmp_path, ["--reset", "--samples", "0"], reads=[])

    assert exit_info.value.code == 2
    assert len(recognition.load_encodings(config)) == 2


# ---------------------------------------------------------------------------
# Reset must still work once capture actually succeeds
# ---------------------------------------------------------------------------

def test_r3_successful_reset_replaces_rather_than_appends(monkeypatch, tmp_path, capsys):
    """A successful --reset run must still discard the old set -- it is a
    replace, not an accidental append once the pre-delete is gone."""
    config = Config(storage_dir=tmp_path)
    seed(config)
    install(monkeypatch, reads=[(True, FRAME), (True, FRAME)])

    added = enroll.capture_and_enroll(config, num_samples=2, auto_delay=0.0, reset=True)

    assert added == 2
    loaded = recognition.load_encodings(config)
    assert len(loaded) == 2, "the old 2 must be GONE, not 4 (2 old + 2 new)"
    assert all(np.array_equal(e, NEW) for e in loaded)
    assert "Cleared previous enrollment" in capsys.readouterr().out


def test_r4_control_without_reset_appends_to_existing(monkeypatch, tmp_path):
    """CONTROL. Without this, a fix that always replaces would pass r3 while
    breaking the ordinary top-up case this file never asked to fix."""
    config = Config(storage_dir=tmp_path)
    seed(config)
    install(monkeypatch, reads=[(True, FRAME), (True, FRAME)])

    added = enroll.capture_and_enroll(config, num_samples=2, auto_delay=0.0, reset=False)

    assert added == 2
    assert len(recognition.load_encodings(config)) == 4


# ---------------------------------------------------------------------------
# --samples must refuse an unworkable value by name, not reach the field
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("value", ["0", "-1"])
def test_samples_unworkable_value_is_refused(monkeypatch, capsys, value):
    monkeypatch.setattr("sys.argv", ["pystory-enroll", "--samples", value])

    with pytest.raises(SystemExit) as exit_info:
        enroll.parse_args()

    assert exit_info.value.code == 2
    stderr = capsys.readouterr().err
    assert "--samples" in stderr
    assert value in stderr


def test_samples_default_is_unaffected(monkeypatch):
    monkeypatch.setattr("sys.argv", ["pystory-enroll"])

    args = enroll.parse_args()

    assert args.samples == 8
