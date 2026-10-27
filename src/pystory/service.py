"""`pystory up` / `pystory down`: run the capture loop in the background.

`up` starts `python -m pystory.main <flags>` detached from the terminal, with
output appended to `<storage-dir>/pystory.log`, and records its pid in
`<storage-dir>/pystory.pid`. `down` stops the recorded process. Flags after
`up` go to the capture loop unchanged, so `--storage-dir` decides where the
pid and log files live as well as the captures.
"""

import argparse
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

from pystory.config import Config

PID_FILE = "pystory.pid"
LOG_FILE = "pystory.log"

# How long `up` watches the child before reporting it started; a bad flag makes
# argparse exit within this window, and that must be reported, not hidden.
STARTUP_CHECK_SECONDS = 1.0
# Long enough for the loop's exit path, which runs obsbot-cli (timeout 15 s).
STOP_TIMEOUT_SECONDS = 20.0


def storage_dir_from(flags: list[str]) -> Path:
    p = argparse.ArgumentParser(add_help=False)
    p.add_argument("--storage-dir", type=Path)
    known, _ = p.parse_known_args(flags)
    return known.storage_dir if known.storage_dir is not None else Config().storage_dir


def child_argv(flags: list[str]) -> list[str]:
    return [sys.executable, "-m", "pystory.main", *flags]


def running_pid(storage_dir: Path) -> int | None:
    """The pid in the pid file, if that process is alive AND is pystory.

    The second check matters because pids are reused: after a reboot or a
    crash the recorded pid can belong to an unrelated process, which `down`
    must not signal.
    """
    try:
        pid = int((storage_dir / PID_FILE).read_text().strip())
        cmdline = Path(f"/proc/{pid}/cmdline").read_bytes()
    except (OSError, ValueError):
        return None
    if b"pystory.main" not in cmdline:
        return None
    return pid


def up(flags: list[str]) -> int:
    storage_dir = storage_dir_from(flags)
    storage_dir.mkdir(parents=True, exist_ok=True)
    pid = running_pid(storage_dir)
    if pid is not None:
        print(f"pystory is already running (pid {pid})")
        return 0

    # Reject bad flags here, where argparse's message reaches the terminal at
    # once. The child only parses them after its heavy imports, which can
    # take longer than STARTUP_CHECK_SECONDS, so `up` would report it started.
    from pystory.main import parse_args
    try:
        parse_args(flags)
    except SystemExit as e:
        if e.code:
            print("pystory not started: invalid flags", file=sys.stderr)
            return 1
        return 0  # --help

    log_path = storage_dir / LOG_FILE
    with open(log_path, "ab") as log:
        proc = subprocess.Popen(
            child_argv(flags),
            stdin=subprocess.DEVNULL,
            stdout=log,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
    (storage_dir / PID_FILE).write_text(f"{proc.pid}\n")

    try:
        rc = proc.wait(timeout=STARTUP_CHECK_SECONDS)
    except subprocess.TimeoutExpired:
        print(f"pystory started (pid {proc.pid}), logging to {log_path}")
        return 0
    (storage_dir / PID_FILE).unlink(missing_ok=True)
    print(f"pystory exited immediately with status {rc}; see {log_path}", file=sys.stderr)
    return 1


def down(flags: list[str]) -> int:
    storage_dir = storage_dir_from(flags)
    pid_path = storage_dir / PID_FILE
    pid = running_pid(storage_dir)
    if pid is None:
        pid_path.unlink(missing_ok=True)
        print("pystory is not running")
        return 0

    os.kill(pid, signal.SIGTERM)
    deadline = time.monotonic() + STOP_TIMEOUT_SECONDS
    while time.monotonic() < deadline:
        if not Path(f"/proc/{pid}").exists() or _is_zombie(pid):
            break
        time.sleep(0.1)
    else:
        os.kill(pid, signal.SIGKILL)
    pid_path.unlink(missing_ok=True)
    print(f"pystory stopped (pid {pid})")
    return 0


def _is_zombie(pid: int) -> bool:
    try:
        stat = Path(f"/proc/{pid}/stat").read_text()
    except OSError:
        return False
    return stat.rsplit(")", 1)[1].split()[0] == "Z"
