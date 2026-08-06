"""Regression tests for the camera-failure fail-open (issue st-xa1v6h).

Before the fix, `tick()` gated the ENTIRE lock decision on
`webcam_frame is not None`, so a webcam returning no frame meant recognition
was consulted 0 times and the hook fired 0 times, indefinitely, with only a
WARNING logged. These bind `tick()` itself rather than `apply_presence`, because
a direct-call test of the helper stays green no matter what the real call site
does with a missing frame.

Every test asserts `prune_old_files` ran, which is the LAST statement in
`tick()`. "The hook fired 0 times" is also what an exception midway through
`tick()` prints, and that is the reassuring direction, so a zero hook count is
only meaningful alongside evidence the tick ran to completion.
"""

import pystory.main as main
from pystory.config import Config


class Recorder:
    """Counts the calls tick() makes, standing in for the real side effects."""

    def __init__(self, frames):
        # frames: one entry per tick. None = capture failure.
        self._frames = list(frames)
        self.webcam_calls = 0
        self.recognition_calls = 0
        self.detect_calls = 0
        self.hook_calls = 0
        self.prune_calls = 0
        self.unlock_log_calls = 0

    def take_webcam_picture(self, timestamp, config):
        frame = self._frames[self.webcam_calls] if self.webcam_calls < len(self._frames) else None
        self.webcam_calls += 1
        return (None, None) if frame is None else ("webcam.jpg", frame)

    def is_recognized(self, frame, config):
        self.recognition_calls += 1
        # A frame is a truthy sentinel string in these tests; "face" means
        # the enrolled user is present.
        return frame == "face"

    def detect_face(self, frame):
        self.detect_calls += 1
        return frame == "face"

    def run_hook(self, config):
        self.hook_calls += 1

    def prune_old_files(self, config):
        self.prune_calls += 1
        return 0


def install(monkeypatch, frames):
    """Point main.py's collaborators at a Recorder and disable screenshots."""
    rec = Recorder(frames)
    monkeypatch.setattr(main, "take_webcam_picture", rec.take_webcam_picture)
    monkeypatch.setattr(main, "is_recognized", rec.is_recognized)
    monkeypatch.setattr(main, "detect_face", rec.detect_face)
    monkeypatch.setattr(main, "run_hook", rec.run_hook)
    monkeypatch.setattr(main, "prune_old_files", rec.prune_old_files)
    return rec


def make_config(**overrides):
    config = Config(screenshot_enabled=False, **overrides)
    return config


def run_ticks(config, state, n):
    for _ in range(n):
        main.tick(config, state)


# --- the positive control: the instrument CAN print a nonzero hook count ------


def test_control_absent_face_with_a_working_camera_locks(monkeypatch):
    """A working camera and a face absent MUST fire the hook.

    Without this, every zero below is unattributable: a harness that can never
    fire the hook reports fail-open for a correct implementation too.
    """
    rec = install(monkeypatch, ["nobody"] * 4)
    config = make_config(presence_confirm_ticks=2)
    state = main.AppState()
    state.presence.confirm_ticks = config.presence_confirm_ticks

    run_ticks(config, state, 4)

    assert rec.recognition_calls == 4
    assert rec.hook_calls == 1  # fires on the transition only
    assert state.locked is True
    assert rec.prune_calls == 4


def test_control_present_face_with_a_working_camera_does_not_lock(monkeypatch):
    """The other direction: a face PRESENT must not fire the hook at all."""
    rec = install(monkeypatch, ["face"] * 4)
    config = make_config(presence_confirm_ticks=2)
    state = main.AppState()
    state.presence.confirm_ticks = config.presence_confirm_ticks

    run_ticks(config, state, 4)

    assert rec.recognition_calls == 4
    assert rec.hook_calls == 0
    assert state.locked is False
    assert rec.prune_calls == 4


# --- the regression: a sustained camera failure must LOCK --------------------


def test_sustained_camera_failure_locks_the_desk(monkeypatch):
    """THE BUG. Ten frameless ticks used to fire the hook 0 times forever.

    grace=3 + confirm=2 means the 5th consecutive failure locks.
    """
    rec = install(monkeypatch, [None] * 10)
    config = make_config(presence_confirm_ticks=2, camera_failure_grace_ticks=3)
    state = main.AppState()
    state.presence.confirm_ticks = config.presence_confirm_ticks

    run_ticks(config, state, 10)

    assert rec.webcam_calls == 10
    assert rec.recognition_calls == 0  # no frame, so nothing to recognize
    assert rec.hook_calls == 1  # the transition, not once per tick
    assert state.locked is True
    assert state.camera_failure_streak == 10
    # tick() ran to completion every time, so the counts above are real and
    # not the residue of an aborted tick.
    assert rec.prune_calls == 10


def test_camera_failure_locks_on_exactly_the_grace_plus_confirm_tick(monkeypatch):
    """Bind the boundary: grace ticks are tolerated, the next ones count.

    An off-by-one here is invisible in a "does it eventually lock" test, and
    both directions of the off-by-one matter: one tick early means a momentary
    USB reset locks the desk, one late means the grace period is longer than
    documented.
    """
    config = make_config(presence_confirm_ticks=2, camera_failure_grace_ticks=3)

    for ticks, expect_locked in [(3, False), (4, False), (5, True)]:
        rec = install(monkeypatch, [None] * ticks)
        state = main.AppState()
        state.presence.confirm_ticks = config.presence_confirm_ticks

        run_ticks(config, state, ticks)

        assert state.locked is expect_locked, f"{ticks} frameless ticks"
        assert rec.hook_calls == (1 if expect_locked else 0), f"{ticks} frameless ticks"
        assert rec.prune_calls == ticks


def test_a_single_dropped_frame_does_not_lock(monkeypatch):
    """The other safe direction: a momentary hiccup must NOT lock the desk.

    This is the half that makes the grace period load-bearing rather than
    decorative. A fix that simply treats "no frame" as "no face" passes the
    test above and fails this one.
    """
    rec = install(monkeypatch, ["face", "face", None, "face", "face"])
    config = make_config(presence_confirm_ticks=2, camera_failure_grace_ticks=3)
    state = main.AppState()
    state.presence.confirm_ticks = config.presence_confirm_ticks

    run_ticks(config, state, 5)

    assert rec.hook_calls == 0
    assert state.locked is False
    assert rec.prune_calls == 5


def test_a_successful_capture_resets_the_failure_streak(monkeypatch):
    """Three failures, a good frame, three more failures: never past grace.

    Without the reset, failures accumulate across unrelated hiccups and the
    desk locks while the camera is demonstrably working.
    """
    rec = install(monkeypatch, [None, None, None, "face", None, None, None])
    config = make_config(presence_confirm_ticks=2, camera_failure_grace_ticks=3)
    state = main.AppState()
    state.presence.confirm_ticks = config.presence_confirm_ticks

    run_ticks(config, state, 7)

    assert state.camera_failure_streak == 3  # reset by the good frame at tick 4
    assert rec.hook_calls == 0
    assert state.locked is False
    assert rec.prune_calls == 7


def test_recovery_after_a_camera_failure_lock_unlocks(monkeypatch):
    """A camera-failure lock must be recoverable when the camera comes back.

    Otherwise the fix trades a permanent unlock for a permanent lock.
    """
    rec = install(monkeypatch, [None] * 6 + ["face"] * 3)
    config = make_config(presence_confirm_ticks=2, camera_failure_grace_ticks=3)
    state = main.AppState()
    state.presence.confirm_ticks = config.presence_confirm_ticks

    run_ticks(config, state, 9)

    assert rec.hook_calls == 1
    assert state.locked is False  # unlocked again once the face was confirmed
    assert state.camera_failure_streak == 0
    assert rec.prune_calls == 9


# --- the opt-out must actually opt out ---------------------------------------


def test_camera_failure_locks_off_restores_fail_open(monkeypatch):
    """--no-camera-failure-lock is documented as fail-open; bind that.

    A flag whose only effect is a log line reads identical to one that works.
    """
    rec = install(monkeypatch, [None] * 10)
    config = make_config(
        presence_confirm_ticks=2, camera_failure_grace_ticks=3, camera_failure_locks=False
    )
    state = main.AppState()
    state.presence.confirm_ticks = config.presence_confirm_ticks

    run_ticks(config, state, 10)

    assert rec.hook_calls == 0
    assert state.locked is False
    assert state.camera_failure_streak == 10
    assert rec.prune_calls == 10


def test_face_detection_disabled_still_never_locks(monkeypatch):
    """--no-face-detection must remain a full opt-out of the lock decision.

    The fix moves the frame check inside `if config.face_detection_enabled`,
    so this guards against the camera-failure path escaping that gate.
    """
    rec = install(monkeypatch, [None] * 6)
    config = make_config(
        presence_confirm_ticks=2, camera_failure_grace_ticks=3, face_detection_enabled=False
    )
    state = main.AppState()
    state.presence.confirm_ticks = config.presence_confirm_ticks

    run_ticks(config, state, 6)

    assert rec.hook_calls == 0
    assert rec.recognition_calls == 0
    assert state.locked is False
    assert state.camera_failure_streak == 0  # the branch was never entered
    assert rec.prune_calls == 6


def test_detection_only_mode_locks_on_sustained_camera_failure(monkeypatch):
    """--no-face-recognition takes the detect_face path; the fix covers it too.

    The frame check sits above the recognition/detection fork, so a fix applied
    to only one arm would pass every recognition test and fail here.
    """
    rec = install(monkeypatch, [None] * 6)
    config = make_config(
        presence_confirm_ticks=2, camera_failure_grace_ticks=3, face_recognition_enabled=False
    )
    state = main.AppState()
    state.presence.confirm_ticks = config.presence_confirm_ticks

    run_ticks(config, state, 6)

    assert rec.detect_calls == 0  # no frame to run the cascade over
    assert rec.recognition_calls == 0
    assert rec.hook_calls == 1
    assert state.locked is True
    assert rec.prune_calls == 6


def test_grace_ticks_zero_locks_on_the_confirm_ticks_tick(monkeypatch):
    """grace=0 means no tolerance: the failure counts from the first tick."""
    rec = install(monkeypatch, [None] * 2)
    config = make_config(presence_confirm_ticks=2, camera_failure_grace_ticks=0)
    state = main.AppState()
    state.presence.confirm_ticks = config.presence_confirm_ticks

    run_ticks(config, state, 2)

    assert rec.hook_calls == 1
    assert state.locked is True
    assert rec.prune_calls == 2
