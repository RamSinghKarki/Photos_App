"""Thumbnail generation for the Viewer (Module 4).

The gallery must never load original images while browsing — that is what keeps
scrolling fast on a 100k+ photo library. This module renders a small, cached
JPEG thumbnail for each photo (longest edge = ``Settings.thumbnail_size``) under
``data/thumbnails`` and records its path in ``photos.thumbnail_path``.

Like the face pipeline it streams pending photos server-side, commits in
batches, and never lets one unreadable file abort the run.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from PIL import Image, ImageOps, UnidentifiedImageError

from config.settings import get_settings
from database import db
from utils.logging_setup import get_logger

logger = get_logger("thumbnails")


@dataclass
class ThumbnailSummary:
    """Outcome of a thumbnail run, shown to the user at the end."""

    generated: int = 0
    unreadable: int = 0
    errors: int = 0

    def render(self) -> str:
        return (
            "\n"
            f"Generated:   {self.generated}\n"
            f"Unreadable:  {self.unreadable}\n"
            f"Errors:      {self.errors}"
        )


def generate_one(file_path: str, photo_id: int) -> str:
    """Render and save a thumbnail for one photo; return its cache path.

    EXIF orientation is applied so portrait photos are not shown sideways.

    Raises:
        FileNotFoundError / UnidentifiedImageError / OSError: if unreadable.
    """
    settings = get_settings()
    size = settings.thumbnail_size
    out_path = settings.thumbnails_dir / f"{photo_id}.jpg"

    with Image.open(file_path) as img:
        oriented = ImageOps.exif_transpose(img)  # honour EXIF orientation
        oriented = oriented.convert("RGB")
        oriented.thumbnail((size, size))  # in-place, preserves aspect ratio
        oriented.save(out_path, "JPEG", quality=settings.thumbnail_quality)

    return str(out_path)


def generate_thumbnails(
    limit: Optional[int] = None,
    regenerate: bool = False,
    batch_size: Optional[int] = None,
) -> ThumbnailSummary:
    """Generate thumbnails for photos that lack one.

    Args:
        limit: Max photos to process this run.
        regenerate: If True, rebuild thumbnails for every photo.
        batch_size: Photos per committed transaction (defaults to configured).
    """
    settings = get_settings()
    settings.ensure_directories()
    effective_batch = batch_size or settings.scan_batch_size
    summary = ThumbnailSummary()

    db.apply_schema()

    write_conn = db.open_connection()
    read_conn = db.open_connection()
    try:
        cur = write_conn.cursor()
        committed = 0
        for photo_id, file_path in db.stream_photos_needing_thumbnail(
            read_conn, regenerate=regenerate, limit=limit
        ):
            try:
                thumb_path = generate_one(file_path, photo_id)
                db.set_thumbnail_path(cur, photo_id, thumb_path)
                summary.generated += 1
            except (FileNotFoundError, UnidentifiedImageError, OSError) as exc:
                summary.unreadable += 1
                logger.warning("Cannot thumbnail %s: %s", file_path, exc)
                continue
            except Exception as exc:  # noqa: BLE001 - keep going past any file
                summary.errors += 1
                logger.error("Failed to thumbnail %s: %s", file_path, exc)
                continue

            committed += 1
            if committed >= effective_batch:
                write_conn.commit()
                committed = 0
                logger.info("Committed batch; generated so far: %d", summary.generated)

        write_conn.commit()
    except Exception:
        write_conn.rollback()
        raise
    finally:
        read_conn.close()
        write_conn.close()

    logger.info("Thumbnail generation complete")
    return summary
