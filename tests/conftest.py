"""Shared pytest fixtures for PhotoSphere AI tests."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest
from PIL import Image


def _make_exif_image(path: Path) -> None:
    """Write a small JPEG carrying camera, capture-time and GPS EXIF."""
    exif = Image.Exif()
    exif[0x010F] = "TestMake"       # Make
    exif[0x0110] = "TestModel"      # Model
    exif[0x0112] = 1                # Orientation
    exif[0x8769] = {0x9003: "2021:07:04 12:34:56"}  # Exif IFD: DateTimeOriginal
    exif[0x8825] = {               # GPS IFD: 37°46'30"N, 122°25'10"W
        1: "N", 2: (37.0, 46.0, 30.0),
        3: "W", 4: (122.0, 25.0, 10.0),
    }
    Image.new("RGB", (200, 150), "green").save(path, "JPEG", exif=exif)


@pytest.fixture
def photo_tree(tmp_path: Path) -> Path:
    """Create a directory tree of fixtures and return its root.

    Contents:
      * a.jpg              plain JPEG
      * sub/b.png          plain PNG
      * sub/a_copy.jpg     byte-identical duplicate of a.jpg
      * with_exif.jpg      JPEG with camera/time/GPS EXIF
      * broken.jpg         invalid bytes but .jpg extension (identity only)
      * notes.txt          non-image, must be ignored
    """
    root = tmp_path / "photos"
    (root / "sub").mkdir(parents=True)

    Image.new("RGB", (120, 80), "red").save(root / "a.jpg", "JPEG")
    Image.new("RGB", (64, 64), "blue").save(root / "sub" / "b.png", "PNG")
    shutil.copy(root / "a.jpg", root / "sub" / "a_copy.jpg")
    _make_exif_image(root / "with_exif.jpg")
    (root / "broken.jpg").write_bytes(b"not really a jpeg")
    (root / "notes.txt").write_text("ignore me")

    return root
