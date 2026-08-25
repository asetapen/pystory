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

    # Which camera cv2.VideoCapture opens: an integer index (0, 1, ...) as
    # the OS enumerates video devices, or a device path (e.g. /dev/video2).
    # Defaults to 0, which on a laptop with an external camera attached is
    # usually the built-in camera, not the external one.
    webcam_device: int | str = 0

    # Presence debouncing: consecutive same-direction ticks needed before
    # acting on a lock/unlock decision.
    presence_confirm_ticks: int = 2

    # A webcam that returns no frame is an UNKNOWN presence state, not an
    # absent face, so it gets its own grace period before it is allowed to
    # influence the lock decision. Tolerate this many consecutive capture
    # failures (a momentary USB reset, a device briefly held by something
    # else); every failure after that is fed to the presence tracker as a
    # miss, so `presence_confirm_ticks` more of them then locks the desk.
    # Set camera_failure_locks False to restore fail-open behaviour, where a
    # dead camera never locks.
    camera_failure_locks: bool = True
    camera_failure_grace_ticks: int = 3

    # Desk-lock overlay (see lockscreen.py). This is a foreground Tk window,
    # not a real session lock — see README for why.
    lock_overlay_enabled: bool = False
    lock_passphrase: str = ""
    lock_panic_hotkey: str = "<Control-Alt-Escape>"

    # OBSBOT camera tracking (see obsbot.py).
    obsbot_tracking_enabled: bool = False
    obsbot_cli_path: str = "obsbot-cli"
    obsbot_ai_mode: int = 2  # 2 = Single Human Tracking
    obsbot_ai_sub_mode: int = 1  # 1 = UpperBody

    # S3 capture archival (see s3_archive.py).
    s3_archive_uri: str = ""  # e.g. s3://my-bucket/pystory-captures/
    s3_archive_interval_seconds: int = 3600
    s3_archive_min_age_seconds: int = 600
    s3_archive_delete_after_upload: bool = True
