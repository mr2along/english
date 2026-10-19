"""Small helpers for short-lived files returned by Gradio callbacks."""

from __future__ import annotations

import threading
import time
from pathlib import Path
from typing import Iterable


def remove_stale_files(directory: str | Path, max_age_seconds: int) -> None:
    """Remove old regular files from a callback-owned temporary directory."""
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    now = time.time()
    for path in directory.iterdir():
        try:
            if path.is_file() and now - path.stat().st_mtime > max_age_seconds:
                path.unlink()
        except OSError:
            continue


def schedule_file_removal(paths: Iterable[str | Path], delay_seconds: int) -> None:
    """Remove generated source files after Gradio has had time to serve them."""
    captured_paths = tuple(Path(path) for path in paths)

    def remove():
        for path in captured_paths:
            try:
                path.unlink(missing_ok=True)
            except OSError:
                continue

    timer = threading.Timer(max(1, delay_seconds), remove)
    timer.daemon = True
    timer.start()
