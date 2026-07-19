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


def photos_by_ids(cur: PgCursor, photo_ids: Sequence[int]) -> list[tuple[int, str]]:
    """Return (id, file_path) for the given photo ids, ordered by id.

    Used for manual, user-selected face detection on specific photos.
    """
    if not photo_ids:
        return []
    cur.execute(
        "SELECT id, file_path FROM photos WHERE id = ANY(%s) ORDER BY id",
        (list(photo_ids),),
    )
    return [(int(r[0]), r[1]) for r in cur.fetchall()]


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


def fetch_ungrouped_face_vectors(
    cur: PgCursor,
) -> tuple[list[int], list[float], "np.ndarray"]:
    """Return (face_ids, det_scores, embeddings) for faces with no person.

    Used by incremental recognition: only faces not yet assigned to a person.
    """
    import numpy as np

    def _to_array(value: Any) -> "np.ndarray":
        if hasattr(value, "to_numpy"):
            return value.to_numpy().astype(np.float32)
        return np.asarray(value, dtype=np.float32)

    cur.execute(
        "SELECT id, det_score, embedding FROM faces WHERE person_id IS NULL ORDER BY id"
    )
    ids: list[int] = []
    scores: list[float] = []
    vectors: list[Any] = []
    for face_id, det_score, embedding in cur.fetchall():
        ids.append(int(face_id))
        scores.append(float(det_score) if det_score is not None else 0.0)
        vectors.append(_to_array(embedding))
    matrix = np.vstack(vectors) if vectors else np.empty((0, 0), np.float32)
    return ids, scores, matrix


def count_ungrouped_faces(cur: PgCursor) -> int:
    """Count faces not yet assigned to a person."""
    cur.execute("SELECT count(*) FROM faces WHERE person_id IS NULL")
    return int(cur.fetchone()[0])


def set_person_centroid(cur: PgCursor, person_id: int, centroid: Sequence[float]) -> None:
    """Store a person's profile (average) embedding."""
    cur.execute(
        "UPDATE persons SET centroid = %s, updated_at = now() WHERE id = %s",
        (list(centroid), person_id),
    )


def fetch_person_centroids(
    cur: PgCursor,
) -> tuple[list[int], list[int], "np.ndarray"]:
    """Return (person_ids, face_counts, centroids) for people with a profile."""
    import numpy as np

    def _to_array(value: Any) -> "np.ndarray":
        if hasattr(value, "to_numpy"):
            return value.to_numpy().astype(np.float32)
        return np.asarray(value, dtype=np.float32)

    cur.execute(
        "SELECT id, face_count, centroid FROM persons WHERE centroid IS NOT NULL ORDER BY id"
    )
    ids: list[int] = []
    counts: list[int] = []
    vectors: list[Any] = []
    for person_id, face_count, centroid in cur.fetchall():
        ids.append(int(person_id))
        counts.append(int(face_count))
        vectors.append(_to_array(centroid))
    matrix = np.vstack(vectors) if vectors else np.empty((0, 0), np.float32)
    return ids, counts, matrix


def update_person_profile(
    cur: PgCursor, person_id: int, centroid: Sequence[float], face_count: int
) -> None:
    """Set a person's centroid and face_count together (after assignment)."""
    cur.execute(
        "UPDATE persons SET centroid = %s, face_count = %s, updated_at = now() WHERE id = %s",
        (list(centroid), face_count, person_id),
    )


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


def rename_person(cur: PgCursor, person_id: int, name: Optional[str]) -> None:
    """Set (or clear, with None) a person's display name."""
    clean = name.strip() if isinstance(name, str) and name.strip() else None
    cur.execute(
        "UPDATE persons SET display_name = %s, updated_at = now() WHERE id = %s",
        (clean, person_id),
    )


def delete_person(cur: PgCursor, person_id: int) -> None:
    """Remove a person group; its faces are un-grouped (person_id → NULL).

    Faces and their embeddings are never deleted — only the grouping is removed,
    thanks to the ON DELETE SET NULL foreign key.
    """
    cur.execute("DELETE FROM persons WHERE id = %s", (person_id,))


def merge_persons(cur: PgCursor, source_id: int, target_id: int) -> None:
    """Merge ``source_id`` into ``target_id``.

    All of the source's faces are reassigned to the target, the target's
    ``face_count`` is recomputed, and the (now empty) source person is removed.
    A no-op if source == target.
    """
    if source_id == target_id:
        return
    import numpy as np

    cur.execute(
        "UPDATE faces SET person_id = %s WHERE person_id = %s",
        (target_id, source_id),
    )
    cur.execute("DELETE FROM persons WHERE id = %s", (source_id,))

    # Recompute the target's profile (centroid + count) from its current faces.
    _ids, _scores, embeddings = _face_vectors_for_person(cur, target_id)
    count = int(embeddings.shape[0])
    if count:
        centroid = embeddings.mean(axis=0)
        norm = float(np.linalg.norm(centroid))
        centroid = (centroid / norm) if norm else centroid
        cur.execute(
            "UPDATE persons SET face_count = %s, centroid = %s, updated_at = now() WHERE id = %s",
            (count, centroid.tolist(), target_id),
        )
    else:
        cur.execute(
            "UPDATE persons SET face_count = 0, updated_at = now() WHERE id = %s",
            (target_id,),
        )


def _face_vectors_for_person(
    cur: PgCursor, person_id: int
) -> tuple[list[int], list[float], "np.ndarray"]:
    """Return (ids, det_scores, embeddings) for one person's faces."""
    import numpy as np

    def _to_array(value: Any) -> "np.ndarray":
        if hasattr(value, "to_numpy"):
            return value.to_numpy().astype(np.float32)
        return np.asarray(value, dtype=np.float32)

    cur.execute(
        "SELECT id, det_score, embedding FROM faces WHERE person_id = %s ORDER BY id",
        (person_id,),
    )
    ids: list[int] = []
    scores: list[float] = []
    vectors: list[Any] = []
    for face_id, det_score, embedding in cur.fetchall():
        ids.append(int(face_id))
        scores.append(float(det_score) if det_score is not None else 0.0)
        vectors.append(_to_array(embedding))
    matrix = np.vstack(vectors) if vectors else np.empty((0, 0), np.float32)
    return ids, scores, matrix


# ---------------------------------------------------------------------------
# Thumbnail helpers (Module 4)
# ---------------------------------------------------------------------------
def stream_photos_needing_thumbnail(
    conn: PgConnection, regenerate: bool = False, limit: Optional[int] = None
) -> Iterator[tuple[int, str]]:
    """Yield (id, file_path) for photos that need a thumbnail, server-side.

    When ``regenerate`` is False only photos with no ``thumbnail_path`` are
    returned; when True, every photo is yielded.
    """
    where = "" if regenerate else "WHERE thumbnail_path IS NULL"
    sql = f"SELECT id, file_path FROM photos {where} ORDER BY id"
    params: tuple[Any, ...] = ()
    if limit is not None:
        sql += " LIMIT %s"
        params = (limit,)
    with conn.cursor(name="pending_thumbs") as cur:
        cur.itersize = 1000
        cur.execute(sql, params)
        for row in cur:
            yield int(row[0]), row[1]


def set_thumbnail_path(cur: PgCursor, photo_id: int, thumbnail_path: str) -> None:
    """Record the cached thumbnail path for a photo."""
    cur.execute(
        "UPDATE photos SET thumbnail_path = %s, updated_at = now() WHERE id = %s",
        (thumbnail_path, photo_id),
    )


def count_photos_needing_thumbnail(cur: PgCursor, regenerate: bool = False) -> int:
    """Return how many photos still need a thumbnail (all, if regenerating)."""
    if regenerate:
        cur.execute("SELECT count(*) FROM photos")
    else:
        cur.execute("SELECT count(*) FROM photos WHERE thumbnail_path IS NULL")
    return int(cur.fetchone()[0])


def count_photos_pending_faces(cur: PgCursor) -> int:
    """Return how many photos have not yet been through face detection."""
    cur.execute("SELECT count(*) FROM photos WHERE faces_processed = FALSE")
    return int(cur.fetchone()[0])


# ---------------------------------------------------------------------------
# Read helpers for the Viewer UI (read-only; the UI never writes SQL directly)
# ---------------------------------------------------------------------------
def library_stats(cur: PgCursor) -> dict[str, int]:
    """Return headline counts for the dashboard and status bar."""
    cur.execute(
        """
        SELECT
            (SELECT count(*) FROM photos),
            (SELECT count(*) FROM faces),
            (SELECT count(*) FROM persons),
            (SELECT coalesce(sum(file_size), 0) FROM photos)
        """
    )
    photos, faces, persons, storage = cur.fetchone()
    return {
        "photos": int(photos),
        "faces": int(faces),
        "persons": int(persons),
        "storage_bytes": int(storage),
    }


def list_photo_grid(
    cur: PgCursor,
    limit: int,
    offset: int = 0,
    person_id: Optional[int] = None,
    search: Optional[str] = None,
) -> list[tuple[int, str, Optional[str], Any]]:
    """Return (id, file_path, thumbnail_path, taken_at) rows for the gallery.

    Newest first (by capture time, then id). Optionally restricted to a person
    (photos containing one of their faces) or filtered by a free-text term that
    matches the file path or camera model.
    """
    clauses: list[str] = []
    params: list[Any] = []
    joins = ""

    if person_id is not None:
        joins = "JOIN faces f ON f.photo_id = p.id"
        clauses.append("f.person_id = %s")
        params.append(person_id)

    if search:
        clauses.append("(p.file_path ILIKE %s OR p.camera_model ILIKE %s)")
        term = f"%{search}%"
        params.extend([term, term])

    where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
    distinct = "DISTINCT" if person_id is not None else ""
    params.extend([limit, offset])

    cur.execute(
        f"""
        SELECT {distinct} p.id, p.file_path, p.thumbnail_path, p.taken_at
          FROM photos p {joins}
          {where}
         ORDER BY p.taken_at DESC NULLS LAST, p.id DESC
         LIMIT %s OFFSET %s
        """,
        params,
    )
    return [(int(r[0]), r[1], r[2], r[3]) for r in cur.fetchall()]


def get_photo_detail(cur: PgCursor, photo_id: int) -> Optional[dict[str, Any]]:
    """Return a photo's full metadata for the viewer panel, or None."""
    cur.execute(
        """
        SELECT id, file_path, thumbnail_path, file_size, width, height, format,
               taken_at, camera_make, camera_model, orientation,
               gps_latitude, gps_longitude, is_favorite
          FROM photos WHERE id = %s
        """,
        (photo_id,),
    )
    row = cur.fetchone()
    if row is None:
        return None
    keys = (
        "id", "file_path", "thumbnail_path", "file_size", "width", "height",
        "format", "taken_at", "camera_make", "camera_model", "orientation",
        "gps_latitude", "gps_longitude", "is_favorite",
    )
    return dict(zip(keys, row))


def list_persons_with_cover(cur: PgCursor) -> list[dict[str, Any]]:
    """Return people ordered by size, each with its cover face crop path."""
    cur.execute(
        """
        SELECT pr.id, pr.display_name, pr.face_count, f.crop_path
          FROM persons pr
          LEFT JOIN faces f ON f.id = pr.cover_face_id
         ORDER BY pr.face_count DESC, pr.id
        """
    )
    return [
        {"id": int(r[0]), "display_name": r[1], "face_count": int(r[2]), "cover_path": r[3]}
        for r in cur.fetchall()
    ]


# ---------------------------------------------------------------------------
# CLIP / semantic search helpers
# ---------------------------------------------------------------------------
def stream_photos_needing_clip(
    conn: PgConnection, model: str, version: int, limit: Optional[int] = None
) -> Iterator[tuple[int, str]]:
    """Yield (id, file_path) for photos with no CLIP embedding for this model.

    Incremental: a photo is returned only if it has no ``clip_embeddings`` row
    matching the given model+version, so re-running only embeds new photos.
    """
    sql = (
        "SELECT p.id, p.file_path FROM photos p "
        "WHERE NOT EXISTS (SELECT 1 FROM clip_embeddings ce "
        "WHERE ce.photo_id = p.id AND ce.model = %s AND ce.version = %s) "
        "ORDER BY p.id"
    )
    params: tuple[Any, ...] = (model, version)
    if limit is not None:
        sql += " LIMIT %s"
        params = (model, version, limit)
    with conn.cursor(name="pending_clip") as cur:
        cur.itersize = 256
        cur.execute(sql, params)
        for row in cur:
            yield int(row[0]), row[1]


def count_photos_needing_clip(cur: PgCursor, model: str, version: int) -> int:
    """Count photos with no CLIP embedding for this model+version."""
    cur.execute(
        "SELECT count(*) FROM photos p WHERE NOT EXISTS ("
        "SELECT 1 FROM clip_embeddings ce WHERE ce.photo_id = p.id "
        "AND ce.model = %s AND ce.version = %s)",
        (model, version),
    )
    return int(cur.fetchone()[0])


def upsert_clip_embedding(
    cur: PgCursor, photo_id: int, embedding: Sequence[float], model: str, version: int
) -> None:
    """Insert or replace a photo's CLIP embedding (one active model per photo)."""
    cur.execute(
        """
        INSERT INTO clip_embeddings (photo_id, embedding, model, version)
        VALUES (%s, %s, %s, %s)
        ON CONFLICT (photo_id) DO UPDATE
           SET embedding = EXCLUDED.embedding,
               model = EXCLUDED.model,
               version = EXCLUDED.version,
               updated_at = now()
        """,
        (photo_id, list(embedding), model, version),
    )


def count_clip_embeddings(cur: PgCursor, model: Optional[str] = None) -> int:
    """Count stored CLIP embeddings (optionally for a specific model)."""
    if model is None:
        cur.execute("SELECT count(*) FROM clip_embeddings")
    else:
        cur.execute("SELECT count(*) FROM clip_embeddings WHERE model = %s", (model,))
    return int(cur.fetchone()[0])


def search_photos_by_clip(
    cur: PgCursor,
    query_vector: Sequence[float],
    model: str,
    limit: int = 200,
) -> list[tuple[int, str, Optional[str], Any, float]]:
    """Return the top-K photos most similar to a query vector.

    Rows are (id, file_path, thumbnail_path, taken_at, score) ordered by cosine
    similarity descending. ``score`` is 1 - cosine_distance in [0, 1]. Restricted
    to embeddings from ``model`` so mixed-model results never appear.
    """
    vec = list(query_vector)
    cur.execute(
        """
        SELECT p.id, p.file_path, p.thumbnail_path, p.taken_at,
               1 - (ce.embedding <=> %s::vector) AS score
          FROM clip_embeddings ce
          JOIN photos p ON p.id = ce.photo_id
         WHERE ce.model = %s
         ORDER BY ce.embedding <=> %s::vector
         LIMIT %s
        """,
        (vec, model, vec, limit),
    )
    return [(int(r[0]), r[1], r[2], r[3], float(r[4])) for r in cur.fetchall()]


def recent_scan_runs(cur: PgCursor, limit: int = 5) -> list[dict[str, Any]]:
    """Return the most recent scan runs for the dashboard activity feed."""
    cur.execute(
        """
        SELECT root_path, started_at, finished_at, processed, skipped, duplicates, errors
          FROM scan_runs ORDER BY id DESC LIMIT %s
        """,
        (limit,),
    )
    keys = ("root_path", "started_at", "finished_at", "processed", "skipped", "duplicates", "errors")
    return [dict(zip(keys, row)) for row in cur.fetchall()]


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
