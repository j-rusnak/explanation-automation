from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

from techshort.domain.hashing import sha256_file
from techshort.domain.models import ReviewStatus
from techshort.domain.storage import ProjectStore, sanitize_filename

ALLOWED_AUDIO = {".wav", ".mp3", ".m4a", ".aac", ".flac", ".ogg", ".opus"}


def import_audio(store: ProjectStore, source: Path) -> Path:
    if not source.is_file() or source.suffix.lower() not in ALLOWED_AUDIO:
        raise ValueError("audio must be a regular FFmpeg-compatible audio file")
    if source.stat().st_size > 200 * 1024 * 1024:
        raise ValueError("audio exceeds the 200 MiB limit")
    filename = sanitize_filename(source.name)
    destination = store.path(f"audio/{sha256_file(source)[:12]}-{filename}")
    if not destination.exists():
        shutil.copyfile(source, destination)
    project = store.project()
    project.dependency_hashes["audio"] = sha256_file(destination)
    project.approvals.final = ReviewStatus.STALE
    project.downstream_valid = False
    store.save_project(project)
    return destination


def probe_duration(path: Path) -> float | None:
    ffprobe = shutil.which("ffprobe")
    if not ffprobe:
        return None
    result = subprocess.run(
        [
            ffprobe,
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "default=nw=1:nk=1",
            str(path),
        ],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    return float(result.stdout.strip()) if result.returncode == 0 else None
