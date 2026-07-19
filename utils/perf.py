"""Lightweight performance timing.

A single ``timer`` context manager used to measure where time goes (tab loads,
database queries, image decoding). It is **off by default** and adds no overhead
unless enabled, so it can stay in the code permanently:

    set PHOTOSPHERE_PERF=1          # Windows
    export PHOTOSPHERE_PERF=1       # Linux/macOS

When enabled, timings are logged (to console + ``logs/photosphere.log``) under
the ``photosphere.perf`` logger:

    with timer("tab.people.refresh"):
        ...                         # -> "PERF tab.people.refresh: 0.412s"
"""

from __future__ import annotations

import os
import time
from contextlib import contextmanager
from typing import Iterator

from utils.logging_setup import get_logger

logger = get_logger("perf")


def perf_enabled() -> bool:
    """Return True if performance timing is switched on via the environment."""
    return os.environ.get("PHOTOSPHERE_PERF", "").strip().lower() in ("1", "true", "yes", "on")


@contextmanager
def timer(name: str) -> Iterator[None]:
    """Time the wrapped block and log it — a no-op unless PHOTOSPHERE_PERF is set."""
    if not perf_enabled():
        yield
        return
    start = time.perf_counter()
    try:
        yield
    finally:
        logger.info("PERF %s: %.3fs", name, time.perf_counter() - start)
