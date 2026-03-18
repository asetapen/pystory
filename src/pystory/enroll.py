import argparse
import logging
from pathlib import Path

import cv2

from pystory.config import Config
from pystory.recognition import encode_face, load_encodings, save_encodings

log = logging.getLogger("pystory.enroll")


def capture_and_enroll(config: Config, num_samples: int) -> int:
    """Capture face samples from the webcam and enroll them. Returns number of new encodings added."""
    existing = load_encodings(config)
    new_encodings = []

    cam = cv2.VideoCapture(0)
    try:
        print(f"Look at the camera. Capturing {num_samples} sample(s)...")
        print("Press SPACE to capture, Q to finish early, ESC to cancel.")

        captured = 0
        while captured < num_samples:
            ret, frame = cam.read()
            if not ret:
                log.error("Failed to read from webcam")
                break

            display = frame.copy()
            cv2.putText(display, f"Sample {captured}/{num_samples} - SPACE to capture",
                        (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 0), 2)
            cv2.imshow("pystory - enroll", display)

            key = cv2.waitKey(1) & 0xFF
            if key == ord("q"):
                break
            if key == 27:  # ESC
                print("Cancelled.")
                return 0
            if key != ord(" "):
                continue

            encoding = encode_face(frame)
            if encoding is None:
                print("  No face detected, try again.")
                continue

            new_encodings.append(encoding)
            captured += 1
            print(f"  Captured sample {captured}/{num_samples}")
    finally:
        cam.release()
        cv2.destroyAllWindows()

    if new_encodings:
        all_encodings = existing + new_encodings
        save_encodings(all_encodings, config)
        print(f"Enrolled {len(new_encodings)} new sample(s) ({len(all_encodings)} total).")

    return len(new_encodings)


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
    )

    p = argparse.ArgumentParser(description="Enroll your face for pystory recognition")
    p.add_argument("--storage-dir", type=Path, help="Where pystory data is stored")
    p.add_argument("--samples", type=int, default=5, help="Number of face samples to capture (default: 5)")
    p.add_argument("--reset", action="store_true", help="Clear all enrolled faces before enrolling")
    args = p.parse_args()

    config = Config()
    if args.storage_dir:
        config.storage_dir = args.storage_dir
    config.storage_dir.mkdir(parents=True, exist_ok=True)

    if args.reset:
        from pystory.recognition import encodings_path
        path = encodings_path(config)
        if path.exists():
            path.unlink()
            print("Cleared all enrolled faces.")

    capture_and_enroll(config, args.samples)


if __name__ == "__main__":
    main()
