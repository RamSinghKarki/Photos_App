"""Central Pillow configuration for decoding the user's own photos.

Pillow's decompression-bomb guard (``MAX_IMAGE_PIXELS`` ≈ 89 MP, a hard error
above 2×) exists to protect *servers* from hostile uploads. PhotoSphere decodes
the user's **own** local files, where a 100–200 MP panorama or a flatbed scan is
an ordinary photo — not an attack — so the guard would wrongly abort an import.

We raise the limit to a generous, overridable cap so real large photos decode
normally, while a genuinely absurd size still raises (and the decoders skip that
one file rather than crashing the pipeline).
"""

from __future__ import annotations

import os
import warnings

from PIL import Image

_DEFAULT_MAX_PIXELS = 512_000_000  # ~512 MP — covers big panoramas / scans
_configured = False


def configure_pillow() -> None:
    """Raise Pillow's pixel limit for the user's own photos (idempotent).

    Honours ``PHOTOSPHERE_MAX_IMAGE_PIXELS`` (an integer; ``0`` disables the
    limit entirely). Safe to call from every entry point — the work is done
    once.
    """
    global _configured
    if _configured:
        return
    raw = os.environ.get("PHOTOSPHERE_MAX_IMAGE_PIXELS", "").strip()
    try:
        cap = int(raw) if raw else _DEFAULT_MAX_PIXELS
    except ValueError:
        cap = _DEFAULT_MAX_PIXELS
    Image.MAX_IMAGE_PIXELS = None if cap <= 0 else cap
    # Between MAX and 2×MAX Pillow only warns; we've chosen the cap on purpose,
    # so silence that warning. A size above the cap still raises and is skipped.
    warnings.simplefilter("ignore", Image.DecompressionBombWarning)
    _configured = True
