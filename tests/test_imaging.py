"""Large-image handling: raise Pillow's bomb limit for the user's own photos,
and skip a genuinely over-limit image instead of aborting the pipeline."""

from __future__ import annotations

from pathlib import Path

import pytest
from PIL import Image

import utils.imaging as im


def _restore(saved) -> None:
    Image.MAX_IMAGE_PIXELS = saved
    im._configured = False
    im.configure_pillow()   # leave the suite with the normal raised default


def test_configure_pillow_raises_limit_and_env_override(monkeypatch) -> None:
    saved = Image.MAX_IMAGE_PIXELS
    try:
        im._configured = False
        monkeypatch.delenv("PHOTOSPHERE_MAX_IMAGE_PIXELS", raising=False)
        im.configure_pillow()
        assert Image.MAX_IMAGE_PIXELS == im._DEFAULT_MAX_PIXELS   # ~512 MP
        assert im._DEFAULT_MAX_PIXELS > 199_756_800               # the crash size

        im._configured = False
        monkeypatch.setenv("PHOTOSPHERE_MAX_IMAGE_PIXELS", "250000000")
        im.configure_pillow()
        assert Image.MAX_IMAGE_PIXELS == 250_000_000

        im._configured = False
        monkeypatch.setenv("PHOTOSPHERE_MAX_IMAGE_PIXELS", "0")   # 0 disables
        im.configure_pillow()
        assert Image.MAX_IMAGE_PIXELS is None
    finally:
        _restore(saved)


def test_oversized_image_skipped_not_fatal(photo_tree: Path) -> None:
    """A decode above the cap must convert to a skippable UnreadableImageError,
    never the raw DecompressionBombError that aborted the whole import."""
    from faces.processor import UnreadableImageError, _decode_photo

    saved = Image.MAX_IMAGE_PIXELS
    Image.MAX_IMAGE_PIXELS = 1   # any real image now "exceeds" the limit
    try:
        with pytest.raises(UnreadableImageError):
            _decode_photo(str(photo_tree / "a.jpg"))
        # sanity: with the limit restored it decodes fine
        Image.MAX_IMAGE_PIXELS = saved
        img, arr = _decode_photo(str(photo_tree / "a.jpg"))
        assert arr.ndim == 3
    finally:
        _restore(saved)
