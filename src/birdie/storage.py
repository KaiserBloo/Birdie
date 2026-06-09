from __future__ import annotations

from datetime import datetime
from pathlib import Path

from fastapi import UploadFile

IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp"}
VIDEO_EXTENSIONS = {".mp4", ".mov", ".webm", ".mkv"}


def event_directory(media_dir: Path, event_id: str, timestamp: datetime) -> Path:
    return media_dir / timestamp.date().isoformat() / event_id


async def save_upload(
    upload: UploadFile,
    *,
    target_dir: Path,
    stem: str,
    allowed_extensions: set[str],
    default_extension: str,
) -> Path:
    target_dir.mkdir(parents=True, exist_ok=True)
    extension = Path(upload.filename or "").suffix.lower()
    if extension not in allowed_extensions:
        extension = default_extension

    destination = target_dir / f"{stem}{extension}"
    total = 0
    with destination.open("wb") as output:
        while True:
            chunk = await upload.read(1024 * 1024)
            if not chunk:
                break
            total += len(chunk)
            output.write(chunk)

    if total == 0:
        destination.unlink(missing_ok=True)
        raise ValueError("uploaded file was empty")
    return destination


def relative_media_path(media_dir: Path, path: Path | None) -> str | None:
    if path is None:
        return None
    return path.resolve().relative_to(media_dir.resolve()).as_posix()


def resolve_media_path(media_dir: Path, relative_path: str) -> Path:
    root = media_dir.resolve()
    candidate = (root / relative_path).resolve()
    if root != candidate and root not in candidate.parents:
        raise ValueError("media path escapes storage root")
    return candidate
