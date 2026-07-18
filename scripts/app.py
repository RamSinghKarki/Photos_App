"""Launch the PhotoSphere AI desktop application.

Usage::

    python -m scripts.app
"""

from __future__ import annotations

import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from viewer.app import run  # noqa: E402


if __name__ == "__main__":
    raise SystemExit(run())
