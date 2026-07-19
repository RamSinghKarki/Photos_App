"""Incremental, batched image-embedding engine.

Computes CLIP image embeddings for photos that don't yet have one for the
active model, in GPU-friendly batches, and stores them in PostgreSQL. Designed
to run in a background worker: it accepts an ``on_progress`` callback and is
cancel-safe (committed batches persist, so a later run resumes).

Only *new* photos are embedded — the pending query excludes photos already
embedded for this model+version, so re-running is cheap.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, List, Optional, Tuple

from PIL import Image, UnidentifiedImageError

from config.settings import get_settings
from database import db
from search.embedding_backend import EmbeddingBackend
from utils.logging_setup import get_logger

logger = get_logger("search.engine")


@dataclass
class EmbeddingSummary:
    """Outcome of an embedding run."""

    embedded: int = 0
    unreadable: int = 0
    errors: int = 0

    def render(self) -> str:
        return (
            "\n"
            f"Embedded:    {self.embedded}\n"
            f"Unreadable:  {self.unreadable}\n"
            f"Errors:      {self.errors}"
        )


def embed_images(
    backend: EmbeddingBackend,
    batch_size: Optional[int] = None,
    limit: Optional[int] = None,
    on_progress: Optional[Callable[[int, int], None]] = None,
) -> EmbeddingSummary:
    """Embed photos lacking a CLIP vector for the backend's model.

    Raises:
        ValueError: if the backend's dimension doesn't match the schema/config.
    """
    settings = get_settings()
    if backend.dim != settings.clip_embedding_dim:
        raise ValueError(
            f"Backend dim {backend.dim} != configured clip_embedding_dim "
            f"{settings.clip_embedding_dim}; recreate clip_embeddings or fix config."
        )

    eff_batch = batch_size or settings.clip_batch_size
    model_id, version = backend.model_id, backend.version
    summary = EmbeddingSummary()

    db.apply_schema()
    write_conn = db.open_connection()
    read_conn = db.open_connection()
    try:
        cur = write_conn.cursor()
        with write_conn.cursor() as count_cur:
            total = db.count_photos_needing_clip(count_cur, model_id, version)
            if limit is not None:
                total = min(total, limit)

        done = 0  # photos consumed from the stream (embedded + skipped)
        batch: List[Tuple[int, Image.Image]] = []

        def flush() -> None:
            """Encode and store the current batch (commits on success)."""
            if not batch:
                return
            try:
                vectors = backend.encode_images([img for _, img in batch])
                for (photo_id, _img), vector in zip(batch, vectors):
                    db.upsert_clip_embedding(cur, photo_id, vector.tolist(), model_id, version)
                    summary.embedded += 1
                write_conn.commit()
            except Exception as exc:  # noqa: BLE001 - a bad batch shouldn't abort the run
                write_conn.rollback()
                summary.errors += len(batch)
                logger.error("Failed to embed a batch of %d: %s", len(batch), exc)
            finally:
                batch.clear()

        def report() -> None:
            # Called after a committed flush; may raise PipelineCancelled to stop.
            if on_progress is not None:
                on_progress(done, total)

        for photo_id, file_path in db.stream_photos_needing_clip(
            read_conn, model_id, version, limit=limit
        ):
            done += 1
            try:
                with Image.open(file_path) as im:
                    image = im.convert("RGB")  # detaches from the file handle
            except (FileNotFoundError, UnidentifiedImageError, OSError) as exc:
                summary.unreadable += 1
                logger.warning("Cannot embed %s: %s", file_path, exc)
                if done % eff_batch == 0:
                    report()
                continue

            batch.append((photo_id, image))
            if len(batch) >= eff_batch:
                flush()
                report()

        flush()
        report()
        write_conn.commit()
    except Exception:
        write_conn.rollback()
        raise
    finally:
        read_conn.close()
        write_conn.close()

    logger.info("CLIP embedding complete: %s embedded", summary.embedded)
    return summary
