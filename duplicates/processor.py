"""Batch perceptual-hash processor for the duplicates module.

Walks photos that have no phash yet, computes each dHash, and stores results
in batches. Unreadable files store a sentinel so they are processed exactly
once. Idempotent and resumable like every other stage: stopping mid-run loses
at most one uncommitted batch.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Optional

from database import db
from duplicates.phash import dhash, to_signed
from utils.imaging import configure_pillow
from utils.logging_setup import get_logger

logger = get_logger("duplicates.processor")

ProgressCallback = Callable[[int, int], None]


@dataclass
class PhashSummary:
    hashed: int = 0
    unreadable: int = 0


def process_phashes(
    on_progress: Optional[ProgressCallback] = None,
    batch_size: int = 200,
) -> PhashSummary:
    """Hash every un-hashed photo; returns counts."""
    configure_pillow()
    summary = PhashSummary()
    with db.connection() as conn, conn.cursor() as cur:
        total = db.count_photos_needing_phash(cur)
        done = 0
        while True:
            pending = db.list_photos_needing_phash(cur, limit=batch_size)
            if not pending:
                break
            rows: list[tuple[int, Optional[int]]] = []
            for photo_id, file_path in pending:
                value = dhash(file_path)
                if value is None:
                    summary.unreadable += 1
                    rows.append((photo_id, None))
                else:
                    summary.hashed += 1
                    rows.append((photo_id, to_signed(value)))
                done += 1
                if on_progress is not None and (done % 25 == 0 or done == total):
                    on_progress(done, total)
            db.set_phashes(cur, rows)
            conn.commit()
    return summary
