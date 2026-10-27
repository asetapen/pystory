import logging
import subprocess
import threading

from pystory.capture import resolve_webcam_device
from pystory.config import Config

log = logging.getLogger("pystory.obsbot")

# obsbot-cli's interactive mode (-i) reads commands from stdin, one per line.
# 'i' prompts for an AI mode number on a second line; 'I' disables AI mode
# outright. See obsbot-camera-control's src/cli/meet2_test.cpp runInteractiveMode.
_ENABLE_SCRIPT = "i\n{ai_mode}\nq\n"
_DISABLE_SCRIPT = "I\nq\n"

# Centring goes through the camera's standard UVC controls, not obsbot-cli:
# obsbot-cli's "centre view" calls an SDK function documented for the Meet
# models only, and on a Tiny 2 it reports success without moving the gimbal.
# The nudge comes first because a control set to the value it already holds
# may not be sent to the camera, and AI tracking moves the gimbal without
# changing the value the control reports.
_V4L2_NUDGE = "pan_absolute=3600,tilt_absolute=3600"
_V4L2_NEUTRAL = "pan_absolute=0,tilt_absolute=0,zoom_absolute=0"


def _run_cli(config: Config, script: str) -> bool:
    try:
        result = subprocess.run(
            [config.obsbot_cli_path, "-i"],
            input=script,
            capture_output=True,
            text=True,
            timeout=15,
        )
    except FileNotFoundError:
        log.error("obsbot-cli not found at %r", config.obsbot_cli_path)
        return False
    except subprocess.SubprocessError as e:
        log.error("obsbot-cli failed: %s", e)
        return False

    if result.returncode != 0:
        log.error("obsbot-cli exited %d: %s", result.returncode, result.stderr.strip())
        return False
    if "No OBSBOT devices found" in result.stdout:
        log.warning("obsbot-cli reports no camera connected")
        return False
    return True


def enable_tracking(config: Config) -> bool:
    """Enable AI person-tracking (pan/tilt/zoom follow) on the OBSBOT camera."""
    ok = _run_cli(config, _ENABLE_SCRIPT.format(ai_mode=config.obsbot_ai_mode))
    if ok:
        log.info("OBSBOT tracking enabled (ai_mode=%d)", config.obsbot_ai_mode)
    return ok


def _set_controls(config: Config, device: str, controls: str) -> bool:
    try:
        result = subprocess.run(
            [config.v4l2_ctl_path, "-d", device, "-c", controls],
            capture_output=True, text=True, timeout=10,
        )
    except FileNotFoundError:
        log.error("v4l2-ctl not found at %r (Ubuntu: apt install v4l-utils)", config.v4l2_ctl_path)
        return False
    except subprocess.SubprocessError as e:
        log.error("v4l2-ctl failed: %s", e)
        return False
    if result.returncode != 0:
        log.error("v4l2-ctl exited %d: %s", result.returncode, result.stderr.strip())
        return False
    return True


def centre_camera(config: Config) -> bool:
    """Point the camera pystory captures from straight ahead, zoomed out to 1x.

    That is the attached OBSBOT under the default `webcam_device` ("auto").
    AI tracking must already be off, or it steers the gimbal straight back.
    """
    device = resolve_webcam_device(config.webcam_device)
    if not isinstance(device, str):
        log.warning("Camera %r is not an OBSBOT device node; not centring it", device)
        return False
    if not (_set_controls(config, device, _V4L2_NUDGE)
            and _set_controls(config, device, _V4L2_NEUTRAL)):
        return False
    log.info("OBSBOT centred and zoomed out")
    return True


def start_tracking(config: Config, stop: threading.Event) -> bool:
    """pystory's startup sequence: optionally centre and pause, then track.

    The pause lets the camera settle at centre before tracking takes the
    gimbal over. It waits on `stop`, so Ctrl-C during it is not delayed, and
    tracking is not turned on at all once `stop` is set.
    """
    if config.obsbot_neutral_on_start:
        disable_tracking(config)
        centre_camera(config)
        if stop.wait(config.obsbot_neutral_pause_seconds):
            return False
    return enable_tracking(config)


def disable_tracking(config: Config) -> bool:
    """Disable AI tracking on the OBSBOT camera."""
    ok = _run_cli(config, _DISABLE_SCRIPT)
    if ok:
        log.info("OBSBOT tracking disabled")
    return ok


def disable_tracking_in_background(config: Config) -> bool:
    """Start disabling AI tracking and return without waiting for it.

    obsbot-cli takes several seconds just to connect, which is what made
    Ctrl-C slow. The child gets its own session so the terminal's SIGINT does
    not reach it, and it reads the already-written script after we exit. Not
    for a systemd stop: systemd kills everything left in the unit's cgroup.
    """
    try:
        proc = subprocess.Popen(
            [config.obsbot_cli_path, "-i"],
            stdin=subprocess.PIPE,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            text=True,
            start_new_session=True,
        )
    except OSError as e:
        log.error("obsbot-cli could not be started at %r: %s", config.obsbot_cli_path, e)
        return False
    try:
        proc.stdin.write(_DISABLE_SCRIPT)
        proc.stdin.close()
    except OSError as e:
        log.error("obsbot-cli did not accept the disable command: %s", e)
        return False
    log.info("Turning OBSBOT tracking off in the background")
    return True
