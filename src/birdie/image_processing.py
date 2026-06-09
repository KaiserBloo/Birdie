from __future__ import annotations

from pathlib import Path
from typing import Any

from PIL import Image, ImageOps, UnidentifiedImageError

ROI_MIN_SIZE = 0.01


def build_roi(
    default_roi: dict[str, float],
    *,
    x: float | None = None,
    y: float | None = None,
    width: float | None = None,
    height: float | None = None,
) -> dict[str, float]:
    roi = {
        "x": float(default_roi["x"] if x is None else x),
        "y": float(default_roi["y"] if y is None else y),
        "width": float(default_roi["width"] if width is None else width),
        "height": float(default_roi["height"] if height is None else height),
    }
    return clamp_roi(roi)


def clamp_roi(roi: dict[str, Any]) -> dict[str, float]:
    x = _clamp(float(roi.get("x", 0.0)), 0.0, 1.0 - ROI_MIN_SIZE)
    y = _clamp(float(roi.get("y", 0.0)), 0.0, 1.0 - ROI_MIN_SIZE)
    width = _clamp(float(roi.get("width", 1.0)), ROI_MIN_SIZE, 1.0 - x)
    height = _clamp(float(roi.get("height", 1.0)), ROI_MIN_SIZE, 1.0 - y)
    return {
        "x": round(x, 4),
        "y": round(y, 4),
        "width": round(width, 4),
        "height": round(height, 4),
    }


def crop_image_to_roi(image_path: Path, destination: Path, roi: dict[str, float]) -> Path | None:
    try:
        with Image.open(image_path) as image:
            image = ImageOps.exif_transpose(image)
            left, top, right, bottom = _roi_to_box(image.width, image.height, roi)
            if right <= left or bottom <= top:
                return None
            cropped = image.crop((left, top, right, bottom)).convert("RGB")
            destination.parent.mkdir(parents=True, exist_ok=True)
            cropped.save(destination, format="JPEG", quality=92, optimize=True)
            return destination
    except (OSError, UnidentifiedImageError, ValueError):
        return None


def _roi_to_box(width: int, height: int, roi: dict[str, float]) -> tuple[int, int, int, int]:
    clamped = clamp_roi(roi)
    left = round(clamped["x"] * width)
    top = round(clamped["y"] * height)
    right = round((clamped["x"] + clamped["width"]) * width)
    bottom = round((clamped["y"] + clamped["height"]) * height)
    return (
        _clamp_int(left, 0, max(width - 1, 0)),
        _clamp_int(top, 0, max(height - 1, 0)),
        _clamp_int(right, 1, width),
        _clamp_int(bottom, 1, height),
    )


def _clamp(value: float, minimum: float, maximum: float) -> float:
    return max(minimum, min(value, maximum))


def _clamp_int(value: int, minimum: int, maximum: int) -> int:
    return max(minimum, min(value, maximum))
