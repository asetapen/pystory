# pystory

Periodically captures screenshots and webcam pictures. If no face is detected in the webcam frame, a configurable hook runs — by default, it locks your screen via `loginctl lock-session`.

Targets Ubuntu 24.

## Install

```bash
./install.sh
```

This installs system dependencies (`cmake`, `build-essential`, `python3-dev`), [uv](https://docs.astral.sh/uv/getting-started/installation/) if needed, and Python packages.

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
| `--no-face-recognition` | | Use detection only (any face prevents locking) |
| `--face-tolerance` | `0.6` | Face match tolerance (lower = stricter) |
| `--no-screenshot` | | Disable screenshot capture |
| `--no-webcam` | | Disable webcam capture |
| `--debug-ui` | | Show live preview windows (press `q` to quit) |
| `--presence-confirm-ticks` | `2` | Consecutive same-result ticks needed before locking/unlocking |
| `--lock-overlay` | | Show a fullscreen block overlay in addition to `--no-face-hook` |
| `--lock-passphrase` | | Passphrase that dismisses the lock overlay |
| `--lock-panic-hotkey` | `<Control-Alt-Escape>` | Tk keysym that force-dismisses the overlay |
| `--obsbot-tracking` | | Enable/disable OBSBOT AI person-tracking based on presence |
| `--obsbot-cli-path` | `obsbot-cli` | Path to the `obsbot-cli` binary |

## Face Recognition

By default, pystory uses face recognition so only *your* face prevents the screen from locking. First, enroll your face:

```bash
# capture 5 samples (press SPACE for each, Q to finish early)
uv run pystory-enroll

# or capture more samples for better accuracy
uv run pystory-enroll --samples 10

# re-enroll from scratch
uv run pystory-enroll --reset
```

Once enrolled, pystory will lock the screen if it sees no face *or* an unrecognized face. If no faces are enrolled, it falls back to detection-only mode (any face prevents locking).

To disable recognition and use detection-only mode explicitly:

```bash
uv run pystory --no-face-recognition
```

### Making recognition reliable

`pystory-enroll` auto-captures samples (default 8) as you follow on-screen pose
prompts (straight, left, right, chin up, chin down) — no manual keypress
needed, which makes it easy to actually capture a good variety of angles.
More/varied samples means fewer false "not recognized" hits day-to-day.

On top of that, `pystory` debounces recognition results with
`--presence-confirm-ticks` (default 2): a single bad frame (glare, a quick
look away) won't lock or unlock anything by itself — it takes N consecutive
same-direction ticks. Raise it if you get spurious locks; lower it (to `1`)
for instant response.

## Desk auto-lock overlay

`--lock-overlay` shows a fullscreen, grabbed, always-on-top window when
you're not recognized, and hides it the moment you're recognized again —
driven by the same debounced presence signal as `--no-face-hook`.

```bash
uv run pystory --lock-overlay --lock-passphrase "supersecret"
```

This is **not** a real session lock (no `loginctl`, no greeter) — it's a
grabbed Tk window that blocks casual keyboard/mouse use. That's intentional:
a real lock screen can leave you stuck behind a login prompt if recognition
misbehaves while you're away. The overlay instead gives you two guaranteed
ways out:

- Type `--lock-passphrase` into the on-screen field and press Enter.
- Press the panic hotkey (`--lock-panic-hotkey`, default `Ctrl+Alt+Escape`) —
  bound at all times, bypasses recognition entirely.

As a last resort, killing the `pystory` process (e.g. over SSH) removes the
overlay outright. For an actual locked session (not just a blocked desktop),
keep using the default `--no-face-hook` (`loginctl lock-session`) alongside
or instead of `--lock-overlay`.

## OBSBOT camera tracking

If you have an [OBSBOT camera](https://www.obsbot.com/) and
[obsbot-camera-control](https://github.com/aaronsb/obsbot-camera-control)
installed (providing `obsbot-cli`), `--obsbot-tracking` turns the camera's
AI person-tracking on while you're present and off while you're away:

```bash
uv run pystory --obsbot-tracking --obsbot-cli-path ~/.local/bin/obsbot-cli
```

Tracking mode/sub-mode are configurable via `Config.obsbot_ai_mode` /
`obsbot_ai_sub_mode` (defaults: Single Human Tracking, Upper Body). This
drives `obsbot-cli -i`'s interactive AI-mode menu directly; it does not
modify your saved `~/.config/obsbot-control/settings.conf`.

## Archiving captures to S3

`pystory-s3-archive` uploads captures older than a configurable age to S3
and (by default) deletes the local copy, so a long-running box doesn't fill
up with old JPEGs before `--max-history-mb` pruning kicks in remotely.

```bash
# one-shot: archive everything older than 10 minutes (the default)
uv run pystory-s3-archive --s3-uri s3://my-bucket/pystory-captures/

# keep local copies after upload
uv run pystory-s3-archive --s3-uri s3://my-bucket/pystory-captures/ --keep-local

# run forever, archiving every hour
uv run pystory-s3-archive --s3-uri s3://my-bucket/pystory-captures/ --interval 3600
```

| Flag | Default | Description |
|------|---------|-------------|
| `--storage-dir` | `~/.pystory` | Where captures are stored |
| `--s3-uri` | *(required)* | Destination prefix, e.g. `s3://my-bucket/pystory/` |
| `--min-age` | `600` | Only archive files at least this many seconds old |
| `--keep-local` | | Upload but don't delete local copies |
| `--interval` | | Run repeatedly every N seconds instead of once |

Requires the `aws` CLI on `PATH` and configured credentials (`aws configure`
or an instance/role profile) with `s3:PutObject` on the destination bucket.
To run it periodically without keeping a process alive, install it as a
systemd timer:

```bash
cp sys/pystory-s3-archive.service sys/pystory-s3-archive.timer ~/.config/systemd/user/
# edit the --s3-uri in the installed .service file first
systemctl --user daemon-reload
systemctl --user enable --now pystory-s3-archive.timer
```

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
