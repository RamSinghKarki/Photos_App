"""Module 2 — Face processing pipeline.

Reads photos the scanner stored, runs the face detector on each, saves a crop
of every face to the image cache, and writes the face rows (bounding box,
detector score, raw embedding, crop path) to the database.

Rules honoured here:
  * **Local only** — detection is done by the injected detector (InsightFace by
    default); nothing leaves the machine.
  * **Never crash on one bad image** — per-photo errors are caught, logged and
    counted; the run continues.
  * **Don't recompute** — only photos with ``faces_processed = FALSE`` are
    examined, unless the caller explicitly reprocesses.
  * **Multiple faces per photo** — each detection becomes its own ``faces`` row.
  * **Cache, don't pollute** — crops go under ``data/face_crops``, never beside
    the user's originals.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import numpy as np
from PIL import Image, UnidentifiedImageError

from config.settings import get_settings
from database import db
from faces.detector import DetectedFace, FaceDetector
from utils.logging_setup import get_logger

logger = get_logger("faces.processor")


class UnreadableImageError(Exception):
    """Raised when a photo's file cannot be opened as an image.

    This is a *terminal* condition for that photo (corrupt bytes or a missing
    file): re-running would fail identically, so the photo is marked processed
    to avoid retrying it forever. ``--reprocess`` still forces another attempt.
    """


@dataclass
class FaceSummary:
    """Counters describing a face-processing run, shown to the user at the end."""

    photos: int = 0        # images opened and run through the detector
    faces: int = 0         # faces detected and stored
    no_faces: int = 0      # processed photos where the detector found nobody
    unreadable: int = 0    # files that could not be opened (corrupt/missing)
    errors: int = 0        # unexpected failures (e.g. database)

    def render(self) -> str:
        """Return the human-readable summary block."""
        return (
            "\n"
            f"Photos processed: {self.photos}\n"
            f"Faces found:      {self.faces}\n"
            f"No faces:         {self.no_faces}\n"
            f"Unreadable:       {self.unreadable}\n"
            f"Errors:           {self.errors}"
        )


def _save_face_crop(image: Image.Image, face: DetectedFace, photo_id: int, index: int) -> str:
    """Crop a face from ``image``, save it to the cache, and return its path."""
    crops_dir = get_settings().face_crops_dir
    x, y, w, h = face.bbox
    crop = image.crop((x, y, x + w, y + h))
    out_path = crops_dir / f"{photo_id}_{index}.jpg"
    crop.convert("RGB").save(out_path, "JPEG", quality=90)
    return str(out_path)


def _process_one_photo(
    cur, detector: FaceDetector, photo_id: int, file_path: str
) -> int:
    """Detect, crop and store faces for a single photo; return face count.

    Raises:
        UnreadableImageError: if the file cannot be opened as an image.
    """
    try:
        img = Image.open(file_path)
    except (FileNotFoundError, UnidentifiedImageError, OSError) as exc:
        raise UnreadableImageError(str(exc)) from exc

    with img:
        rgb_img = img.convert("RGB")
        rgb_array = np.asarray(rgb_img)
        faces = detector.detect(rgb_array)

        for index, face in enumerate(faces):
            crop_path = _save_face_crop(rgb_img, face, photo_id, index)
            db.insert_face(
                cur,
                photo_id=photo_id,
                bbox=face.bbox,
                embedding=face.embedding,
                det_score=face.det_score,
                crop_path=crop_path,
            )

    db.mark_photo_faces_processed(cur, photo_id)
    return len(faces)


def process_faces(
    detector: FaceDetector,
    reprocess: bool = False,
    limit: Optional[int] = None,
    batch_size: Optional[int] = None,
) -> FaceSummary:
    """Run face detection over photos that need it.

    Args:
        detector: The face detector to use (injected for testability).
        reprocess: If True, re-examine every photo (existing faces are cleared
            per photo before re-detecting) instead of only unprocessed ones.
        limit: Maximum number of photos to process this run.
        batch_size: Photos per committed transaction (defaults to configured).

    Returns:
        A :class:`FaceSummary` of the run.
    """
    settings = get_settings()
    settings.ensure_directories()
    effective_batch = batch_size or settings.scan_batch_size
    summary = FaceSummary()

    db.apply_schema()

    # Two connections: one streams the (potentially huge) list of pending photos
    # server-side, the other performs batched writes. Keeping them separate lets
    # writes commit repeatedly without invalidating the streaming read cursor.
    write_conn = db.open_connection()
    read_conn = db.open_connection()
    try:
        cur = write_conn.cursor()

        if reprocess:
            reset = db.reset_faces_processed(cur)
            write_conn.commit()  # commit before streaming so the read sees it
            logger.info("Reprocess requested: %d photos re-queued for faces", reset)

        committed = 0
        for photo_id, file_path in db.stream_photos_pending_faces(read_conn, limit=limit):
            # A per-photo savepoint isolates failures: a bad image rolls back
            # only its own writes, never the rest of the uncommitted batch.
            cur.execute("SAVEPOINT photo_sp")
            try:
                if reprocess:
                    db.delete_faces_for_photo(cur, photo_id)

                found = _process_one_photo(cur, detector, photo_id, file_path)
                cur.execute("RELEASE SAVEPOINT photo_sp")

                summary.photos += 1
                summary.faces += found
                if found == 0:
                    summary.no_faces += 1

                committed += 1
                if committed >= effective_batch:
                    write_conn.commit()
                    committed = 0
                    logger.info("Committed batch; photos so far: %d", summary.photos)

            except UnreadableImageError as exc:
                # Terminal for this photo: undo any partial writes, then mark it
                # processed so future runs don't keep retrying a dead file.
                cur.execute("ROLLBACK TO SAVEPOINT photo_sp")
                cur.execute("RELEASE SAVEPOINT photo_sp")
                db.mark_photo_faces_processed(cur, photo_id)
                summary.unreadable += 1
                committed += 1
                logger.warning("Unreadable image, skipping faces: %s (%s)", file_path, exc)

            except Exception as exc:  # noqa: BLE001 - keep processing past any file
                summary.errors += 1
                # Undo just this photo's partial writes and carry on.
                cur.execute("ROLLBACK TO SAVEPOINT photo_sp")
                cur.execute("RELEASE SAVEPOINT photo_sp")
                logger.error("Failed to process faces for %s: %s", file_path, exc)

        write_conn.commit()
    except Exception:
        write_conn.rollback()
        raise
    finally:
        read_conn.close()
        write_conn.close()

    logger.info("Face processing complete")
    return summary
