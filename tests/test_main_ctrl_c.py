"""Ctrl-C must stop pystory at once, whatever the capture loop is doing.

It used to take seconds: the loop ran on the main thread, so a Ctrl-C landing
inside a camera read or face recognition waited for that C call to return, and
the exit path then waited again for obsbot-cli (several seconds just to
connect) to turn tracking off. The loop now runs on a worker thread and the
main thread only waits for the signal.

The timing tests run the real entrypoint in a child process and send it a real
SIGINT, with `tick` replaced by a stand-in that blocks in C code the way
OpenCV does, so a Python-level interrupt cannot reach it.
"""

import os
import signal
import subprocess
import sys
import textwrap
import threading
import time
from pathlib import Path

import pytest

import pystory.main as main

CHILD = textwrap.dedent("""
    import hashlib, sys
    import pystory.main as m

    mode = sys.argv[1]

    def tick(config, state):
        print("TICK", flush=True)
        if mode == "busy":
            # Holds the thread in C for many seconds without checking for
            # signals, like a stuck camera read.
            hashlib.pbkdf2_hmac("sha256", b"x", b"y", 10**8)

    m.tick = tick
    sys.argv = ["pystory", *sys.argv[2:]]
    m.main()
""")

# Stands in for obsbot-cli: enabling returns at once, disabling takes as long
# as the real one does to connect and then records that it ran.
FAKE_CLI = textwrap.dedent("""\
    #!/bin/sh
    input=$(cat)
    case "$input" in
      I*) sleep {delay}; echo off > "{marker}" ;;
    esac
""")


def fake_cli(tmp_path: Path, delay: float) -> tuple[Path, Path]:
    marker = tmp_path / "disabled"
    cli = tmp_path / "obsbot-cli"
    cli.write_text(FAKE_CLI.format(delay=delay, marker=marker))
    cli.chmod(0o755)
    return cli, marker


def start_child(tmp_path, mode, *flags):
    proc = subprocess.Popen(
        [sys.executable, "-c", CHILD, mode, "--storage-dir", str(tmp_path),
         "--no-face-hook", "", "--interval", "1", *flags],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
    )
    # Wait until the loop is really inside a tick before interrupting it.
    assert proc.stdout.readline().strip() == "TICK", proc.stderr.read()
    time.sleep(0.2)
    return proc


def interrupt_and_time(proc, sig=signal.SIGINT, timeout=30):
    sent = time.monotonic()
    proc.send_signal(sig)
    rc = proc.wait(timeout=timeout)
    return rc, time.monotonic() - sent


def test_ctrl_c_exits_at_once_while_a_tick_is_stuck_in_c(tmp_path):
    proc = start_child(tmp_path, "busy", "--no-obsbot-tracking-on-run")
    rc, elapsed = interrupt_and_time(proc)

    assert rc == 130
    assert elapsed < 2, f"took {elapsed:.1f}s to exit"
    assert "Traceback" not in proc.stderr.read()


def test_ctrl_c_does_not_wait_for_obsbot_but_still_turns_tracking_off(tmp_path):
    cli, marker = fake_cli(tmp_path, delay=3)
    proc = start_child(tmp_path, "idle", "--obsbot-cli-path", str(cli))
    rc, elapsed = interrupt_and_time(proc)

    assert rc == 130
    assert elapsed < 2, f"took {elapsed:.1f}s to exit"
    assert not marker.exists(), "fixture check: disabling should still be running"
    deadline = time.monotonic() + 10
    while not marker.exists() and time.monotonic() < deadline:
        time.sleep(0.1)
    assert marker.read_text().strip() == "off", "tracking was never turned off"


def test_sigterm_still_waits_for_tracking_off(tmp_path):
    """systemd kills whatever is left in the unit's cgroup once the main
    process exits, so a background disable would be killed there. SIGTERM
    keeps waiting for it."""
    cli, marker = fake_cli(tmp_path, delay=1)
    proc = start_child(tmp_path, "idle", "--obsbot-cli-path", str(cli))
    rc, elapsed = interrupt_and_time(proc, signal.SIGTERM)

    assert rc == 0
    assert marker.exists(), "exited before tracking was turned off"
    assert elapsed >= 1


# In-process tests of the loop wiring. tick and cv2 are replaced, so nothing
# here opens a camera or a window.


class FakeCv2:
    def __init__(self, keys=()):
        self.delays = []
        self.shown = []
        self.destroy_calls = 0
        self._keys = list(keys)

    def imshow(self, title, frame):
        self.shown.append((title, threading.current_thread() is threading.main_thread()))

    def waitKey(self, delay):
        self.delays.append(delay)
        return self._keys.pop(0) if self._keys else ord("q")

    def destroyAllWindows(self):
        self.destroy_calls += 1


class Frame:
    shape = (10, 10, 3)


def run_main(monkeypatch, tmp_path, argv, tick):
    monkeypatch.setattr(main, "tick", tick)
    monkeypatch.setattr("sys.argv", ["pystory", "--storage-dir", str(tmp_path),
                                     "--no-obsbot-tracking-on-run", *argv])
    main.main()


def test_debug_ui_shows_frames_on_the_main_thread_and_q_quits(monkeypatch, tmp_path):
    fake = FakeCv2(keys=[0, 0])
    monkeypatch.setattr(main, "cv2", fake)

    def tick(config, state):
        state.debug_frames.put((main.DEBUG_WINDOW_WEBCAM, Frame()))

    run_main(monkeypatch, tmp_path, ["--debug-ui", "--interval", "0"], tick)

    assert fake.shown, "no frame reached the debug UI"
    assert all(on_main for _title, on_main in fake.shown), "imshow ran off the main thread"
    assert len(fake.delays) == 3, "q should end the loop on the third key poll"
    assert all(d > 0 for d in fake.delays), "waitKey(<=0) waits forever"
    assert fake.destroy_calls == 1


def test_a_crashed_capture_thread_stops_pystory(monkeypatch, tmp_path):
    """A capture thread that died quietly would leave pystory up and never
    locking, so its exception must surface on the main thread."""
    def tick(config, state):
        raise RuntimeError("camera exploded")

    with pytest.raises(RuntimeError, match="camera exploded"):
        run_main(monkeypatch, tmp_path, [], tick)


def test_interval_is_the_wait_between_ticks(monkeypatch):
    """`--interval 0` means as fast as possible, so the wait between ticks
    must be passed through unclamped, and a nonzero interval unchanged.

    capture_loop is called directly with a recording Event: patching
    threading.Event globally would also replace the one Thread.start() uses."""
    for interval in (0, 2):
        waits = []

        class RecordingEvent(threading.Event):
            def wait(self, timeout=None):
                waits.append(timeout)
                return super().wait(0)

        ticks = []
        monkeypatch.setattr(main, "tick", lambda config, state: ticks.append(1))
        stop = RecordingEvent()
        config = main.Config()
        config.interval_seconds = interval
        original_wait = stop.wait

        def wait_then_stop_after_three(timeout=None):
            result = original_wait(timeout)
            if len(ticks) == 3:
                stop.set()
                return True
            return result

        stop.wait = wait_then_stop_after_three
        errors = []
        main.capture_loop(config, main.AppState(), stop, errors)

        assert errors == []
        assert ticks == [1, 1, 1]
        assert waits == [interval] * 3
