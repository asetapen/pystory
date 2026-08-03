import argparse
import logging
import subprocess
import time
from pathlib import Path

from pystory.config import Config

log = logging.getLogger("pystory.s3_archive")


def _age_seconds(path: Path) -> float:
    return time.time() - path.stat().st_mtime


def find_archivable(storage_dir: Path, min_age_seconds: int) -> list[Path]:
    files = []
    for pattern in ("screenshot_*.jpg", "webcam_*.jpg"):
        files.extend(storage_dir.glob(pattern))
    return [f for f in files if _age_seconds(f) >= min_age_seconds]


def archive_once(config: Config) -> int:
    """Upload archivable captures to S3 and (optionally) delete local copies.

    Returns the number of files archived. Uses one `aws s3 cp` invocation
    per file rather than a bulk sync, so partial failures don't block
    already-uploaded files from being deleted.
    """
    if not config.s3_archive_uri:
        log.error("s3_archive_uri is not configured, nothing to do")
        return 0

    dest = config.s3_archive_uri.rstrip("/") + "/"
    files = find_archivable(config.storage_dir, config.s3_archive_min_age_seconds)
    if not files:
        log.info("No files old enough to archive")
        return 0

    archived = 0
    for f in files:
        try:
            subprocess.run(
                ["aws", "s3", "cp", str(f), dest + f.name],
                check=True,
                capture_output=True,
                text=True,
                timeout=60,
            )
        except subprocess.CalledProcessError as e:
            log.error("Upload failed for %s: %s", f, e.stderr.strip())
            continue
        except subprocess.SubprocessError as e:
            log.error("Upload failed for %s: %s", f, e)
            continue

        archived += 1
        if config.s3_archive_delete_after_upload:
            f.unlink(missing_ok=True)

    log.info("Archived %d/%d file(s) to %s", archived, len(files), dest)
    return archived


def parse_args() -> tuple[Config, bool, int]:
    p = argparse.ArgumentParser(description="Upload pystory captures to S3 and clear local storage")
    p.add_argument("--storage-dir", type=Path, help="Where captures are stored")
    p.add_argument("--s3-uri", type=str, required=True, help="Destination, e.g. s3://my-bucket/pystory/")
    p.add_argument("--min-age", type=int, help="Only archive files at least this many seconds old")
    p.add_argument("--keep-local", action="store_true", help="Upload but don't delete local copies")
    p.add_argument("--interval", type=int, help="Run repeatedly every N seconds instead of once")
    args = p.parse_args()

    config = Config()
    if args.storage_dir:
        config.storage_dir = args.storage_dir
    config.s3_archive_uri = args.s3_uri
    if args.min_age is not None:
        config.s3_archive_min_age_seconds = args.min_age
    if args.keep_local:
        config.s3_archive_delete_after_upload = False
    interval = args.interval or 0
    return config, bool(args.interval), interval


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
    )

    config, loop, interval = parse_args()

    if not loop:
        archive_once(config)
        return

    log.info("Archiving every %ds to %s", interval, config.s3_archive_uri)
    while True:
        try:
            archive_once(config)
        except Exception as e:
            log.error("Archive pass failed: %s", e)
        time.sleep(interval)


if __name__ == "__main__":
    main()
