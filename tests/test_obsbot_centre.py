"""Centring the OBSBOT at startup, then pausing, then turning tracking on.

obsbot-cli's "centre view" reports success on a Tiny 2 without moving the
gimbal, so centring goes through the UVC pan/tilt/zoom controls with v4l2-ctl.
These tests replace both tools with recorders, so no camera moves.
"""

import threading
import time

import pytest

import pystory.obsbot as obsbot
from pystory.config import Config

NUDGE = "pan_absolute=3600,tilt_absolute=3600"
NEUTRAL = "pan_absolute=0,tilt_absolute=0,zoom_absolute=0"


@pytest.fixture
def events(monkeypatch):
    log = []

    def run_cli(config, script):
        log.append(("cli", script, time.monotonic()))
        return True

    def set_controls(config, device, controls):
        log.append(("v4l2", (device, controls), time.monotonic()))
        return True

    monkeypatch.setattr(obsbot, "_run_cli", run_cli)
    monkeypatch.setattr(obsbot, "_set_controls", set_controls)
    return log


def config(**overrides):
    c = Config()
    c.webcam_device = "/dev/fake-obsbot"
    c.obsbot_neutral_pause_seconds = 0
    for k, v in overrides.items():
        setattr(c, k, v)
    return c


def steps(log):
    return [(kind, what) for kind, what, _t in log]


def test_ai_off_then_centre_then_track(events):
    assert obsbot.start_tracking(config(), threading.Event()) is True
    assert steps(events) == [
        ("cli", "I\nq\n"),
        ("v4l2", ("/dev/fake-obsbot", NUDGE)),
        ("v4l2", ("/dev/fake-obsbot", NEUTRAL)),
        ("cli", "i\n2\nq\n"),
    ]


def test_tracking_waits_for_the_pause_after_centring(events):
    obsbot.start_tracking(config(obsbot_neutral_pause_seconds=1), threading.Event())
    centred_at = events[2][2]
    tracked_at = events[3][2]
    assert tracked_at - centred_at >= 1


def test_stopping_during_the_pause_never_turns_tracking_on(events):
    stop = threading.Event()
    threading.Timer(0.2, stop.set).start()
    t0 = time.monotonic()

    assert obsbot.start_tracking(config(obsbot_neutral_pause_seconds=30), stop) is False
    assert time.monotonic() - t0 < 5, "the pause must end as soon as stop is set"
    assert ("cli", "i\n2\nq\n") not in steps(events)


def test_no_neutral_on_start_only_turns_tracking_on(events):
    obsbot.start_tracking(config(obsbot_neutral_on_start=False), threading.Event())
    assert steps(events) == [("cli", "i\n2\nq\n")]


def test_a_camera_index_is_not_centred_but_tracking_still_starts(events, monkeypatch):
    # "auto" with no OBSBOT attached resolves to index 0, the built-in webcam.
    monkeypatch.setattr(obsbot, "resolve_webcam_device", lambda device: 0)
    obsbot.start_tracking(config(webcam_device="auto"), threading.Event())
    assert steps(events) == [("cli", "I\nq\n"), ("cli", "i\n2\nq\n")]


def test_a_failed_nudge_skips_the_centre_but_tracking_still_starts(events, monkeypatch):
    def set_controls(config, device, controls):
        events.append(("v4l2", (device, controls), time.monotonic()))
        return False

    monkeypatch.setattr(obsbot, "_set_controls", set_controls)
    obsbot.start_tracking(config(), threading.Event())
    assert steps(events) == [
        ("cli", "I\nq\n"),
        ("v4l2", ("/dev/fake-obsbot", NUDGE)),
        ("cli", "i\n2\nq\n"),
    ]


def test_set_controls_reports_a_missing_v4l2_ctl(monkeypatch, caplog, tmp_path):
    monkeypatch.undo()  # the real _set_controls, not conftest's stub
    c = config(v4l2_ctl_path=str(tmp_path / "no-such-v4l2-ctl"))
    assert obsbot._set_controls(c, "/dev/fake-obsbot", NEUTRAL) is False
    assert "v4l-utils" in caplog.text


def test_set_controls_passes_device_and_controls(monkeypatch, tmp_path):
    monkeypatch.undo()
    args = tmp_path / "args"
    fake = tmp_path / "v4l2-ctl"
    fake.write_text(f'#!/bin/sh\necho "$*" > "{args}"\n')
    fake.chmod(0o755)

    assert obsbot._set_controls(config(v4l2_ctl_path=str(fake)), "/dev/video9", NEUTRAL) is True
    assert args.read_text().strip() == f"-d /dev/video9 -c {NEUTRAL}"
