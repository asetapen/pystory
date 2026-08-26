# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What This Is

pystory captures screenshots and webcam pictures on a timer. If the enrolled user's face isn't detected, it locks the screen (configurable hook). Targets Ubuntu 24.

## Commands

```bash
# Install system deps + uv + python packages
./install.sh

# Run
uv sync
uv run pystory
uv run pystory --debug-ui          # live preview windows
uv run pystory --no-face-recognition  # detection only (any face)
uv run pystory --lock-overlay --lock-passphrase "..."  # fullscreen block overlay
uv run pystory --obsbot-tracking   # drive OBSBOT AI tracking off presence

# Enroll face for recognition (auto-captures through pose prompts)
uv run pystory-enroll
uv run pystory-enroll --samples 10 --reset

# Generate timelapse videos
uv run pystory-timelapse --type webcam --fps 30

# Archive old captures to S3
uv run pystory-s3-archive --s3-uri s3://bucket/prefix/

# Browse captures in a local web UI (http://127.0.0.1:8420/)
uv run pystory-web

# Install as systemd user service
cp sys/pystory.service ~/.config/systemd/user/
systemctl --user enable --now pystory

# Tests
uv sync --group dev
uv run pytest
```

## Architecture

All source is in `src/pystory/`. Five CLI entrypoints defined in `pyproject.toml [project.scripts]`:

- **`pystory`** → `main.py:main` — Main capture loop. Each tick: screenshot (mss) → webcam (opencv) → face check → debounce via `PresenceTracker` → on a state transition: hook / lock overlay / OBSBOT tracking → prune old files. `--debug-ui` uses `cv2.imshow` with `cv2.waitKey` as the sleep mechanism.
- **`pystory-enroll`** → `enroll.py:main` — Auto-captures face samples from the webcam while cycling pose prompts (straight/left/right/chin up/chin down) and stores dlib encodings as JSON in `~/.pystory/face_encodings.json`.
- **`pystory-timelapse`** → `timelapse.py:main` — Reads stored JPEGs sorted by filename (embeds timestamp) and stitches into MP4 via `cv2.VideoWriter`.
- **`pystory-s3-archive`** → `s3_archive.py:main` — Uploads captures older than `--min-age` to a configurable S3 URI via the `aws` CLI and deletes the local copy (unless `--keep-local`). Can loop with `--interval` or run as a systemd timer (`sys/pystory-s3-archive.{service,timer}`, fires nightly at 03:30 by default).
- **`pystory-web`** → `web.py:main` — Local web viewer (stdlib `http.server`, no extra deps) for scrubbing through captures day by day. Binds `127.0.0.1:8420` by default — no auth, so don't rebind it to a non-localhost host without adding your own. Groups files by the `YYYYMMDD` embedded in the filename (`list_days`/`list_ticks_for_day`, pure and testable); `/api/days`, `/api/days/<day>`, `/captures/<filename>` back a single-page UI. Only sees what's still on local disk — captures the nightly S3 job has archived-and-deleted are gone from the viewer too.

Module dependency flow: `main.py` → `capture.py`, `recognition.py`, `presence.py`, `storage.py`, `obsbot.py`, `lockscreen.py` (lazy-imported), `config.py`. Everything reads from `Config` dataclass.

Key modules:
- `config.py` — `Config` dataclass with all defaults. CLI args override fields.
- `capture.py` — `take_screenshot` (mss→PIL→JPEG), `take_webcam_picture` (opencv), `detect_face` (haar cascade). Both capture functions return `(Path, np.ndarray)` so debug UI can display them.
- `recognition.py` — `is_recognized` compares webcam frame against enrolled 128-dim dlib encodings. Returns `True`/`False`/`None` (no face). Falls back to detection-only if no enrollments exist.
- `presence.py` — `PresenceTracker` debounces per-tick recognition results into a lock/unlock decision, requiring `presence_confirm_ticks` consecutive same-direction ticks before firing. `main.py`'s `AppState` uses this so hooks/overlay/tracking only fire on state transitions, not every tick.
- `lockscreen.py` — `LockOverlay`: a fullscreen, grabbed, always-on-top Tk window run on its own thread (communicated with via a `queue.Queue`, since Tk isn't thread-safe otherwise). Not a real session lock — see README for why (panic hotkey + passphrase always bypass it, so misbehaving recognition can't strand you behind a login screen).
- `obsbot.py` — drives `obsbot-cli -i`'s interactive stdin menu (see `obsbot-camera-control`'s `meet2_test.cpp::runInteractiveMode`) to toggle AI person-tracking. Doesn't touch the user's saved `settings.conf`.
- `s3_archive.py` — `find_archivable` (pure, testable) + `archive_once` (shells out to `aws s3 cp` per file, so one failed upload doesn't block others from being deleted).
- `storage.py` — `prune_old_files` deletes oldest JPEGs when storage exceeds `max_history_mb`.

## Gotchas

- `face_recognition` depends on dlib (needs `cmake` to build) and uses `pkg_resources`, requiring `setuptools<82` pin.
- The systemd service expects `pystory` at `~/.local/bin/pystory` — install with `uv tool install .`.
- Captures are saved as `{screenshot,webcam}_YYYYMMDD_HHMMSS.jpg`. The timelapse and pruning logic depend on this naming convention.
- `capture.py`'s `cv2.CascadeClassifier` usage breaks on opencv-python 5.0+ (the symbol moved); this repo's pin (`opencv-python>=4.10`) is meant to avoid that, but if your index only serves 5.x you'll hit `AttributeError: module 'cv2' has no attribute 'CascadeClassifier'` on import. Pre-existing, not introduced by any of the features above.
- `LockOverlay` uses `grab_set_global()`, which can raise `TclError: grab failed` if another Tk grab is still held (e.g. a previous crashed test process). Don't smoke-test it against a live/shared display — a stuck global grab blocks real keyboard/mouse input city-wide until the holding process exits.
- `obsbot.py` assumes `obsbot-cli` is installed and a camera is connected; both `enable_tracking`/`disable_tracking` log and return `False` on failure rather than raising, so a missing camera doesn't take down the capture loop.
- `cv2.VideoCapture` opens `config.webcam_device` (default `0`, overridable via `--webcam-device` on `pystory` and `pystory-enroll`), not necessarily the camera you want — with more than one attached, `0` is whichever the OS enumerates first, often the laptop's built-in one rather than an external OBSBOT.
- `recognition.py` converts BGR→RGB with `np.ascontiguousarray(frame[:, :, ::-1])`, not a bare slice: `[:, :, ::-1]` alone returns a negative-stride view, and dlib's pybind11 binding rejects that with a `TypeError: incompatible function arguments` that reads like a signature mismatch rather than a memory-layout one.
