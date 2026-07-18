"""Database access layer for PhotoSphere AI.

The PostgreSQL database is the single source of truth. Every read and write in
the application goes through a named helper function in this module — there is
no inline SQL scattered across the codebase. That keeps the schema contract in
one place and makes future changes safe.

Connections are short-lived and wrapped in :func:`connection`, a context
manager that commits on success and rolls back on any exception, so a partial
scan never leaves the database in a half-written state.
"""

from __future__ import annotations

import datetime as _dt
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterator, Optional, Sequence

import psycopg2
from psycopg2.extensions import connection as PgConnection
from psycopg2.extensions import cursor as PgCursor
from pgvector.psycopg2 import register_vector

from config.settings import get_settings
from utils.logging_setup import get_logger

logger = get_logger("database")

_SCHEMA_PATH = Path(__file__).resolve().parent / "schema.sql"


# ---------------------------------------------------------------------------
# Data transfer objects
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class PhotoMetadata:
    """Everything the scanner knows about one image before it is stored.

    Only the identity fields (path/hash/size/mtime) are guaranteed present;
    all EXIF-derived fields are optional because many files lack them.
    """

    file_path: str
    file_hash: str
    file_size: int
    file_mtime: _dt.datetime
    width: Optional[int] = None
    height: Optional[int] = None
    format: Optional[str] = None
    taken_at: Optional[_dt.datetime] = None
    camera_make: Optional[str] = None
    camera_model: Optional[str] = None
    orientation: Optional[int] = None
    gps_latitude: Optional[float] = None
    gps_longitude: Optional[float] = None


# ---------------------------------------------------------------------------
# Connection management
# ---------------------------------------------------------------------------
def _connect() -> PgConnection:
    """Open a raw psycopg2 connection using the configured DSN."""
    settings = get_settings()
    conn = psycopg2.connect(settings.database.dsn)
    # Register the pgvector adapter so Python lists/arrays map to `vector`.
    # This requires the `vector` extension to already exist; on a brand-new
    # database that happens inside apply_schema(), so we tolerate failure here.
    try:
        register_vector(conn)
    except psycopg2.Error:
        conn.rollback()
        logger.debug("pgvector type not registered yet (extension not installed)")
    return conn


@contextmanager
def connection() -> Iterator[PgConnection]:
    """Yield a connection that commits on success and rolls back on error.

    Usage::

        with connection() as conn, conn.cursor() as cur:
            insert_photo(cur, meta)
    """
    conn = _connect()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def apply_schema() -> None:
    """Create the schema (extension, tables, indexes) if it does not exist.

    Idempotent — safe to run at every startup. Uses its own connection so it
    can be called before any other database work.
    """
    sql = _SCHEMA_PATH.read_text(encoding="utf-8")
    conn = psycopg2.connect(get_settings().database.dsn)
    try:
        with conn.cursor() as cur:
            cur.execute(sql)
        conn.commit()
        logger.info("Database schema applied (idempotent)")
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Photo helpers
# ---------------------------------------------------------------------------
def photo_path_exists(cur: PgCursor, file_path: str) -> bool:
    """Return True if a photo with this exact path is already stored."""
    cur.execute("SELECT 1 FROM photos WHERE file_path = %s LIMIT 1", (file_path,))
    return cur.fetchone() is not None


def hash_exists(cur: PgCursor, file_hash: str) -> bool:
    """Return True if any stored photo already has this content hash.

    Used for duplicate detection: two different paths with the same hash are
    byte-identical images.
    """
    cur.execute("SELECT 1 FROM photos WHERE file_hash = %s LIMIT 1", (file_hash,))
    return cur.fetchone() is not None


def insert_photo(cur: PgCursor, meta: PhotoMetadata) -> Optional[int]:
    """Insert a photo row and return its new id.

    If a row with the same ``file_path`` already exists the insert is skipped
    (ON CONFLICT DO NOTHING) and ``None`` is returned, so re-scanning a folder
    is safe and cheap.
    """
    cur.execute(
        """
        INSERT INTO photos (
            file_path, file_hash, file_size, file_mtime,
            width, height, format, taken_at,
            camera_make, camera_model, orientation,
            gps_latitude, gps_longitude
        ) VALUES (
            %(file_path)s, %(file_hash)s, %(file_size)s, %(file_mtime)s,
            %(width)s, %(height)s, %(format)s, %(taken_at)s,
            %(camera_make)s, %(camera_model)s, %(orientation)s,
            %(gps_latitude)s, %(gps_longitude)s
        )
        ON CONFLICT (file_path) DO NOTHING
        RETURNING id
        """,
        meta.__dict__,
    )
    row = cur.fetchone()
    return int(row[0]) if row else None


def count_photos(cur: PgCursor) -> int:
    """Return the total number of photos stored."""
    cur.execute("SELECT count(*) FROM photos")
    return int(cur.fetchone()[0])


# ---------------------------------------------------------------------------
# Face helpers (schema is ready now; used by Module 2)
# ---------------------------------------------------------------------------
def insert_face(
    cur: PgCursor,
    photo_id: int,
    bbox: tuple[int, int, int, int],
    embedding: Sequence[float],
    det_score: Optional[float] = None,
    crop_path: Optional[str] = None,
) -> int:
    """Insert one detected face for a photo and return its id.

    ``embedding`` is stored exactly as produced by the model (normalization for
    comparison happens at query time, not on write).
    """
    x, y, w, h = bbox
    cur.execute(
        """
        INSERT INTO faces (photo_id, bbox_x, bbox_y, bbox_w, bbox_h,
                           det_score, embedding, crop_path)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
        RETURNING id
        """,
        (photo_id, x, y, w, h, det_score, list(embedding), crop_path),
    )
    return int(cur.fetchone()[0])


def mark_photo_faces_processed(cur: PgCursor, photo_id: int) -> None:
    """Flag a photo as having been through the face module."""
    cur.execute(
        "UPDATE photos SET faces_processed = TRUE, updated_at = now() WHERE id = %s",
        (photo_id,),
    )


def _pending_faces_sql(limit: Optional[int]) -> tuple[str, tuple[Any, ...]]:
    """Build the SELECT for photos awaiting face processing."""
    sql = "SELECT id, file_path FROM photos WHERE faces_processed = FALSE ORDER BY id"
    if limit is not None:
        return sql + " LIMIT %s", (limit,)
    return sql, ()


def iter_photos_pending_faces(
    cur: PgCursor, limit: Optional[int] = None
) -> list[tuple[int, str]]:
    """Return (id, file_path) for photos not yet processed by the face module.

    Materialises the full list — convenient for tests and small batches. For
    large libraries prefer :func:`stream_photos_pending_faces`.
    """
    sql, params = _pending_faces_sql(limit)
    cur.execute(sql, params)
    return [(int(row[0]), row[1]) for row in cur.fetchall()]


def stream_photos_pending_faces(
    conn: PgConnection, limit: Optional[int] = None, itersize: int = 1000
) -> Iterator[tuple[int, str]]:
    """Yield (id, file_path) for pending photos via a server-side cursor.

    The named cursor keeps the result set on the server and streams it in
    ``itersize`` chunks, so memory stays flat even for a 500k-photo library.
    The given connection must stay read-only for the life of the generator
    (do writes/commits on a *separate* connection).
    """
    sql, params = _pending_faces_sql(limit)
    with conn.cursor(name="pending_faces") as cur:
        cur.itersize = itersize
        cur.execute(sql, params)
        for row in cur:
            yield int(row[0]), row[1]


def open_connection() -> PgConnection:
    """Open a standalone connection; the caller manages commit/close.

    Used when two connections are needed at once — e.g. streaming reads on one
    while committing writes on another.
    """
    return _connect()


def delete_faces_for_photo(cur: PgCursor, photo_id: int) -> None:
    """Remove any existing faces for a photo (used when reprocessing)."""
    cur.execute("DELETE FROM faces WHERE photo_id = %s", (photo_id,))


def reset_faces_processed(cur: PgCursor) -> int:
    """Mark every photo as needing face processing again; return row count.

    Used by the ``--reprocess`` path so a re-run re-examines the whole library.
    """
    cur.execute("UPDATE photos SET faces_processed = FALSE WHERE faces_processed = TRUE")
    return cur.rowcount


def count_faces(cur: PgCursor) -> int:
    """Return the total number of detected faces stored."""
    cur.execute("SELECT count(*) FROM faces")
    return int(cur.fetchone()[0])


# ---------------------------------------------------------------------------
# Person / clustering helpers (Module 3)
# ---------------------------------------------------------------------------
def fetch_face_vectors(cur: PgCursor) -> tuple[list[int], list[float], "np.ndarray"]:
    """Return (face_ids, det_scores, embeddings) for every stored face.

    ``embeddings`` is an (N, dim) float32 array. Because pgvector is registered
    on the connection, the ``embedding`` column already arrives as a NumPy
    array, so no per-row parsing is needed.
    """
    import numpy as np  # local import keeps db.py import-light

    def _to_array(value: Any) -> "np.ndarray":
        # pgvector may hand back its own Vector type, a list, or an ndarray
        # depending on version; normalize them all to a float32 row.
        if hasattr(value, "to_numpy"):
            return value.to_numpy().astype(np.float32)
        return np.asarray(value, dtype=np.float32)

    cur.execute("SELECT id, det_score, embedding FROM faces ORDER BY id")
    ids: list[int] = []
    scores: list[float] = []
    vectors: list[Any] = []
    for face_id, det_score, embedding in cur.fetchall():
        ids.append(int(face_id))
        scores.append(float(det_score) if det_score is not None else 0.0)
        vectors.append(_to_array(embedding))

    matrix = np.vstack(vectors) if vectors else np.empty((0, 0), np.float32)
    return ids, scores, matrix


def clear_persons(cur: PgCursor) -> None:
    """Remove every person row, detaching their faces.

    DELETE (not TRUNCATE) is used because the faces->persons foreign key blocks
    TRUNCATE; the FK's ON DELETE SET NULL clears each face's person_id as its
    person is removed, giving a clean slate for a re-cluster.
    """
    cur.execute("DELETE FROM persons")


def create_person(cur: PgCursor, face_count: int, cover_face_id: Optional[int]) -> int:
    """Insert a person row and return its id."""
    cur.execute(
        "INSERT INTO persons (face_count, cover_face_id) VALUES (%s, %s) RETURNING id",
        (face_count, cover_face_id),
    )
    return int(cur.fetchone()[0])


def assign_faces_to_person(cur: PgCursor, person_id: int, face_ids: Sequence[int]) -> None:
    """Point a batch of faces at one person in a single statement."""
    cur.execute(
        "UPDATE faces SET person_id = %s WHERE id = ANY(%s)",
        (person_id, list(face_ids)),
    )


def count_persons(cur: PgCursor) -> int:
    """Return the number of person groups."""
    cur.execute("SELECT count(*) FROM persons")
    return int(cur.fetchone()[0])


# ---------------------------------------------------------------------------
# Scan-run bookkeeping (drives the processing summary)
# ---------------------------------------------------------------------------
def start_scan_run(cur: PgCursor, root_path: str) -> int:
    """Record the start of a scan and return its run id."""
    cur.execute(
        "INSERT INTO scan_runs (root_path) VALUES (%s) RETURNING id",
        (root_path,),
    )
    return int(cur.fetchone()[0])


def finish_scan_run(
    cur: PgCursor,
    run_id: int,
    processed: int,
    skipped: int,
    duplicates: int,
    errors: int,
) -> None:
    """Record the final counters and finish time for a scan run."""
    cur.execute(
        """
        UPDATE scan_runs
           SET finished_at = now(),
               processed   = %s,
               skipped     = %s,
               duplicates  = %s,
               errors      = %s
         WHERE id = %s
        """,
        (processed, skipped, duplicates, errors, run_id),
    )
