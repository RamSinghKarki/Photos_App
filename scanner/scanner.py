"""Module 1 — Scanner.

Walks a directory tree, extracts metadata for each supported image, and stores
it in PostgreSQL. This is the foundation every later module builds on: faces,
clustering, search, and the timeline all read from the ``photos`` rows created
here.

Design choices that follow the project rules:
  * **Streaming, not slurping.** Files are yielded by a generator and processed
    one at a time; the tree is never materialised into a giant list, so the
    scan scales to hundreds of thousands of photos without growing RAM.
  * **Never crash on one bad file.** Every per-file error is caught, logged,
    and counted; the scan keeps going.
  * **Idempotent + dedup-aware.** Re-scanning skips paths already stored, and
    byte-identical files (same SHA-256) are counted as duplicates.
  * **Batched transactions.** Rows commit in configurable batches so a large
    scan is durable in chunks and a crash loses at most one batch.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterator, Optional

from config.settings import get_settings
from database import db
from scanner.metadata import extract_metadata
from utils.imaging import configure_pillow
from utils.logging_setup import get_logger

# Called periodically with (items_seen, total). total == 0 means indeterminate
# (the scanner streams the tree and does not know the count in advance).
ProgressCallback = Callable[[int, int], None]

logger = get_logger("scanner")


@dataclass
class ScanSummary:
    """Counters describing the outcome of a scan, shown to the user at the end."""

    processed: int = 0
    skipped: int = 0
    duplicates: int = 0
    errors: int = 0

    def render(self) -> str:
        """Return the human-readable summary block."""
        return (
            "\n"
            f"Processed:   {self.processed}\n"
            f"Skipped:     {self.skipped}\n"
            f"Duplicates:  {self.duplicates}\n"
            f"Errors:      {self.errors}"
        )


def iter_image_files(root: Path) -> Iterator[Path]:
    """Yield image files under ``root`` one at a time.

    Non-image files are filtered by extension. The walk is lazy (a generator)
    so memory stays flat regardless of tree size.
    """
    extensions = get_settings().image_extensions
    for path in root.rglob("*"):
        try:
            if path.is_file() and path.suffix.lower() in extensions:
                yield path
        except OSError as exc:
            # e.g. a broken symlink or permission error on stat().
            logger.warning("Cannot access %s: %s", path, exc)


def scan_directory(
    root: Path,
    batch_size: Optional[int] = None,
    on_progress: Optional[ProgressCallback] = None,
) -> ScanSummary:
    """Scan ``root`` recursively and store new photos, returning a summary.

    Args:
        root: Directory to scan.
        batch_size: Rows to commit per transaction; defaults to the configured
            ``scan_batch_size``.

    Raises:
        FileNotFoundError: if ``root`` is not an existing directory.
    """
    configure_pillow()  # allow the user's large panoramas/scans to decode
    root = root.expanduser().resolve()
    if not root.is_dir():
        raise FileNotFoundError(f"Scan root is not a directory: {root}")

    effective_batch = batch_size or get_settings().scan_batch_size
    summary = ScanSummary()

    db.apply_schema()  # idempotent; guarantees tables exist before we write.

    with db.connection() as conn, conn.cursor() as cur:
        run_id = db.start_scan_run(cur, str(root))
        conn.commit()  # persist the run start immediately for auditability.

        pending = 0
        seen = 0
        for path in iter_image_files(root):
            seen += 1
            if on_progress is not None and seen % 25 == 0:
                on_progress(seen, 0)  # total unknown -> indeterminate
            try:
                if db.photo_path_exists(cur, str(path)):
                    # Already scanned in a previous run — nothing to do.
                    summary.skipped += 1
                    continue

                meta = extract_metadata(path)

                is_duplicate = db.hash_exists(cur, meta.file_hash)
                photo_id = db.insert_photo(cur, meta)

                if photo_id is None:
                    # Lost a race / concurrent path conflict — treat as skip.
                    summary.skipped += 1
                    continue

                summary.processed += 1
                if is_duplicate:
                    # Stored (different path) but content already seen elsewhere.
                    summary.duplicates += 1

                pending += 1
                if pending >= effective_batch:
                    conn.commit()
                    pending = 0
                    logger.info("Committed batch; processed so far: %d", summary.processed)

            except OSError as exc:
                summary.errors += 1
                logger.error("Failed to read %s: %s", path, exc)
            except Exception as exc:  # noqa: BLE001 - keep scanning past any file
                summary.errors += 1
                logger.error("Unexpected error on %s: %s", path, exc)

        conn.commit()  # flush the final partial batch.
        db.finish_scan_run(
            cur,
            run_id,
            processed=summary.processed,
            skipped=summary.skipped,
            duplicates=summary.duplicates,
            errors=summary.errors,
        )

    logger.info("Scan complete for %s", root)
    return summary
