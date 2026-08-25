import json
import logging
from pathlib import Path

import face_recognition
import numpy as np

from pystory.config import Config

log = logging.getLogger("pystory.recognition")

ENCODINGS_FILE = "face_encodings.json"


def encodings_path(config: Config) -> Path:
    return config.storage_dir / ENCODINGS_FILE


def load_encodings(config: Config) -> list[np.ndarray]:
    path = encodings_path(config)
    if not path.exists():
        return []
    data = json.loads(path.read_text())
    return [np.array(e) for e in data]


def save_encodings(encodings: list[np.ndarray], config: Config) -> None:
    path = encodings_path(config)
    path.parent.mkdir(parents=True, exist_ok=True)
    data = [e.tolist() for e in encodings]
    path.write_text(json.dumps(data))
    log.info("Saved %d face encoding(s) to %s", len(encodings), path)


def encode_face(frame: np.ndarray) -> np.ndarray | None:
    """Extract a face encoding from a BGR frame. Returns None if no face found."""
    # ::-1 reverses the channel axis by making its stride negative rather than
    # copying, so the result is a non-contiguous view. dlib's pybind11 binding
    # requires a C-contiguous buffer and rejects that view with a confusing
    # "incompatible function arguments" TypeError that looks like a signature
    # mismatch rather than a memory-layout one.
    rgb = np.ascontiguousarray(frame[:, :, ::-1])  # BGR to RGB
    encodings = face_recognition.face_encodings(rgb)
    if not encodings:
        return None
    return encodings[0]


def is_recognized(frame: np.ndarray, config: Config) -> bool | None:
    """Check if any face in the frame matches enrolled faces.

    Returns True if recognized, False if face found but not recognized,
    None if no face detected at all.
    """
    known = load_encodings(config)
    if not known:
        log.warning("No enrolled faces found — falling back to detection only")
        return None

    rgb = np.ascontiguousarray(frame[:, :, ::-1])
    unknown_encodings = face_recognition.face_encodings(rgb)
    if not unknown_encodings:
        return None

    for unknown in unknown_encodings:
        matches = face_recognition.compare_faces(known, unknown, tolerance=config.face_tolerance)
        if any(matches):
            return True

    return False
