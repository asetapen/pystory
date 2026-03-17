from pathlib import Path

from pystory.config import Config


def get_storage_size_mb(config: Config) -> float:
    total = sum(f.stat().st_size for f in config.storage_dir.glob("*.jpg") if f.is_file())
    return total / (1024 * 1024)


def prune_old_files(config: Config) -> int:
    """Delete oldest files until storage is under the max. Returns number of files deleted."""
    deleted = 0
    while get_storage_size_mb(config) > config.max_history_mb:
        files = sorted(config.storage_dir.glob("*.jpg"), key=lambda f: f.stat().st_mtime)
        if not files:
            break
        files[0].unlink()
        deleted += 1
    return deleted
