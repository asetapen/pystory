import argparse
import logging
import subprocess
import time
from datetime import datetime
from pathlib import Path

import cv2

from pystory.capture import take_screenshot, take_webcam_picture, detect_face
from pystory.config import Config
from pystory.obsbot import disable_tracking, enable_tracking
from pystory.presence import PresenceTracker
from pystory.recognition import is_recognized, load_encodings
from pystory.storage import prune_old_files

log = logging.getLogger("pystory")

DEBUG_WINDOW_SCREENSHOT = "pystory - screenshot"
DEBUG_WINDOW_WEBCAM = "pystory - webcam"


def parse_args() -> Config:
    p = argparse.ArgumentParser(description="Screenshot + webcam capture with face detection")
    p.add_argument("--storage-dir", type=Path, help="Where to store captures")
    p.add_argument("--interval", type=int, help="Seconds between captures")
    p.add_argument("--quality", type=int, help="JPEG quality (1-100)")
    p.add_argument("--max-dimension", type=int, help="Max image width/height in pixels")
    p.add_argument("--max-history-mb", type=int, help="Max storage in MB before pruning")
    p.add_argument("--no-face-hook", type=str, help="Command to run when no face detected")
    p.add_argument("--no-face-detection", action="store_true", help="Disable face detection")
    p.add_argument("--no-face-recognition", action="store_true", help="Disable face recognition (detection only)")
    p.add_argument("--face-tolerance", type=float, help="Face match tolerance (lower = stricter, default: 0.6)")
    p.add_argument("--no-screenshot", action="store_true", help="Disable screenshots")
    p.add_argument("--no-webcam", action="store_true", help="Disable webcam capture")
    p.add_argument("--debug-ui", action="store_true", help="Show live preview windows")
    p.add_argument("--presence-confirm-ticks", type=int,
                    help="Consecutive same-result ticks needed before locking/unlocking (default: 2)")
    p.add_argument("--lock-overlay", action="store_true",
                    help="Show a fullscreen block overlay instead of/alongside --no-face-hook")
    p.add_argument("--lock-passphrase", type=str, help="Passphrase that dismisses the lock overlay")
    p.add_argument("--lock-panic-hotkey", type=str,
                    help="Tk keysym that force-dismisses the overlay (default: <Control-Alt-Escape>)")
    p.add_argument("--obsbot-tracking", action="store_true",
                    help="Enable/disable OBSBOT AI tracking based on presence")
    p.add_argument("--obsbot-cli-path", type=str, help="Path to obsbot-cli (default: obsbot-cli on PATH)")

    args = p.parse_args()
    config = Config()

    if args.storage_dir:
        config.storage_dir = args.storage_dir
    if args.interval:
        config.interval_seconds = args.interval
    if args.quality:
        config.image_quality = args.quality
    if args.max_dimension:
        config.image_max_dimension = args.max_dimension
    if args.max_history_mb:
        config.max_history_mb = args.max_history_mb
    if args.no_face_hook:
        config.no_face_hook = args.no_face_hook
    if args.no_face_detection:
        config.face_detection_enabled = False
    if args.no_face_recognition:
        config.face_recognition_enabled = False
    if args.face_tolerance is not None:
        config.face_tolerance = args.face_tolerance
    if args.no_screenshot:
        config.screenshot_enabled = False
    if args.no_webcam:
        config.webcam_enabled = False
    if args.debug_ui:
        config.debug_ui = True
    if args.presence_confirm_ticks is not None:
        config.presence_confirm_ticks = args.presence_confirm_ticks
    if args.lock_overlay:
        config.lock_overlay_enabled = True
    if args.lock_passphrase:
        config.lock_passphrase = args.lock_passphrase
    if args.lock_panic_hotkey:
        config.lock_panic_hotkey = args.lock_panic_hotkey
    if args.obsbot_tracking:
        config.obsbot_tracking_enabled = True
    if args.obsbot_cli_path:
        config.obsbot_cli_path = args.obsbot_cli_path

    return config


def run_hook(config: Config) -> None:
    log.warning("No face detected, running hook: %s", config.no_face_hook)
    try:
        subprocess.run(config.no_face_hook, shell=True, check=True, timeout=10)
    except subprocess.SubprocessError as e:
        log.error("Hook failed: %s", e)


def show_debug(title: str, frame, max_width: int = 800) -> None:
    h, w = frame.shape[:2]
    if w > max_width:
        scale = max_width / w
        frame = cv2.resize(frame, (max_width, int(h * scale)))
    cv2.imshow(title, frame)


class AppState:
    """Tracks whether we're currently 'locked' so hooks/overlay/tracking only
    fire on state transitions, not every tick."""

    def __init__(self) -> None:
        self.presence = PresenceTracker()
        self.locked = False
        self.lock_overlay = None


def tick(config: Config, state: AppState) -> None:
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    screenshot_frame = None
    if config.screenshot_enabled:
        try:
            path, screenshot_frame = take_screenshot(timestamp, config)
            log.info("Screenshot saved: %s", path)
        except Exception as e:
            log.error("Screenshot failed: %s", e)

    webcam_frame = None
    if config.webcam_enabled:
        try:
            path, webcam_frame = take_webcam_picture(timestamp, config)
            if path:
                log.info("Webcam saved: %s", path)
            else:
                log.warning("Webcam capture failed (no frame)")
        except Exception as e:
            log.error("Webcam failed: %s", e)

    if config.face_detection_enabled and webcam_frame is not None:
        if config.face_recognition_enabled:
            result = is_recognized(webcam_frame, config)
            recognized = result is True
            if result is None:
                log.info("No face detected")
            elif result is False:
                log.info("Face detected but not recognized")
            else:
                log.debug("Face recognized")
        else:
            recognized = detect_face(webcam_frame)

        state.presence.observe(recognized)
        decision = state.presence.should_be_locked
        if decision is True and not state.locked:
            state.locked = True
            run_hook(config)
            if state.lock_overlay is not None:
                state.lock_overlay.show()
            if config.obsbot_tracking_enabled:
                disable_tracking(config)
        elif decision is False and state.locked:
            state.locked = False
            log.info("Presence confirmed, unlocking")
            if state.lock_overlay is not None:
                state.lock_overlay.hide()
            if config.obsbot_tracking_enabled:
                enable_tracking(config)

    if config.debug_ui:
        if screenshot_frame is not None:
            show_debug(DEBUG_WINDOW_SCREENSHOT, screenshot_frame)
        if webcam_frame is not None:
            show_debug(DEBUG_WINDOW_WEBCAM, webcam_frame)

    pruned = prune_old_files(config)
    if pruned:
        log.info("Pruned %d old files", pruned)


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
    )

    config = parse_args()
    config.storage_dir.mkdir(parents=True, exist_ok=True)

    log.info("Starting pystory (interval=%ds, storage=%s)", config.interval_seconds, config.storage_dir)

    state = AppState()
    state.presence.confirm_ticks = config.presence_confirm_ticks
    if config.lock_overlay_enabled:
        from pystory.lockscreen import LockOverlay
        state.lock_overlay = LockOverlay(config)
        state.lock_overlay.start()

    try:
        while True:
            tick(config, state)
            if config.debug_ui:
                key = cv2.waitKey(config.interval_seconds * 1000)
                if key == ord("q"):
                    log.info("Quit requested via debug UI")
                    break
            else:
                time.sleep(config.interval_seconds)
    finally:
        if config.debug_ui:
            cv2.destroyAllWindows()


if __name__ == "__main__":
    main()
