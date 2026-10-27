import os

import cv2
import mss
import numpy as np
from PIL import Image
from pathlib import Path

from pystory.config import Config

_face_cascade: cv2.CascadeClassifier | None = None

AUTO_WEBCAM_DEVICE = "auto"
V4L_BY_ID_DIR = Path("/dev/v4l/by-id")

# Always open through V4L2. Given a device PATH with no API preference, OpenCV
# picks its FFMPEG backend, which opens an OBSBOT Tiny 2 Lite and then fails
# every read; an integer index happened to pick V4L2, which reads fine. Bound
# at import so a test double for `cv2` does not need to carry the constant.
WEBCAM_API = cv2.CAP_V4L2


def resolve_webcam_device(device: int | str, by_id_dir: Path = V4L_BY_ID_DIR) -> int | str:
    """Turn `webcam_device` into something cv2.VideoCapture can open.

    "auto" picks an attached OBSBOT's capture node (the `-video-index0` entry
    under /dev/v4l/by-id; `-index1` is its metadata node, which yields no
    frames) and falls back to index 0 when there is none. by-id only lists
    real USB devices, so a v4l2loopback "OBSBOT Virtual Camera" is never
    chosen. Resolved to the /dev/videoN target because that is the form
    OpenCV's V4L2 backend is known to accept. Anything else passes through.
    """
    if device != AUTO_WEBCAM_DEVICE:
        return device
    try:
        names = sorted(os.listdir(by_id_dir))
    except OSError:
        return 0
    for name in names:
        if "obsbot" in name.lower() and name.endswith("-video-index0"):
            return os.path.realpath(by_id_dir / name)
    return 0


def _get_face_cascade() -> cv2.CascadeClassifier:
    global _face_cascade
    if _face_cascade is None:
        cascade_path = cv2.data.haarcascades + "haarcascade_frontalface_default.xml"
        _face_cascade = cv2.CascadeClassifier(cascade_path)
    return _face_cascade


def _compress_and_save(img: Image.Image, path: Path, config: Config) -> None:
    img.thumbnail((config.image_max_dimension, config.image_max_dimension))
    path.parent.mkdir(parents=True, exist_ok=True)
    img.save(path, "JPEG", quality=config.image_quality)


def take_screenshot(timestamp: str, config: Config) -> tuple[Path, np.ndarray]:
    with mss.mss() as sct:
        monitor = sct.monitors[0]  # all monitors combined
        raw = sct.grab(monitor)
        img = Image.frombytes("RGB", raw.size, raw.bgra, "raw", "BGRX")
    path = config.storage_dir / f"screenshot_{timestamp}.jpg"
    _compress_and_save(img, path, config)
    frame = cv2.cvtColor(np.array(img), cv2.COLOR_RGB2BGR)
    return path, frame


def take_webcam_picture(timestamp: str, config: Config) -> tuple[Path | None, np.ndarray | None]:
    cam = cv2.VideoCapture(resolve_webcam_device(config.webcam_device), WEBCAM_API)
    try:
        # The camera is opened fresh every tick, and the first frames after an
        # open are taken before auto-exposure settles. Measured on an OBSBOT
        # Tiny 2 Lite: frames 0-5 averaged ~60/255 against ~155 once settled,
        # and the face detector missed the first frame on 8 of 8 opens with a
        # face in view, which on its own locks the desk every few ticks.
        for _ in range(config.webcam_warmup_frames + 1):
            ret, frame = cam.read()
            if not ret:
                return None, None
        img = Image.fromarray(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))
        path = config.storage_dir / f"webcam_{timestamp}.jpg"
        _compress_and_save(img, path, config)
        return path, frame
    finally:
        cam.release()


def detect_face(frame: np.ndarray) -> bool:
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    cascade = _get_face_cascade()
    faces = cascade.detectMultiScale(gray, scaleFactor=1.1, minNeighbors=5, minSize=(30, 30))
    return len(faces) > 0
