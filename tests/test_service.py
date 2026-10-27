"""`pystory up` / `pystory down` through the real entrypoint and a real child.

The child is the real capture loop with every side effect switched off
(no webcam, no screenshot, no face detection, empty hook), so starting it in a
test can neither open the camera nor lock the session.
"""

import os
import sys
import time
from pathlib import Path

import pytest

import pystory.main as main
from pystory import service


def safe_flags(tmp_path):
    return ["--storage-dir", str(tmp_path), "--no-webcam", "--no-screenshot",
            "--no-face-detection", "--no-face-hook", "", "--interval", "1",
            "--no-obsbot-tracking-on-run"]


def run(monkeypatch, *argv):
    monkeypatch.setattr(sys, "argv", ["pystory", *argv])
    with pytest.raises(SystemExit) as exit_info:
        main.main()
    return exit_info.value.code


def alive(pid):
    return Path(f"/proc/{pid}").exists() and not service._is_zombie(pid)


@pytest.fixture
def started(monkeypatch, tmp_path):
    assert run(monkeypatch, "up", *safe_flags(tmp_path)) == 0
    pid = int((tmp_path / "pystory.pid").read_text())
    yield pid
    if alive(pid):
        os.kill(pid, 9)


def test_up_starts_the_capture_loop_in_the_background(started, tmp_path):
    assert alive(started)
    assert b"pystory.main" in Path(f"/proc/{started}/cmdline").read_bytes()
    # Detached: its own session, so closing the terminal does not kill it.
    assert os.getsid(started) == started
    time.sleep(1.5)
    assert "Starting pystory" in (tmp_path / "pystory.log").read_text()


def test_down_stops_it_and_removes_the_pid_file(monkeypatch, started, tmp_path):
    t0 = time.monotonic()
    assert run(monkeypatch, "down", "--storage-dir", str(tmp_path)) == 0
    # Stopped by SIGTERM, not by the SIGKILL fallback after the timeout.
    assert time.monotonic() - t0 < 5

    assert not alive(started)
    assert not (tmp_path / "pystory.pid").exists()


def test_up_twice_does_not_start_a_second_copy(monkeypatch, started, tmp_path, capsys):
    capsys.readouterr()
    assert run(monkeypatch, "up", *safe_flags(tmp_path)) == 0

    assert int((tmp_path / "pystory.pid").read_text()) == started
    assert "already running" in capsys.readouterr().out


def test_up_reports_a_child_that_dies_at_startup(monkeypatch, tmp_path):
    rc = run(monkeypatch, "up", "--storage-dir", str(tmp_path), "--interval", "-1")

    assert rc == 1
    assert not (tmp_path / "pystory.pid").exists()
    assert "--interval" in (tmp_path / "pystory.log").read_text()


def test_down_does_not_signal_a_reused_pid(monkeypatch, tmp_path, capsys):
    # A stale pid file naming a live process that is not pystory (this test
    # runner itself). Signalling it would kill pytest, so surviving is the pass.
    (tmp_path / "pystory.pid").write_text(f"{os.getpid()}\n")

    assert run(monkeypatch, "down", "--storage-dir", str(tmp_path)) == 0

    assert "not running" in capsys.readouterr().out
    assert not (tmp_path / "pystory.pid").exists()


def test_down_when_nothing_is_running(monkeypatch, tmp_path, capsys):
    assert run(monkeypatch, "down", "--storage-dir", str(tmp_path)) == 0
    assert "not running" in capsys.readouterr().out


def test_flags_without_a_subcommand_still_run_the_loop_parser(monkeypatch):
    # `pystory --interval 3` must keep meaning the foreground loop.
    monkeypatch.setattr(sys, "argv", ["pystory", "--interval", "3"])
    assert main.parse_args().interval_seconds == 3


FAKE_OBSBOT_CLI = """#!/bin/sh
# Records each invocation's stdin script, one line per call, like obsbot-cli -i.
printf '%s\\n' "$(cat | tr '\\n' ' ')" >> "$(dirname "$0")/calls.log"
"""


def test_up_turns_tracking_on_and_down_turns_it_off(monkeypatch, tmp_path):
    cli = tmp_path / "obsbot-cli"
    cli.write_text(FAKE_OBSBOT_CLI)
    cli.chmod(0o755)
    calls = tmp_path / "calls.log"
    flags = [f for f in safe_flags(tmp_path) if f != "--no-obsbot-tracking-on-run"]

    assert run(monkeypatch, "up", *flags, "--obsbot-cli-path", str(cli)) == 0
    pid = int((tmp_path / "pystory.pid").read_text())
    try:
        deadline = time.monotonic() + 5
        while not calls.exists() and time.monotonic() < deadline:
            time.sleep(0.1)
        assert calls.read_text().splitlines() == ["i 2 q "]  # Single Human Tracking

        assert run(monkeypatch, "down", "--storage-dir", str(tmp_path)) == 0
        assert calls.read_text().splitlines() == ["i 2 q ", "I q "]  # then AI off
    finally:
        if alive(pid):
            os.kill(pid, 9)


def test_no_obsbot_tracking_on_run_leaves_the_camera_alone(monkeypatch, tmp_path):
    cli = tmp_path / "obsbot-cli"
    cli.write_text(FAKE_OBSBOT_CLI)
    cli.chmod(0o755)

    assert run(monkeypatch, "up", *safe_flags(tmp_path), "--obsbot-cli-path", str(cli)) == 0
    time.sleep(1.5)
    assert run(monkeypatch, "down", "--storage-dir", str(tmp_path)) == 0

    assert not (tmp_path / "calls.log").exists()
