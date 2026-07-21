"""Incremental OCR processing.

Runs OCR over photos that haven't been processed yet and stores the extracted
text in ``photos.ocr_text`` (empty string = processed, no text — so it isn't
retried). Streams server-side, commits in batches, is cancel-safe, and reports
progress. Feeds the unified search (text queries match OCR content).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Optional

from PIL import Image, UnidentifiedImageError

from config.settings import get_settings
from database import db
from ocr.backend import OcrBackend
from utils.logging_setup import get_logger
from utils.prefetch import prefetch

logger = get_logger("ocr")


@dataclass
class OcrSummary:
    """Outcome of an OCR run."""

    processed: int = 0      # images run through OCR
    with_text: int = 0      # images where text was found
    unreadable: int = 0     # files that couldn't be opened
    errors: int = 0

    def render(self) -> str:
        return (
            "\n"
            f"Processed:   {self.processed}\n"
            f"With text:   {self.with_text}\n"
            f"Unreadable:  {self.unreadable}\n"
            f"Errors:      {self.errors}"
        )


def run_ocr(
    backend: OcrBackend,
    limit: Optional[int] = None,
    batch_size: Optional[int] = None,
    on_progress: Optional[Callable[[int, int], None]] = None,
) -> OcrSummary:
    """Extract and store OCR text for photos that need it (incremental)."""
    settings = get_settings()
    settings.ensure_directories()
    eff_batch = batch_size or settings.scan_batch_size
    summary = OcrSummary()

    db.apply_schema()
    write_conn = db.open_connection()
    read_conn = db.open_connection()
    try:
        cur = write_conn.cursor()
        with write_conn.cursor() as count_cur:
            total = db.count_photos_needing_ocr(count_cur)
            if limit is not None:
                total = min(total, limit)

        done = 0
        committed = 0

        def _decode(row) -> Image.Image:
            # Full resolution on purpose: draft-scale decode would blur the very
            # small text OCR exists to read. Decode overlaps the engine via the
            # prefetch pool, so the OCR model never waits on JPEG decode.
            with Image.open(row[1]) as im:
                return im.convert("RGB")

        stream = db.stream_photos_needing_ocr(read_conn, limit=limit)
        for (photo_id, file_path), future in prefetch(
            stream, _decode, min(4, settings.decode_workers)
        ):
            done += 1
            try:
                image = future.result()
            except (FileNotFoundError, UnidentifiedImageError, OSError) as exc:
                # Mark processed (empty) so a dead file isn't retried forever.
                db.set_ocr_text(cur, photo_id, "")
                summary.unreadable += 1
                logger.warning("Cannot OCR %s: %s", file_path, exc)
            except Exception as exc:  # noqa: BLE001
                summary.errors += 1
                logger.error("OCR failed for %s: %s", file_path, exc)
            else:
                try:
                    text = backend.extract_text(image)
                except Exception as exc:  # noqa: BLE001 - a bad image shouldn't stop the run
                    summary.errors += 1
                    logger.error("OCR engine failed on %s: %s", file_path, exc)
                    text = None
                if text is not None:
                    db.set_ocr_text(cur, photo_id, text)
                    summary.processed += 1
                    if text:
                        summary.with_text += 1

            committed += 1
            if committed >= eff_batch:
                write_conn.commit()
                committed = 0
            if on_progress is not None and (done % 5 == 0 or done == total):
                on_progress(done, total)

        write_conn.commit()
    except Exception:
        write_conn.rollback()
        raise
    finally:
        read_conn.close()
        write_conn.close()

    logger.info("OCR complete: %d processed, %d with text", summary.processed, summary.with_text)
    return summary
