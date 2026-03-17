import argparse
import logging
import subprocess
import time
from datetime import datetime
from pathlib import Path

import cv2

from pystory.capture import take_screenshot, take_webcam_picture, detect_face
from pystory.config import Config
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
    p.add_argument("--no-screenshot", action="store_true", help="Disable screenshots")
    p.add_argument("--no-webcam", action="store_true", help="Disable webcam capture")
    p.add_argument("--debug-ui", action="store_true", help="Show live preview windows")

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
    if args.no_screenshot:
        config.screenshot_enabled = False
    if args.no_webcam:
        config.webcam_enabled = False
    if args.debug_ui:
        config.debug_ui = True

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


def tick(config: Config) -> None:
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
        if not detect_face(webcam_frame):
            run_hook(config)

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

    try:
        while True:
            tick(config)
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
