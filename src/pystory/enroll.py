import argparse
import logging
import time
from pathlib import Path

import cv2

from pystory.config import Config
from pystory.main import bounded_int, camera_device
from pystory.recognition import encode_face, load_encodings, save_encodings

log = logging.getLogger("pystory.enroll")

# Prompts walk the user through varied head angles so the enrolled encoding
# set covers more of the pose space recognition will see in practice.
POSE_PROMPTS = [
    "Look straight at the camera",
    "Turn your head slightly left",
    "Turn your head slightly right",
    "Tilt your chin up slightly",
    "Tilt your chin down slightly",
    "Look straight at the camera again",
]


def capture_and_enroll(config: Config, num_samples: int, auto_delay: float = 1.5, reset: bool = False) -> int:
    """Auto-capture face samples from the webcam and enroll them.

    Cycles through pose prompts and automatically grabs a sample every
    `auto_delay` seconds once a face is detected, instead of relying on
    manual keypresses. Returns number of new encodings added.

    `reset` replaces the existing enrollment with the newly captured set
    instead of appending to it -- and only once capture actually produces
    at least one sample, so a cancelled or failed capture leaves the
    previous enrollment untouched rather than wiping it up front.
    """
    existing = [] if reset else load_encodings(config)
    new_encodings: list = []

    cam = cv2.VideoCapture(config.webcam_device)
    try:
        print(f"Capturing {num_samples} sample(s) automatically. Follow the prompts.")
        print("Press Q to finish early, ESC to cancel.")

        captured = 0
        last_capture = 0.0
        while captured < num_samples:
            ret, frame = cam.read()
            if not ret:
                log.error("Failed to read from webcam")
                break

            prompt = POSE_PROMPTS[captured % len(POSE_PROMPTS)]
            now = time.monotonic()
            remaining = max(0.0, auto_delay - (now - last_capture))

            display = frame.copy()
            cv2.putText(display, f"Sample {captured}/{num_samples}: {prompt}",
                        (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 0), 2)
            cv2.putText(display, f"capturing in {remaining:.1f}s...",
                        (10, 60), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 200, 255), 2)
            cv2.imshow("pystory - enroll", display)

            key = cv2.waitKey(1) & 0xFF
            if key == ord("q"):
                break
            if key == 27:  # ESC
                print("Cancelled.")
                return 0

            if remaining > 0:
                continue

            encoding = encode_face(frame)
            if encoding is None:
                print(f"  [{prompt}] No face detected, still trying...")
                continue

            new_encodings.append(encoding)
            captured += 1
            last_capture = now
            print(f"  Captured sample {captured}/{num_samples} ({prompt})")
    finally:
        cam.release()
        cv2.destroyAllWindows()

    if new_encodings:
        all_encodings = existing + new_encodings
        save_encodings(all_encodings, config)
        if reset:
            print(f"Cleared previous enrollment. Enrolled {len(new_encodings)} new sample(s).")
        else:
            print(f"Enrolled {len(new_encodings)} new sample(s) ({len(all_encodings)} total).")

    return len(new_encodings)


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Enroll your face for pystory recognition")
    p.add_argument("--storage-dir", type=Path, help="Where pystory data is stored")
    p.add_argument("--samples", type=bounded_int(1), default=8, help="Number of face samples to capture (default: 8)")
    p.add_argument("--delay", type=float, default=1.5, help="Seconds between auto-captures (default: 1.5)")
    p.add_argument("--reset", action="store_true", help="Clear all enrolled faces before enrolling")
    p.add_argument("--webcam-device", type=camera_device,
                    help="Camera to use: an index (0, 1, ...) or a device path like /dev/video2 (default: 0)")
    return p.parse_args()


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
    )

    args = parse_args()

    config = Config()
    if args.storage_dir:
        config.storage_dir = args.storage_dir
    if args.webcam_device is not None:
        config.webcam_device = args.webcam_device
    config.storage_dir.mkdir(parents=True, exist_ok=True)

    capture_and_enroll(config, args.samples, args.delay, reset=args.reset)


if __name__ == "__main__":
    main()
