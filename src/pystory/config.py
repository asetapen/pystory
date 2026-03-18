from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class Config:
    storage_dir: Path = field(default_factory=lambda: Path.home() / ".pystory")
    interval_seconds: int = 5
    image_quality: int = 50  # JPEG quality 1-100
    image_max_dimension: int = 1280  # max width or height in pixels
    max_history_mb: int = 500
    no_face_hook: str = "loginctl lock-session"
    face_detection_enabled: bool = True
    face_recognition_enabled: bool = True
    face_tolerance: float = 0.6  # lower = stricter matching
    screenshot_enabled: bool = True
    webcam_enabled: bool = True
    debug_ui: bool = False
