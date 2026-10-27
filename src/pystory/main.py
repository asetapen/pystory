import argparse
import logging
import queue
import signal
import subprocess
import sys
import threading
from datetime import datetime
from pathlib import Path

import cv2

from pystory.capture import take_screenshot, take_webcam_picture, detect_face, resolve_webcam_device
from pystory.config import Config
from pystory.obsbot import disable_tracking, disable_tracking_in_background, enable_tracking, start_tracking
from pystory.presence import PresenceTracker
from pystory.recognition import is_recognized, load_encodings
from pystory.storage import prune_old_files

log = logging.getLogger("pystory")

DEBUG_WINDOW_SCREENSHOT = "pystory - screenshot"
DEBUG_WINDOW_WEBCAM = "pystory - webcam"
# How often the main thread wakes to notice Ctrl-C and pump the debug UI.
MAIN_THREAD_POLL_SECONDS = 0.05


def bounded_int(low: int, high: int | None = None):
    """An argparse `type` that REFUSES an out-of-range value.

    The alternative is letting it reach the field, where it either fails
    obscurely much later (`--max-dimension 0` raises ZeroDivisionError inside
    PIL on the first capture) or does silent damage (`--max-history-mb -1`
    deletes every capture). argparse names the flag and exits 2 for us.
    """

    def parse(raw: str) -> int:
        try:
            value = int(raw)
        except ValueError:
            raise argparse.ArgumentTypeError(f"expected an integer, got {raw!r}")
        if value < low or (high is not None and value > high):
            want = f"{low}-{high}" if high is not None else f"{low} or greater"
            raise argparse.ArgumentTypeError(f"must be {want}, got {value}")
        return value

    return parse


def camera_device(raw: str) -> int | str:
    """An argparse `type` for a camera identifier: an index or a device path.

    cv2.VideoCapture accepts either an integer index (0, 1, ...) or a device
    path (e.g. /dev/video2). Coercing a path through int() would raise, so
    only a numeric-looking value becomes an int; anything else passes through
    unchanged as the device path.
    """
    try:
        return int(raw)
    except ValueError:
        return raw


def non_empty(what: str):
    """An argparse `type` that REFUSES the empty string.

    For a flag whose value cannot work when empty: Tk raises on an empty keysym,
    so an empty panic hotkey would leave the overlay with no escape, and an empty
    command name cannot exec. The alternative is what `if args.x:` used to do --
    drop the value, keep the default, log nothing -- so argparse names the flag
    and exits 2 for us, exactly as `bounded_int` does for a number.

    Not used for `--no-face-hook`: an empty hook is a working no-op (`sh -c ""`
    exits 0), which is a legitimate request and must reach the field instead.
    """

    def parse(raw: str) -> str:
        if not raw:
            raise argparse.ArgumentTypeError(f"expected {what}, got an empty string")
        return raw

    return parse


def parse_args(argv: list[str] | None = None) -> Config:
    p = argparse.ArgumentParser(description="Screenshot + webcam capture with face detection")
    p.add_argument("--storage-dir", type=Path, help="Where to store captures")
    p.add_argument("--interval", type=bounded_int(0),
                    help="Seconds between captures (0 = as fast as possible)")
    p.add_argument("--quality", type=bounded_int(1, 100), help="JPEG quality (1-100)")
    p.add_argument("--max-dimension", type=bounded_int(1), help="Max image width/height in pixels")
    p.add_argument("--max-history-mb", type=bounded_int(0),
                    help="Max storage in MB before pruning (0 = keep nothing)")
    p.add_argument("--no-face-hook", type=str,
                    help="Command to run when no face detected (empty string = run nothing)")
    p.add_argument("--no-face-detection", action="store_true", help="Disable face detection")
    p.add_argument("--no-face-recognition", action="store_true", help="Disable face recognition (detection only)")
    p.add_argument("--face-tolerance", type=float, help="Face match tolerance (lower = stricter, default: 0.6)")
    p.add_argument("--no-screenshot", action="store_true", help="Disable screenshots")
    p.add_argument("--no-webcam", action="store_true", help="Disable webcam capture")
    p.add_argument("--webcam-device", type=camera_device,
                    help="Camera to use: auto, an index (0, 1, ...) or a device path like /dev/video2 "
                         "(default: auto = an attached OBSBOT, else 0)")
    p.add_argument("--webcam-warmup-frames", type=bounded_int(0),
                    help="Frames discarded after opening the camera while exposure settles (default: 20)")
    p.add_argument("--debug-ui", action="store_true", help="Show live preview windows")
    p.add_argument("--presence-confirm-ticks", type=bounded_int(1),
                    help="Consecutive same-result ticks needed before locking/unlocking (default: 2)")
    p.add_argument("--no-camera-failure-lock", action="store_true",
                    help="Do not let a sustained webcam failure lock the desk (restores fail-open)")
    p.add_argument("--camera-failure-grace-ticks", type=bounded_int(0),
                    help="Consecutive frameless ticks tolerated before a camera failure "
                         "counts against presence (0 = none, default: 3)")
    p.add_argument("--lock-overlay", action="store_true",
                    help="Show a fullscreen block overlay instead of/alongside --no-face-hook")
    p.add_argument("--lock-passphrase", type=str, help="Passphrase that dismisses the lock overlay")
    p.add_argument("--lock-panic-hotkey", type=non_empty("a Tk keysym"),
                    help="Tk keysym that force-dismisses the overlay (default: <Control-Alt-Escape>)")
    p.add_argument("--obsbot-tracking", action="store_true",
                    help="Enable/disable OBSBOT AI tracking based on presence")
    p.add_argument("--no-obsbot-tracking-on-run", action="store_true",
                    help="Do not turn OBSBOT AI tracking on at startup and off at exit")
    p.add_argument("--no-obsbot-neutral-on-start", action="store_true",
                    help="Do not centre and zoom out the OBSBOT camera at startup")
    p.add_argument("--obsbot-neutral-pause", type=bounded_int(0),
                    help="Seconds to hold the camera centred before tracking starts (default: 3)")
    p.add_argument("--v4l2-ctl-path", type=non_empty("a path or command name"),
                    help="Path to v4l2-ctl, used to centre the camera (default: v4l2-ctl on PATH)")
    p.add_argument("--obsbot-cli-path", type=non_empty("a path or command name"),
                    help="Path to obsbot-cli (default: obsbot-cli on PATH)")

    args = p.parse_args(argv)
    config = Config()

    # Every flag that carries a VALUE is gated on `is not None`, never on
    # truthiness: `if args.x:` cannot tell "not passed" from "passed a falsy
    # value", and it silently applies the default for both. The `store_true`
    # flags below are the exception, and gating those on truthiness is correct --
    # for them False IS absence.
    if args.storage_dir is not None:
        config.storage_dir = args.storage_dir
    if args.interval is not None:
        config.interval_seconds = args.interval
    if args.quality is not None:
        config.image_quality = args.quality
    if args.max_dimension is not None:
        config.image_max_dimension = args.max_dimension
    if args.max_history_mb is not None:
        config.max_history_mb = args.max_history_mb
    if args.no_face_hook is not None:
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
    if args.webcam_device is not None:
        config.webcam_device = args.webcam_device
    if args.webcam_warmup_frames is not None:
        config.webcam_warmup_frames = args.webcam_warmup_frames
    if args.debug_ui:
        config.debug_ui = True
    if args.presence_confirm_ticks is not None:
        config.presence_confirm_ticks = args.presence_confirm_ticks
    if args.no_camera_failure_lock:
        config.camera_failure_locks = False
    if args.camera_failure_grace_ticks is not None:
        config.camera_failure_grace_ticks = args.camera_failure_grace_ticks
    if args.lock_overlay:
        config.lock_overlay_enabled = True
    if args.lock_passphrase is not None:
        config.lock_passphrase = args.lock_passphrase
    if args.lock_panic_hotkey is not None:
        config.lock_panic_hotkey = args.lock_panic_hotkey
    if args.obsbot_tracking:
        config.obsbot_tracking_enabled = True
    if args.no_obsbot_tracking_on_run:
        config.obsbot_tracking_on_run = False
    if args.no_obsbot_neutral_on_start:
        config.obsbot_neutral_on_start = False
    if args.obsbot_neutral_pause is not None:
        config.obsbot_neutral_pause_seconds = args.obsbot_neutral_pause
    if args.v4l2_ctl_path is not None:
        config.v4l2_ctl_path = args.v4l2_ctl_path
    if args.obsbot_cli_path is not None:
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
        # Consecutive ticks the webcam has returned no usable frame. Reset by
        # any successful capture; see camera_failure_grace_ticks.
        self.camera_failure_streak = 0
        # (window title, frame) pairs for the debug UI. tick() runs on the
        # capture thread and OpenCV's Qt GUI must stay on the main thread, so
        # frames are handed over here instead of shown from tick().
        self.debug_frames: queue.Queue = queue.Queue()


def apply_presence(config: Config, state: AppState, recognized: bool) -> None:
    """Feed one presence observation to the debouncer and act on a transition.

    The single place the lock/unlock side effects fire, so the camera-failure
    path and the normal recognition path cannot drift apart.
    """
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

    if config.face_detection_enabled:
        if webcam_frame is not None:
            state.camera_failure_streak = 0
            if config.face_recognition_enabled:
                result = is_recognized(webcam_frame, config)
                if result is None and not load_encodings(config):
                    # `None` covers TWO states and only one of them is a reason to
                    # fall back: "no face in the frame", and "nobody is enrolled,
                    # so the frame was never examined". Treating both as a MISS is
                    # what locked a fresh install on the second tick, with no way
                    # back: the no-enrollment None is returned before the frame is
                    # looked at, so nothing the user did could clear it.
                    #
                    # Asked here rather than inside `is_recognized` so the value a
                    # caller (or a test double) sees keeps its meaning, and asked
                    # only on the None path, so an enrolled install never pays the
                    # extra read while a face is in frame.
                    #
                    # Per tick, not once at startup: `pystory-enroll` writes the
                    # encodings file while this loop is running, so a startup check
                    # would keep a just-enrolled user in detection-only mode --
                    # where ANY face prevents locking -- until they restarted.
                    recognized = detect_face(webcam_frame)
                else:
                    recognized = result is True
                    if result is None:
                        log.info("No face detected")
                    elif result is False:
                        log.info("Face detected but not recognized")
                    else:
                        log.debug("Face recognized")
            else:
                recognized = detect_face(webcam_frame)

            apply_presence(config, state, recognized)
        else:
            # No frame is an UNKNOWN presence state. Absent this branch the
            # whole lock decision is skipped, so a dead camera leaves the desk
            # unlocked indefinitely with only a WARNING to show for it.
            state.camera_failure_streak += 1
            if not config.camera_failure_locks:
                log.warning(
                    "Webcam unavailable for %d tick(s); camera_failure_locks is off, "
                    "leaving the lock state unchanged",
                    state.camera_failure_streak,
                )
            elif state.camera_failure_streak <= config.camera_failure_grace_ticks:
                log.warning(
                    "Webcam unavailable for %d tick(s), within the grace period of %d; "
                    "not yet counting it against presence",
                    state.camera_failure_streak,
                    config.camera_failure_grace_ticks,
                )
            else:
                log.warning(
                    "Webcam unavailable for %d consecutive tick(s), past the grace period "
                    "of %d; treating presence as unconfirmed",
                    state.camera_failure_streak,
                    config.camera_failure_grace_ticks,
                )
                apply_presence(config, state, False)

    if config.debug_ui:
        if screenshot_frame is not None:
            state.debug_frames.put((DEBUG_WINDOW_SCREENSHOT, screenshot_frame))
        if webcam_frame is not None:
            state.debug_frames.put((DEBUG_WINDOW_WEBCAM, webcam_frame))

    pruned = prune_old_files(config)
    if pruned:
        log.info("Pruned %d old files", pruned)


def main() -> None:
    if len(sys.argv) > 1 and sys.argv[1] in ("up", "down"):
        from pystory import service
        command = service.up if sys.argv[1] == "up" else service.down
        sys.exit(command(sys.argv[2:]))

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
    )

    config = parse_args()
    config.storage_dir.mkdir(parents=True, exist_ok=True)

    log.info("Starting pystory (interval=%ds, storage=%s)", config.interval_seconds, config.storage_dir)
    if config.webcam_enabled:
        log.info("Webcam device %s resolves to %s", config.webcam_device, resolve_webcam_device(config.webcam_device))

    state = AppState()
    state.presence.confirm_ticks = config.presence_confirm_ticks
    if config.lock_overlay_enabled:
        from pystory.lockscreen import LockOverlay
        state.lock_overlay = LockOverlay(config)
        state.lock_overlay.start()

    # SIGTERM (what `pystory down` and systemd send) would otherwise end the
    # process without running the `finally` below, leaving tracking on.
    signal.signal(signal.SIGTERM, lambda signum, frame: sys.exit(0))

    stop = threading.Event()
    errors: list[BaseException] = []
    interrupted = False
    try:
        if config.obsbot_tracking_on_run:
            start_tracking(config, stop)
        worker = threading.Thread(
            target=capture_loop, args=(config, state, stop, errors),
            name="pystory-capture", daemon=True,
        )
        worker.start()
        if config.debug_ui:
            pump_debug_ui(state, stop)
        else:
            # Woken often so Ctrl-C lands within one poll, whatever the
            # capture thread is in the middle of.
            while not stop.wait(MAIN_THREAD_POLL_SECONDS):
                pass
        if errors:
            raise errors[0]
    except KeyboardInterrupt:
        interrupted = True
        log.info("Interrupted, exiting")
    finally:
        stop.set()
        if config.obsbot_tracking_on_run:
            if interrupted:
                disable_tracking_in_background(config)
            else:
                disable_tracking(config)
        if config.debug_ui:
            cv2.destroyAllWindows()
    if interrupted:
        sys.exit(130)


def capture_loop(config: Config, state: AppState, stop: threading.Event,
                 errors: list[BaseException]) -> None:
    """The tick loop, run on its own daemon thread.

    A daemon so that exiting never waits for a tick stuck in a camera read or
    face recognition. Any exception is handed to the main thread, which
    re-raises it: a capture thread that died quietly would leave pystory
    running and never locking.
    """
    try:
        while not stop.is_set():
            tick(config, state)
            if stop.wait(config.interval_seconds):
                break
    except BaseException as e:
        errors.append(e)
    finally:
        stop.set()


def pump_debug_ui(state: AppState, stop: threading.Event) -> None:
    """Show frames from the capture thread and watch for `q`, on the main thread."""
    shown = False
    poll_ms = max(1, int(MAIN_THREAD_POLL_SECONDS * 1000))
    while not stop.is_set():
        try:
            while True:
                title, frame = state.debug_frames.get_nowait()
                show_debug(title, frame)
                shown = True
        except queue.Empty:
            pass
        if not shown:
            # waitKey returns at once while no window exists, so it cannot
            # pace this loop until the first frame is up.
            stop.wait(MAIN_THREAD_POLL_SECONDS)
            continue
        if cv2.waitKey(poll_ms) == ord("q"):
            log.info("Quit requested via debug UI")
            stop.set()

if __name__ == "__main__":
    main()
