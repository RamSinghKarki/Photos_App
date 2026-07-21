"""Filesystem locations that stay correct whether run from source or frozen.

Packaging with PyInstaller changes two assumptions a desktop app must respect:

* **Bundled resources** (e.g. the SQL schema) are unpacked to a temporary
  directory exposed as ``sys._MEIPASS`` — not next to the source file.
* **The install directory is read-only** (``C:\\Program Files`` on Windows), so
  generated data — thumbnails, face crops, logs, caches — must live in a
  per-user location, never beside the executable.

Run from source (development, tests) the original project-relative layout is
kept, so nothing about the dev workflow or the test suite changes.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

PROJECT_ROOT: Path = Path(__file__).resolve().parent.parent


def is_frozen() -> bool:
    """True when running from a PyInstaller (or similar) bundle."""
    return bool(getattr(sys, "frozen", False))


def resource_path(relative: str) -> Path:
    """Locate a read-only bundled resource, e.g. ``database/schema.sql``.

    Frozen: resolve under the bundle's extraction dir (``sys._MEIPASS``).
    Source: resolve under the project root.
    """
    base = Path(getattr(sys, "_MEIPASS", PROJECT_ROOT)) if is_frozen() else PROJECT_ROOT
    return base / relative


def user_data_dir() -> Path:
    """Writable base directory for generated artifacts (data, logs, cache).

    Honours ``PHOTOSPHERE_DATA_DIR``. A frozen install uses the OS-standard
    per-user location; running from source uses the project directory so
    development and the test suite are unaffected.
    """
    override = os.environ.get("PHOTOSPHERE_DATA_DIR", "").strip()
    if override:
        return Path(override)
    if not is_frozen():
        return PROJECT_ROOT
    if sys.platform.startswith("win"):
        base = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
        return Path(base) / "PhotoSphere"
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "PhotoSphere"
    xdg = os.environ.get("XDG_DATA_HOME", "").strip()
    return (Path(xdg) if xdg else Path.home() / ".local" / "share") / "PhotoSphere"
