# pystory

Periodically captures screenshots and webcam pictures. If no face is detected in the webcam frame, a configurable hook runs — by default, it locks your screen via `loginctl lock-session`.

Targets Ubuntu 24.

## Install

Requires [uv](https://docs.astral.sh/uv/getting-started/installation/).

```bash
uv sync
```

## Usage

```bash
uv run pystory
```

All options have sensible defaults. Override with flags:

```bash
uv run pystory \
  --interval 10 \
  --storage-dir ~/my-captures \
  --quality 70 \
  --max-dimension 1920 \
  --max-history-mb 1000 \
  --no-face-hook "notify-send 'No face detected'"
```

| Flag | Default | Description |
|------|---------|-------------|
| `--storage-dir` | `~/.pystory` | Where captures are saved |
| `--interval` | `5` | Seconds between captures |
| `--quality` | `50` | JPEG quality (1-100) |
| `--max-dimension` | `1280` | Max image width or height in pixels |
| `--max-history-mb` | `500` | Prunes oldest files when exceeded |
| `--no-face-hook` | `loginctl lock-session` | Command to run when no face is detected |
| `--no-face-detection` | | Disable face detection entirely |
| `--no-screenshot` | | Disable screenshot capture |
| `--no-webcam` | | Disable webcam capture |
| `--debug-ui` | | Show live preview windows (press `q` to quit) |

## Debug UI

Run with `--debug-ui` to open OpenCV windows showing the latest screenshot and webcam frame after each capture. Useful for verifying camera angle and face detection.

```bash
uv run pystory --debug-ui
```

Press `q` in any preview window to quit.

## Timelapse

Generate timelapse videos from your captured images:

```bash
# both webcam and screenshot timelapses
uv run pystory-timelapse

# just webcam
uv run pystory-timelapse --type webcam

# custom fps and resolution
uv run pystory-timelapse --type screenshot --fps 60 --width 1920

# specify output path
uv run pystory-timelapse --type webcam --output ~/my-timelapse.mp4
```

| Flag | Default | Description |
|------|---------|-------------|
| `--storage-dir` | `~/.pystory` | Where captures are stored |
| `--type` | `both` | `webcam`, `screenshot`, or `both` |
| `--output` | `<storage-dir>/timelapse_<type>.mp4` | Output video path |
| `--fps` | `30` | Frames per second |
| `--width` | original | Output video width (height scales proportionally) |

## Run as a systemd user service

```bash
mkdir -p ~/.config/systemd/user
cp sys/pystory.service ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now pystory
```

Check status:

```bash
systemctl --user status pystory
journalctl --user -u pystory -f
```

Note: the service expects `pystory` to be on your PATH at `~/.local/bin/pystory`. You can install it there with:

```bash
uv tool install .
```
