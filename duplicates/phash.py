"""Perceptual hashing (dHash) for visual duplicate detection.

A dHash reduces an image to a 64-bit gradient fingerprint: resize to 9×8
grayscale, then each bit records whether a pixel is brighter than its right
neighbour. Re-encoded, resized, or slightly edited copies of a photo produce
identical or near-identical hashes, while different photos differ in many
bits. Distance is the Hamming distance between the two 64-bit values.

Pure Pillow + stdlib — no new dependencies, works with no GPU.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional, Union

from PIL import Image

HASH_BITS = 64
_SIZE = (9, 8)  # (width+1, height) -> 8x8 comparisons = 64 bits


def dhash(image: Union[Image.Image, Path, str]) -> Optional[int]:
    """Return the 64-bit dHash of an image, or None if it cannot be decoded."""
    try:
        img = image if isinstance(image, Image.Image) else Image.open(image)
        gray = img.convert("L").resize(_SIZE, Image.Resampling.LANCZOS)
    except Exception:  # noqa: BLE001 - unreadable file -> simply unhashable
        return None
    pixels = list(gray.getdata())
    width = _SIZE[0]
    value = 0
    for row in range(_SIZE[1]):
        for col in range(width - 1):
            left = pixels[row * width + col]
            right = pixels[row * width + col + 1]
            value = (value << 1) | (1 if left > right else 0)
    return value


def hamming(a: int, b: int) -> int:
    """Number of differing bits between two 64-bit hashes."""
    return ((a ^ b) & (2**HASH_BITS - 1)).bit_count()


def to_signed(value: int) -> int:
    """Map an unsigned 64-bit hash into BIGINT range for storage."""
    return value - 2**64 if value >= 2**63 else value


def from_signed(value: int) -> int:
    """Inverse of :func:`to_signed`."""
    return value + 2**64 if value < 0 else value
