import logging
import subprocess

from pystory.config import Config

log = logging.getLogger("pystory.obsbot")

# obsbot-cli's interactive mode (-i) reads commands from stdin, one per line.
# 'i' prompts for an AI mode number on a second line; 'I' disables AI mode
# outright. See obsbot-camera-control's src/cli/meet2_test.cpp runInteractiveMode.
_ENABLE_SCRIPT = "i\n{ai_mode}\nq\n"
_DISABLE_SCRIPT = "I\nq\n"


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
