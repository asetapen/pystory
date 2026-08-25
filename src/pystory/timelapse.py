import argparse
import logging
from pathlib import Path

import cv2

from pystory.config import Config
from pystory.main import bounded_int

log = logging.getLogger("pystory.timelapse")


def build_timelapse(images: list[Path], output: Path, fps: int, resolution: tuple[int, int] | None) -> None:
    if not images:
        log.error("No images found")
        return

    first = cv2.imread(str(images[0]))
    if first is None:
        log.error("Could not read %s", images[0])
        return

    if resolution is None:
        h, w = first.shape[:2]
        resolution = (w, h)

    output.parent.mkdir(parents=True, exist_ok=True)

    fourcc = cv2.VideoWriter_fourcc(*"mp4v")
    writer = cv2.VideoWriter(str(output), fourcc, fps, resolution)
    if not writer.isOpened():
        log.error("Could not open video writer for %s (fps=%d, resolution=%s)", output, fps, resolution)
        return

    for i, path in enumerate(images):
        frame = cv2.imread(str(path))
        if frame is None:
            log.warning("Skipping unreadable: %s", path)
            continue
        frame = cv2.resize(frame, resolution)
        writer.write(frame)
        if (i + 1) % 100 == 0:
            log.info("Processed %d / %d frames", i + 1, len(images))

    writer.release()
    log.info("Wrote %s (%d frames, %d fps)", output, len(images), fps)


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Generate timelapse videos from pystory captures")
    p.add_argument("--storage-dir", type=Path, default=Config().storage_dir,
                    help="Where captures are stored (default: ~/.pystory)")
    p.add_argument("--type", choices=["webcam", "screenshot", "both"], default="both",
                    help="Which captures to include (default: both)")
    p.add_argument("--output", type=Path,
                    help="Output video path, requires --type webcam or --type screenshot "
                         "(default: <storage-dir>/timelapse_<type>.mp4)")
    p.add_argument("--fps", type=bounded_int(1), default=30, help="Frames per second (default: 30)")
    p.add_argument("--width", type=int, help="Output video width (height scales proportionally)")
    args = p.parse_args()

    if args.output and args.type == "both":
        p.error("--output names one file, but --type both writes two; "
                "pass --type webcam or --type screenshot, or omit --output")

    return args


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
    )

    args = parse_args()

    prefixes = {
        "webcam": ["webcam_"],
        "screenshot": ["screenshot_"],
        "both": ["webcam_", "screenshot_"],
    }

    for prefix in prefixes[args.type]:
        kind = prefix.rstrip("_")
        images = sorted(args.storage_dir.glob(f"{prefix}*.jpg"))
        log.info("Found %d %s images", len(images), kind)

        if not images:
            continue

        output = args.output if args.output else args.storage_dir / f"timelapse_{kind}.mp4"

        resolution = None
        if args.width:
            sample = cv2.imread(str(images[0]))
            if sample is not None:
                h, w = sample.shape[:2]
                scale = args.width / w
                resolution = (args.width, int(h * scale))

        build_timelapse(images, output, args.fps, resolution)


if __name__ == "__main__":
    main()
