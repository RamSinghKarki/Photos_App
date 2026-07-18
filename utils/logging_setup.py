"""Logging configuration for PhotoSphere AI.

Every module logs through Python's standard :mod:`logging`. Logs go to two
places at once — a rotating file at ``logs/photosphere.log`` and the console —
so that errors are never lost and are also visible while a scan runs.

Call :func:`setup_logging` once at the start of any entry point (CLI script,
API server, UI launcher). Library modules should *not* call it; they simply do
``logger = logging.getLogger(__name__)`` and inherit this configuration.
"""

from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path

from config.settings import get_settings

_LOG_FORMAT = "%(asctime)s %(levelname)-8s %(name)s: %(message)s"
_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"
_LOG_FILENAME = "photosphere.log"

# Guard so repeated calls (e.g. tests, re-entrant entry points) don't attach
# duplicate handlers that would double every log line.
_CONFIGURED = False


def setup_logging(level: str | None = None) -> logging.Logger:
    """Configure root logging to write to both file and console.

    Args:
        level: Optional level name (e.g. ``"DEBUG"``). Falls back to the
            configured ``log_level`` setting when omitted.

    Returns:
        The application root logger (``"photosphere"``).
    """
    global _CONFIGURED

    settings = get_settings()
    settings.ensure_directories()
    effective_level = (level or settings.log_level).upper()

    root = logging.getLogger()
    root.setLevel(effective_level)

    if not _CONFIGURED:
        formatter = logging.Formatter(_LOG_FORMAT, datefmt=_DATE_FORMAT)

        # Rotate at 5 MB, keep 5 backups, so the log can never fill the disk.
        file_path: Path = settings.logs_dir / _LOG_FILENAME
        file_handler = RotatingFileHandler(
            file_path, maxBytes=5 * 1024 * 1024, backupCount=5, encoding="utf-8"
        )
        file_handler.setFormatter(formatter)
        root.addHandler(file_handler)

        console_handler = logging.StreamHandler()
        console_handler.setFormatter(formatter)
        root.addHandler(console_handler)

        _CONFIGURED = True

    return logging.getLogger("photosphere")


def get_logger(name: str) -> logging.Logger:
    """Return a module-scoped logger under the ``photosphere`` namespace."""
    return logging.getLogger(f"photosphere.{name}")
