import cv2
import mss
import numpy as np
from PIL import Image
from pathlib import Path

from pystory.config import Config

_face_cascade: cv2.CascadeClassifier | None = None


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
    cam = cv2.VideoCapture(0)
    try:
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
