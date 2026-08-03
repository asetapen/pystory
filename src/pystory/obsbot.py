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
