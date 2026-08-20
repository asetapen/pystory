"""With nobody enrolled, recognition must fall back to detection (issue st-5ca1n6).

`recognition.is_recognized` returns `None` for TWO different states:

    no face in the frame                            (recognition.py, after looking)
    nobody enrolled, so the frame was never examined (recognition.py, before looking)

`main.tick` mapped `None` to `recognized = False`, a presence MISS. On a fresh
install that is every tick: `face_recognition_enabled` defaults True and
`face_encodings.json` does not exist until `pystory-enroll` runs. So the desk
locked after `presence_confirm_ticks` ticks and could NEVER unlock, because the
no-enrollment `None` is returned BEFORE the frame is looked at and no action by
the person at the desk can change it. The hook that fired is the default
`loginctl lock-session`, a real session lock.

README.md:71 and CLAUDE.md both promise the opposite ("If no faces are enrolled,
it falls back to detection-only mode (any face prevents locking)"), and
`recognition.py` logged "falling back to detection only" while returning `None`
to a caller that did no such thing. `main.py` imported `load_encodings` and never
called it, which was the vestige of the fallback that was never implemented.

WHY THESE ARMS DRIVE `main.tick` AND DO NOT STUB `is_recognized`. The defect is
in what the CALL SITE does with a value `is_recognized` returns correctly, so a
double at that seam cannot see it -- and `tests/test_main_camera_failure.py`
proves the point: it drives the real `tick` but stubs `is_recognized` with a
double that returns a plain BOOL and never `None`, so the whole family is
unreachable in the shipped suite. What is stubbed here is the third-party
`face_recognition` boundary (so "a face is in frame" is stateable without a real
face), the camera, the hook, the pruner, and `main.detect_face` (so the fallback
shows up as a call count rather than as a cv2 result on a fake frame).

BOTH DIRECTIONS OF THE DANGEROUS PATH, as repo/pystory.md requires: a face
present that must NOT lock (r1, r3, r6) and a face absent that MUST (r2, r5).
r1 alone would pass for a build that never locks at all.
"""

import json

import numpy as np
import pytest

import face_recognition

import pystory.main as main
import pystory.recognition as recognition
from pystory.config import Config

FRAME = np.zeros((4, 4, 3), dtype=np.uint8)
ENCODING = [0.0] * 128


class Fake:
    def __init__(self, face_in_frame: bool, matches: bool = True):
        self.face_in_frame = face_in_frame
        self.matches = matches
        self.detect_calls = 0
        self.hook_calls = 0
        self.prune_calls = 0

    # --- third-party boundary --------------------------------------------
    def face_encodings(self, rgb):
        return [np.array(ENCODING)] if self.face_in_frame else []

    def compare_faces(self, known, unknown, tolerance):
        return [self.matches] * len(known)

    # --- pystory's own collaborators -------------------------------------
    def detect_face(self, frame):
        self.detect_calls += 1
        return self.face_in_frame

    def take_webcam_picture(self, timestamp, config):
        return ("webcam.jpg", FRAME)

    def run_hook(self, config):
        self.hook_calls += 1

    def prune_old_files(self, config):
        self.prune_calls += 1
        return 0


def enroll(tmp_path):
    """Write one enrolled encoding, the way `pystory-enroll` would."""
    (tmp_path / recognition.ENCODINGS_FILE).write_text(json.dumps([ENCODING]))


def install(monkeypatch, tmp_path, *, enrolled, face_in_frame, matches=True):
    fake = Fake(face_in_frame, matches)
    monkeypatch.setattr(face_recognition, "face_encodings", fake.face_encodings)
    monkeypatch.setattr(face_recognition, "compare_faces", fake.compare_faces)
    monkeypatch.setattr(main, "take_webcam_picture", fake.take_webcam_picture)
    monkeypatch.setattr(main, "detect_face", fake.detect_face)
    monkeypatch.setattr(main, "run_hook", fake.run_hook)
    monkeypatch.setattr(main, "prune_old_files", fake.prune_old_files)
    if enrolled:
        enroll(tmp_path)
    return fake


def make(tmp_path, **overrides):
    config = Config(storage_dir=tmp_path, screenshot_enabled=False,
                    presence_confirm_ticks=2, **overrides)
    state = main.AppState()
    state.presence.confirm_ticks = config.presence_confirm_ticks
    return config, state


def run_ticks(config, state, n):
    for _ in range(n):
        main.tick(config, state)


# ---------------------------------------------------------------------------
# The defect
# ---------------------------------------------------------------------------

def test_r1_no_enrollment_and_a_face_in_frame_does_not_lock(monkeypatch, tmp_path):
    """THE DEFECT. README.md:71: with nobody enrolled, any face prevents locking."""
    fake = install(monkeypatch, tmp_path, enrolled=False, face_in_frame=True)
    config, state = make(tmp_path)

    run_ticks(config, state, 6)

    assert fake.prune_calls == 6, "tick() did not run to completion"
    assert fake.detect_calls == 6, "the detection fallback was never consulted"
    assert fake.hook_calls == 0
    assert state.locked is False


def test_r2_no_enrollment_and_nobody_there_still_locks(monkeypatch, tmp_path):
    """The other direction. A fallback that never locks is not a fix."""
    fake = install(monkeypatch, tmp_path, enrolled=False, face_in_frame=False)
    config, state = make(tmp_path)

    run_ticks(config, state, 2)

    assert fake.prune_calls == 2
    assert fake.detect_calls == 2
    assert fake.hook_calls == 1
    assert state.locked is True


def test_r3_no_enrollment_recovers_when_the_face_comes_back(monkeypatch, tmp_path):
    """The half that made this permanent: the no-enrollment None is returned
    before the frame is examined, so nothing the user did could clear it."""
    fake = install(monkeypatch, tmp_path, enrolled=False, face_in_frame=False)
    config, state = make(tmp_path)

    run_ticks(config, state, 2)
    assert state.locked is True, "precondition: the desk locked on absence"

    fake.face_in_frame = True
    run_ticks(config, state, 2)

    assert fake.prune_calls == 4
    assert state.locked is False
    assert fake.hook_calls == 1


# ---------------------------------------------------------------------------
# Controls: an enrolled install must be untouched
# ---------------------------------------------------------------------------

def test_r4_enrolled_and_present_does_not_fall_back(monkeypatch, tmp_path):
    """A fix must not turn an ENROLLED install into detection-only. With the
    enrolled user present the detector must not be consulted at all."""
    fake = install(monkeypatch, tmp_path, enrolled=True, face_in_frame=True)
    config, state = make(tmp_path)

    run_ticks(config, state, 4)

    assert fake.prune_calls == 4
    assert fake.detect_calls == 0
    assert fake.hook_calls == 0
    assert state.locked is False


def test_r5_enrolled_and_nobody_there_locks_without_falling_back(monkeypatch, tmp_path):
    """THE ARM THAT CATCHES AN UNCONDITIONAL FALLBACK. An enrolled install with
    an empty frame also gets `None` from `is_recognized`, so a fix that falls back
    on `None` alone would consult the detector here and stop distinguishing
    "nobody enrolled" from "nobody there"."""
    fake = install(monkeypatch, tmp_path, enrolled=True, face_in_frame=False)
    config, state = make(tmp_path)

    run_ticks(config, state, 2)

    assert fake.prune_calls == 2
    assert fake.detect_calls == 0, "the fallback fired for an ENROLLED install"
    assert fake.hook_calls == 1
    assert state.locked is True


def test_r6_an_enrolled_stranger_still_locks(monkeypatch, tmp_path):
    """The strictness recognition mode exists for: a face, but not yours."""
    fake = install(monkeypatch, tmp_path, enrolled=True, face_in_frame=True, matches=False)
    config, state = make(tmp_path)

    run_ticks(config, state, 2)

    assert fake.prune_calls == 2
    assert fake.detect_calls == 0
    assert fake.hook_calls == 1
    assert state.locked is True


# ---------------------------------------------------------------------------
# Why the check is PER TICK and not once at startup
# ---------------------------------------------------------------------------

def test_r7_enrolling_while_pystory_runs_takes_effect_on_the_next_tick(monkeypatch, tmp_path):
    """THIS ARM IS THE DESIGN CHOICE, and a startup-only check fails it.

    `pystory-enroll` writes the encodings file while the capture loop is up, so a
    check made once at startup would keep a just-enrolled user in detection-only
    mode until they restarted pystory -- and detection-only means ANY face
    prevents locking, which is exactly the strictness they enrolled to get.

    A stranger is in frame throughout. Before enrollment that must NOT lock (any
    face is enough); after enrollment the same frame MUST lock, with the detector
    no longer consulted.
    """
    fake = install(monkeypatch, tmp_path, enrolled=False, face_in_frame=True, matches=False)
    config, state = make(tmp_path)

    run_ticks(config, state, 4)
    assert state.locked is False, "precondition: detection-only, so any face is enough"
    assert fake.detect_calls == 4
    assert fake.hook_calls == 0

    enroll(tmp_path)
    run_ticks(config, state, 2)

    assert fake.prune_calls == 6
    assert fake.detect_calls == 4, "the detector must not be consulted once enrolled"
    assert fake.hook_calls == 1
    assert state.locked is True


# ---------------------------------------------------------------------------
# The predicate the fix is built on, tested against the real files
# ---------------------------------------------------------------------------

def test_r8_load_encodings_is_a_safe_emptiness_test(tmp_path):
    """No doubles here. The fix asks `not load_encodings(config)`, and that must
    be a plain list truthiness test: a bare ndarray would raise
    "truth value of an array is ambiguous" and take down the capture loop on the
    one path that decides whether the desk locks."""
    config = Config(storage_dir=tmp_path)
    assert recognition.load_encodings(config) == []
    # Spelled with bool(...) is False, not `not x is True`: `is` binds tighter
    # than `not`, so that reads as `not (x is True)` and passes for every value.
    assert bool(recognition.load_encodings(config)) is False

    enroll(tmp_path)

    loaded = recognition.load_encodings(config)
    assert len(loaded) == 1
    assert isinstance(loaded, list)
    assert bool(loaded) is True
