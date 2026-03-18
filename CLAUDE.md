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

# Enroll face for recognition
uv run pystory-enroll
uv run pystory-enroll --samples 10 --reset

# Generate timelapse videos
uv run pystory-timelapse --type webcam --fps 30

# Install as systemd user service
cp sys/pystory.service ~/.config/systemd/user/
systemctl --user enable --now pystory
```

## Architecture

All source is in `src/pystory/`. Three CLI entrypoints defined in `pyproject.toml [project.scripts]`:

- **`pystory`** → `main.py:main` — Main capture loop. Each tick: screenshot (mss) → webcam (opencv) → face check → hook if needed → prune old files. `--debug-ui` uses `cv2.imshow` with `cv2.waitKey` as the sleep mechanism.
- **`pystory-enroll`** → `enroll.py:main` — Interactive webcam enrollment. Captures face encodings via dlib and stores as JSON in `~/.pystory/face_encodings.json`.
- **`pystory-timelapse`** → `timelapse.py:main` — Reads stored JPEGs sorted by filename (embeds timestamp) and stitches into MP4 via `cv2.VideoWriter`.

Module dependency flow: `main.py` → `capture.py`, `recognition.py`, `storage.py`, `config.py`. Everything reads from `Config` dataclass.

Key modules:
- `config.py` — `Config` dataclass with all defaults. CLI args override fields.
- `capture.py` — `take_screenshot` (mss→PIL→JPEG), `take_webcam_picture` (opencv), `detect_face` (haar cascade). Both capture functions return `(Path, np.ndarray)` so debug UI can display them.
- `recognition.py` — `is_recognized` compares webcam frame against enrolled 128-dim dlib encodings. Returns `True`/`False`/`None` (no face). Falls back to detection-only if no enrollments exist.
- `storage.py` — `prune_old_files` deletes oldest JPEGs when storage exceeds `max_history_mb`.

## Gotchas

- `face_recognition` depends on dlib (needs `cmake` to build) and uses `pkg_resources`, requiring `setuptools<82` pin.
- The systemd service expects `pystory` at `~/.local/bin/pystory` — install with `uv tool install .`.
- Captures are saved as `{screenshot,webcam}_YYYYMMDD_HHMMSS.jpg`. The timelapse and pruning logic depend on this naming convention.
