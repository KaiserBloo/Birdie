from __future__ import annotations

from pathlib import Path

from PIL import Image

from birdie.image_processing import build_roi, crop_image_to_roi


def test_build_roi_clamps_to_image_bounds() -> None:
    roi = build_roi(
        {"x": 0.25, "y": 0.25, "width": 0.5, "height": 0.5},
        x=0.9,
        y=-1,
        width=0.5,
        height=2,
    )

    assert roi == {"x": 0.9, "y": 0.0, "width": 0.1, "height": 1.0}


def test_crop_image_to_roi_writes_jpeg_crop(tmp_path: Path) -> None:
    source = tmp_path / "source.jpg"
    destination = tmp_path / "crop.jpg"
    Image.new("RGB", (100, 80), color=(150, 120, 90)).save(source)

    result = crop_image_to_roi(
        source,
        destination,
        {"x": 0.25, "y": 0.25, "width": 0.5, "height": 0.5},
    )

    assert result == destination
    with Image.open(destination) as crop:
        assert crop.size == (50, 40)


def test_crop_image_to_roi_ignores_invalid_image(tmp_path: Path) -> None:
    source = tmp_path / "not-an-image.jpg"
    destination = tmp_path / "crop.jpg"
    source.write_text("nope", encoding="utf-8")

    result = crop_image_to_roi(
        source,
        destination,
        {"x": 0.25, "y": 0.25, "width": 0.5, "height": 0.5},
    )

    assert result is None
    assert not destination.exists()
