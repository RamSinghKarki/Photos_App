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


def _embeddings_to_matrix(rows: "list[Any]") -> "np.ndarray":
    """Stack pgvector/list embeddings into an (N, dim) float32 matrix."""
    import numpy as np

    mats = []
    for value in rows:
        if hasattr(value, "to_numpy"):
            mats.append(value.to_numpy().astype(np.float32))
        else:
            mats.append(np.asarray(value, dtype=np.float32))
    return np.vstack(mats) if mats else np.empty((0, 0), np.float32)


def fetch_ungrouped_faces(
    cur: PgCursor,
) -> tuple[list[int], list[float], list[tuple[int, int]], "np.ndarray"]:
    """Return (face_ids, det_scores, sizes, embeddings) for faces with no person.

    ``sizes`` is a list of (bbox_w, bbox_h) so the recognition engine can score
    each face's quality (resolution) without a second query.
    """
    cur.execute(
        "SELECT id, det_score, bbox_w, bbox_h, embedding "
        "FROM faces WHERE person_id IS NULL ORDER BY id"
    )
    ids: list[int] = []
    scores: list[float] = []
    sizes: list[tuple[int, int]] = []
    vectors: list[Any] = []
    for face_id, det_score, bbox_w, bbox_h, embedding in cur.fetchall():
        ids.append(int(face_id))
        scores.append(float(det_score) if det_score is not None else 0.0)
        sizes.append((int(bbox_w), int(bbox_h)))
        vectors.append(embedding)
    return ids, scores, sizes, _embeddings_to_matrix(vectors)


def fetch_person_face_rows(
    cur: PgCursor, person_id: int
) -> tuple[list[int], list[float], list[tuple[int, int]], "np.ndarray"]:
    """Like :func:`fetch_ungrouped_faces` but for one person's assigned faces.

    Used to backfill a representative gallery for people grouped before the
    gallery existed.
    """
    cur.execute(
        "SELECT id, det_score, bbox_w, bbox_h, embedding "
        "FROM faces WHERE person_id = %s ORDER BY id",
        (person_id,),
    )
    ids: list[int] = []
    scores: list[float] = []
    sizes: list[tuple[int, int]] = []
    vectors: list[Any] = []
    for face_id, det_score, bbox_w, bbox_h, embedding in cur.fetchall():
        ids.append(int(face_id))
        scores.append(float(det_score) if det_score is not None else 0.0)
        sizes.append((int(bbox_w), int(bbox_h)))
        vectors.append(embedding)
    return ids, scores, sizes, _embeddings_to_matrix(vectors)


# ---------------------------------------------------------------------------
# Representative gallery (recognition engine v2)
# ---------------------------------------------------------------------------
def add_person_embeddings_from_faces(
    cur: PgCursor, rows: Sequence[tuple[int, int, float]]
) -> None:
    """Insert (or move) many faces into person galleries in ONE statement.

    ``rows`` is (person_id, face_id, quality) per face; the embedding is copied
    **server-side** from ``faces`` — it never round-trips through Python. The
    previous approaches were measured (audit item P2): row-at-a-time upserts
    ~1.9 s per 1000 faces, and even a batched insert still ~1.4 s because
    serializing 1000×512 floats to SQL text dominates. This variant sends three
    scalars per row. Keyed by face_id: a face reassigned by a merge moves rather
    than duplicates. Stored embeddings are raw; every read path normalizes.
    """
    if not rows:
        return
    from psycopg2.extras import execute_values

    execute_values(
        cur,
        """
        INSERT INTO person_embeddings
            (person_id, face_id, embedding, quality, is_representative)
        SELECT v.person_id, v.face_id, f.embedding, v.quality, FALSE
          FROM (VALUES %s) AS v(person_id, face_id, quality)
          JOIN faces f ON f.id = v.face_id
        ON CONFLICT (face_id) DO UPDATE SET
            person_id = EXCLUDED.person_id,
            embedding = EXCLUDED.embedding,
            quality = EXCLUDED.quality
        """,
        [(int(p), int(f), float(q)) for p, f, q in rows],
    )


def fetch_person_gallery(
    cur: PgCursor, person_id: int
) -> tuple[list[int], "np.ndarray", "np.ndarray"]:
    """Return (face_ids, qualities, embeddings) for one person's whole gallery."""
    import numpy as np

    cur.execute(
        "SELECT face_id, quality, embedding FROM person_embeddings "
        "WHERE person_id = %s ORDER BY face_id",
        (person_id,),
    )
    ids: list[int] = []
    quals: list[float] = []
    vectors: list[Any] = []
    for face_id, quality, embedding in cur.fetchall():
        ids.append(int(face_id))
        quals.append(float(quality))
        vectors.append(embedding)
    return ids, np.asarray(quals, dtype=np.float32), _embeddings_to_matrix(vectors)


def set_person_representatives(
    cur: PgCursor, person_id: int, representative_face_ids: Sequence[int]
) -> None:
    """Flag exactly ``representative_face_ids`` as representative for a person."""
    reps = list(representative_face_ids)
    cur.execute(
        "UPDATE person_embeddings SET is_representative = (face_id = ANY(%s)) "
        "WHERE person_id = %s",
        (reps, person_id),
    )


def set_adaptive_threshold(
    cur: PgCursor, person_id: int, threshold: Optional[float]
) -> None:
    """Store a person's adaptive threshold (NULL -> fall back to the global one)."""
    cur.execute(
        "UPDATE persons SET adaptive_threshold = %s, updated_at = now() WHERE id = %s",
        (None if threshold is None else float(threshold), person_id),
    )


def fetch_person_representatives(
    cur: PgCursor,
) -> list[tuple[int, Optional[float], "np.ndarray"]]:
    """Return (person_id, adaptive_threshold, representative_embeddings) per person.

    Only people with at least one representative are returned — the primary
    matching path for recognition.
    """
    import numpy as np

    cur.execute(
        """
        SELECT pe.person_id, p.adaptive_threshold, pe.embedding
          FROM person_embeddings pe
          JOIN persons p ON p.id = pe.person_id
         WHERE pe.is_representative
         ORDER BY pe.person_id, pe.face_id
        """
    )
    grouped: dict[int, list[Any]] = {}
    thresholds: dict[int, Optional[float]] = {}
    for person_id, threshold, embedding in cur.fetchall():
        pid = int(person_id)
        grouped.setdefault(pid, []).append(embedding)
        thresholds[pid] = None if threshold is None else float(threshold)
    return [
        (pid, thresholds[pid], _embeddings_to_matrix(vectors))
        for pid, vectors in grouped.items()
    ]


def clear_person_gallery(cur: PgCursor, person_id: int) -> None:
    """Remove all gallery rows for a person (before a full rebuild, e.g. a merge)."""
    cur.execute("DELETE FROM person_embeddings WHERE person_id = %s", (person_id,))


def persons_missing_gallery(cur: PgCursor) -> list[int]:
    """Person ids that have assigned faces but no gallery rows yet (backfill set)."""
    cur.execute(
        """
        SELECT DISTINCT f.person_id
          FROM faces f
         WHERE f.person_id IS NOT NULL
           AND NOT EXISTS (
               SELECT 1 FROM person_embeddings pe WHERE pe.person_id = f.person_id
           )
        ORDER BY f.person_id
        """
    )
    return [int(r[0]) for r in cur.fetchall()]


def recompute_person_profile(cur: PgCursor, person_id: int) -> int:
    """Recompute a person's centroid + face_count from their current faces.

    Returns the new face count (0 if the person has no faces left).
    """
    import numpy as np

    _ids, _scores, embeddings = _face_vectors_for_person(cur, person_id)
    count = int(embeddings.shape[0])
    if count:
        centroid = embeddings.mean(axis=0)
        norm = float(np.linalg.norm(centroid))
        centroid = (centroid / norm) if norm else centroid
        cur.execute(
            "UPDATE persons SET face_count = %s, centroid = %s, updated_at = now() WHERE id = %s",
            (count, centroid.tolist(), person_id),
        )
    else:
        cur.execute(
            "UPDATE persons SET face_count = 0, updated_at = now() WHERE id = %s",
            (person_id,),
        )
    return count


def unassign_person_faces_in_photos(
    cur: PgCursor, person_id: int, photo_ids: Sequence[int]
) -> list[int]:
    """Detach a person's faces that lie in the given photos; return their ids."""
    cur.execute(
        "UPDATE faces SET person_id = NULL "
        "WHERE person_id = %s AND photo_id = ANY(%s) RETURNING id",
        (person_id, list(photo_ids)),
    )
    return [int(r[0]) for r in cur.fetchall()]


# ---------------------------------------------------------------------------
# Recognition feedback (correction memory)
# ---------------------------------------------------------------------------
def record_feedback(
    cur: PgCursor, face_id: int, person_id: int, verdict: str = "reject"
) -> None:
    """Record that a face was rejected from (or confirmed for) a person."""
    cur.execute(
        """
        INSERT INTO recognition_feedback (face_id, person_id, verdict)
        VALUES (%s, %s, %s)
        ON CONFLICT (face_id, person_id) DO UPDATE
            SET verdict = EXCLUDED.verdict, created_at = now()
        """,
        (face_id, person_id, verdict),
    )


def list_person_representatives_detail(
    cur: PgCursor, person_id: int
) -> list[dict[str, Any]]:
    """Return a person's representative faces for display (crop + quality + date).

    Ordered best-quality first. Powers the "what PhotoSphere learned" strip on a
    person's page. ``photo_id`` lets the UI open the source photo.
    """
    cur.execute(
        """
        SELECT pe.face_id, f.crop_path, pe.quality, f.photo_id, p.taken_at
          FROM person_embeddings pe
          JOIN faces f  ON f.id = pe.face_id
          JOIN photos p ON p.id = f.photo_id
         WHERE pe.person_id = %s AND pe.is_representative
         ORDER BY pe.quality DESC, pe.face_id
        """,
        (person_id,),
    )
    return [
        {
            "face_id": int(r[0]),
            "crop_path": r[1],
            "quality": float(r[2]),
            "photo_id": int(r[3]),
            "taken_at": r[4],
        }
        for r in cur.fetchall()
    ]


def detach_faces(cur: PgCursor, face_ids: Sequence[int]) -> None:
    """Un-assign a set of faces from whatever person they belong to."""
    cur.execute("UPDATE faces SET person_id = NULL WHERE id = ANY(%s)", (list(face_ids),))


def fetch_person_context_rows(
    cur: PgCursor,
) -> list[tuple[int, Any, Optional[float], Optional[float]]]:
    """Return (person_id, taken_at, gps_lat, gps_lon) for grouped faces' photos.

    Distinct per (person, photo) so a busy photo counts once; feeds context fusion.
    """
    cur.execute(
        """
        SELECT DISTINCT f.person_id, p.taken_at, p.gps_latitude, p.gps_longitude
          FROM faces f
          JOIN photos p ON p.id = f.photo_id
         WHERE f.person_id IS NOT NULL
        """
    )
    return [(int(r[0]), r[1], r[2], r[3]) for r in cur.fetchall()]


def fetch_faces_photo_context(
    cur: PgCursor, face_ids: Sequence[int]
) -> dict[int, tuple[Any, Optional[float], Optional[float]]]:
    """Return face_id -> (taken_at, gps_lat, gps_lon) for the given faces."""
    if not face_ids:
        return {}
    cur.execute(
        """
        SELECT f.id, p.taken_at, p.gps_latitude, p.gps_longitude
          FROM faces f
          JOIN photos p ON p.id = f.photo_id
         WHERE f.id = ANY(%s)
        """,
        (list(face_ids),),
    )
    return {int(r[0]): (r[1], r[2], r[3]) for r in cur.fetchall()}


def record_suggestion(cur: PgCursor, face_id: int, person_id: int, score: float) -> None:
    """Record (or refresh) a borderline 'Is this <person>?' suggestion for a face."""
    cur.execute(
        """
        INSERT INTO recognition_suggestions (face_id, person_id, score)
        VALUES (%s, %s, %s)
        ON CONFLICT (face_id) DO UPDATE
            SET person_id = EXCLUDED.person_id, score = EXCLUDED.score, created_at = now()
        """,
        (face_id, person_id, float(score)),
    )


def delete_suggestion(cur: PgCursor, face_id: int) -> None:
    """Drop a face's pending suggestion (after it is answered or assigned)."""
    cur.execute("DELETE FROM recognition_suggestions WHERE face_id = %s", (face_id,))


def delete_grouped_suggestions(cur: PgCursor) -> None:
    """Clear suggestions for faces that are no longer ungrouped (e.g. clustered)."""
    cur.execute(
        """
        DELETE FROM recognition_suggestions rs
         USING faces f
         WHERE rs.face_id = f.id AND f.person_id IS NOT NULL
        """
    )


def list_suggestions_for_person(cur: PgCursor, person_id: int) -> list[dict[str, Any]]:
    """Pending suggestions proposing this person, best score first (ungrouped only)."""
    cur.execute(
        """
        SELECT rs.face_id, f.crop_path, rs.score, f.photo_id
          FROM recognition_suggestions rs
          JOIN faces f ON f.id = rs.face_id
         WHERE rs.person_id = %s AND f.person_id IS NULL
         ORDER BY rs.score DESC, rs.face_id
        """,
        (person_id,),
    )
    return [
        {"face_id": int(r[0]), "crop_path": r[1], "score": float(r[2]), "photo_id": int(r[3])}
        for r in cur.fetchall()
    ]


def count_suggestions(cur: PgCursor) -> int:
    """Total pending suggestions for still-ungrouped faces."""
    cur.execute(
        """
        SELECT count(*) FROM recognition_suggestions rs
          JOIN faces f ON f.id = rs.face_id
         WHERE f.person_id IS NULL
        """
    )
    return int(cur.fetchone()[0])


def fetch_person_names(cur: PgCursor) -> dict[int, Optional[str]]:
    """person_id -> display_name (None when unnamed) for every person."""
    cur.execute("SELECT id, display_name FROM persons")
    return {int(r[0]): r[1] for r in cur.fetchall()}


# ---------------------------------------------------------------------------
# Person-merge suggestions (anti-fragmentation)
# ---------------------------------------------------------------------------
def _ordered_pair(a: int, b: int) -> tuple[int, int]:
    return (a, b) if a < b else (b, a)


def replace_merge_suggestions(
    cur: PgCursor, rows: Sequence[tuple[int, int, float]]
) -> None:
    """Replace the whole suggestion set with this scan's results."""
    cur.execute("DELETE FROM person_merge_suggestions")
    if not rows:
        return
    from psycopg2.extras import execute_values

    execute_values(
        cur,
        "INSERT INTO person_merge_suggestions (person_a, person_b, score) VALUES %s",
        [(*_ordered_pair(int(a), int(b)), float(s)) for a, b, s in rows],
    )


def fetch_merge_rejections(cur: PgCursor) -> set[tuple[int, int]]:
    """Pairs the user said are NOT the same person (ordered a < b)."""
    cur.execute("SELECT person_a, person_b FROM person_merge_rejections")
    return {(int(r[0]), int(r[1])) for r in cur.fetchall()}


def record_merge_rejection(cur: PgCursor, person_a: int, person_b: int) -> None:
    """Remember 'not the same person' and drop the pending suggestion."""
    a, b = _ordered_pair(person_a, person_b)
    cur.execute(
        "INSERT INTO person_merge_rejections (person_a, person_b) VALUES (%s, %s) "
        "ON CONFLICT (person_a, person_b) DO NOTHING",
        (a, b),
    )
    cur.execute(
        "DELETE FROM person_merge_suggestions WHERE person_a = %s AND person_b = %s",
        (a, b),
    )


def list_merge_suggestions_detail(cur: PgCursor) -> list[dict[str, Any]]:
    """Pending 'Same person?' pairs with names, counts and covers, best first."""
    cur.execute(
        """
        SELECT s.person_a, s.person_b, s.score,
               pa.display_name, pa.face_count, fa.crop_path,
               pb.display_name, pb.face_count, fb.crop_path
          FROM person_merge_suggestions s
          JOIN persons pa ON pa.id = s.person_a
          JOIN persons pb ON pb.id = s.person_b
          LEFT JOIN faces fa ON fa.id = pa.cover_face_id
          LEFT JOIN faces fb ON fb.id = pb.cover_face_id
         ORDER BY s.score DESC, s.id
        """
    )
    return [
        {
            "person_a": int(r[0]), "person_b": int(r[1]), "score": float(r[2]),
            "name_a": r[3], "count_a": int(r[4]), "cover_a": r[5],
            "name_b": r[6], "count_b": int(r[7]), "cover_b": r[8],
        }
        for r in cur.fetchall()
    ]


def fetch_rejections(cur: PgCursor) -> dict[int, set[int]]:
    """Return person_id -> set(face_id) of rejected pairs (recognition blocklist)."""
    cur.execute(
        "SELECT person_id, face_id FROM recognition_feedback WHERE verdict = 'reject'"
    )
    rejections: dict[int, set[int]] = {}
    for person_id, face_id in cur.fetchall():
        rejections.setdefault(int(person_id), set()).add(int(face_id))
    return rejections


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


def list_timeline_buckets(cur: PgCursor) -> list[tuple[int, int, int]]:
    """Return (year, month, count) buckets for dated photos, newest first."""
    cur.execute(
        """
        SELECT EXTRACT(YEAR FROM taken_at)::int AS y,
               EXTRACT(MONTH FROM taken_at)::int AS m,
               count(*)
          FROM photos
         WHERE taken_at IS NOT NULL
         GROUP BY y, m
         ORDER BY y DESC, m DESC
        """
    )
    return [(int(r[0]), int(r[1]), int(r[2])) for r in cur.fetchall()]


def list_photos_by_month(
    cur: PgCursor, year: int, month: int, limit: int, offset: int = 0
) -> list[tuple[int, str, Optional[str], Any]]:
    """Return (id, file_path, thumbnail_path, taken_at) for one month, newest first."""
    cur.execute(
        """
        SELECT id, file_path, thumbnail_path, taken_at
          FROM photos
         WHERE taken_at >= make_date(%s, %s, 1)
           AND taken_at <  (make_date(%s, %s, 1) + interval '1 month')
         ORDER BY taken_at DESC, id DESC
         LIMIT %s OFFSET %s
        """,
        (year, month, year, month, limit, offset),
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
    rows = search_candidates(cur, query_vector, model, limit)
    return [(r[0], r[1], r[2], r[3], r[5]) for r in rows]


def search_candidates(
    cur: PgCursor,
    query_vector: Sequence[float],
    model: str,
    limit: int,
    favorite: bool = False,
    since: Any = None,
    until: Any = None,
    person_id: Optional[int] = None,
) -> list[tuple[int, str, Optional[str], Any, bool, float]]:
    """Return a filtered candidate pool for unified search ranking.

    Rows are (id, file_path, thumbnail_path, taken_at, is_favorite, similarity)
    ordered by CLIP similarity descending. Structured filters (favorite, date
    range, person) are applied in SQL so ranking works on the right subset.
    """
    vec = list(query_vector)
    clauses = ["ce.model = %s"]
    params: list[Any] = [vec, model]  # first %s is the SELECT similarity vector

    if favorite:
        clauses.append("p.is_favorite = TRUE")
    if since is not None:
        clauses.append("p.taken_at >= %s")
        params.append(since)
    if until is not None:
        clauses.append("p.taken_at <= %s")
        params.append(until)
    if person_id is not None:
        # EXISTS avoids row duplication when a photo has several faces of one person.
        clauses.append("EXISTS (SELECT 1 FROM faces f WHERE f.photo_id = p.id AND f.person_id = %s)")
        params.append(person_id)

    where = " AND ".join(clauses)
    params.append(vec)     # ORDER BY vector
    params.append(limit)
    cur.execute(
        f"""
        SELECT p.id, p.file_path, p.thumbnail_path, p.taken_at, p.is_favorite,
               1 - (ce.embedding <=> %s::vector) AS sim
          FROM clip_embeddings ce
          JOIN photos p ON p.id = ce.photo_id
         WHERE {where}
         ORDER BY ce.embedding <=> %s::vector
         LIMIT %s
        """,
        params,
    )
    return [
        (int(r[0]), r[1], r[2], r[3], bool(r[4]), float(r[5])) for r in cur.fetchall()
    ]


def find_similar_photos(
    cur: PgCursor, photo_id: int, limit: int = 100
) -> list[tuple[int, str, Optional[str], Any]]:
    """Return photos visually similar to ``photo_id`` (CLIP nearest neighbours).

    Works purely from stored embeddings — no model needed at query time. Returns
    (id, file_path, thumbnail_path, taken_at) ordered by similarity, excluding
    the source photo. Empty if the photo has no CLIP embedding.
    """
    import numpy as np

    cur.execute("SELECT embedding, model FROM clip_embeddings WHERE photo_id = %s", (photo_id,))
    row = cur.fetchone()
    if row is None:
        return []
    embedding, model = row
    vec = embedding.to_numpy() if hasattr(embedding, "to_numpy") else np.asarray(embedding)
    cur.execute(
        """
        SELECT p.id, p.file_path, p.thumbnail_path, p.taken_at
          FROM clip_embeddings ce
          JOIN photos p ON p.id = ce.photo_id
         WHERE ce.model = %s AND ce.photo_id <> %s
         ORDER BY ce.embedding <=> %s::vector
         LIMIT %s
        """,
        (model, photo_id, vec.tolist(), limit),
    )
    return [(int(r[0]), r[1], r[2], r[3]) for r in cur.fetchall()]


def set_favorite(cur: PgCursor, photo_id: int, favorite: bool) -> None:
    """Mark or unmark a photo as a favorite (a user signal used by ranking)."""
    cur.execute(
        "UPDATE photos SET is_favorite = %s, updated_at = now() WHERE id = %s",
        (favorite, photo_id),
    )


def find_person_id_by_exact_name(cur: PgCursor, name: str) -> Optional[int]:
    """Return the person id whose display_name equals ``name`` (case-insensitive).

    Returns None if there is no match or the name is ambiguous (>1 person), so
    auto person-filtering in search never guesses.
    """
    cur.execute(
        "SELECT id FROM persons WHERE lower(display_name) = lower(%s)",
        (name.strip(),),
    )
    ids = [r[0] for r in cur.fetchall()]
    return int(ids[0]) if len(ids) == 1 else None


# ---------------------------------------------------------------------------
# OCR helpers
# ---------------------------------------------------------------------------
def stream_photos_needing_ocr(
    conn: PgConnection, limit: Optional[int] = None
) -> Iterator[tuple[int, str]]:
    """Yield (id, file_path) for photos with no OCR run yet.

    ``ocr_text IS NULL`` means not processed; an empty string means processed
    with no text found, so those are not re-processed.
    """
    sql = "SELECT id, file_path FROM photos WHERE ocr_text IS NULL ORDER BY id"
    params: tuple[Any, ...] = ()
    if limit is not None:
        sql += " LIMIT %s"
        params = (limit,)
    with conn.cursor(name="pending_ocr") as cur:
        cur.itersize = 256
        cur.execute(sql, params)
        for row in cur:
            yield int(row[0]), row[1]


def count_photos_needing_ocr(cur: PgCursor) -> int:
    """Count photos not yet processed by OCR."""
    cur.execute("SELECT count(*) FROM photos WHERE ocr_text IS NULL")
    return int(cur.fetchone()[0])


def set_ocr_text(cur: PgCursor, photo_id: int, text: str) -> None:
    """Store extracted OCR text (empty string marks 'processed, no text')."""
    cur.execute(
        "UPDATE photos SET ocr_text = %s, updated_at = now() WHERE id = %s",
        (text, photo_id),
    )


def count_ocr_texts(cur: PgCursor) -> int:
    """Count photos that have non-empty OCR text."""
    cur.execute("SELECT count(*) FROM photos WHERE ocr_text IS NOT NULL AND ocr_text <> ''")
    return int(cur.fetchone()[0])


def search_photos_by_ocr(
    cur: PgCursor,
    tokens: Sequence[str],
    limit: int,
    favorite: bool = False,
    since: Any = None,
    until: Any = None,
    person_id: Optional[int] = None,
) -> list[tuple[int, str, Optional[str], Any, bool]]:
    """Return photos whose OCR text contains any of ``tokens`` (+ filters).

    Rows are (id, file_path, thumbnail_path, taken_at, is_favorite), newest
    first. Uses the trigram index for fast substring matching.
    """
    tokens = [t for t in tokens if len(t) >= 3]
    if not tokens:
        return []
    clauses = ["p.ocr_text IS NOT NULL"]
    params: list[Any] = []

    ors = " OR ".join(["p.ocr_text ILIKE %s"] * len(tokens))
    clauses.append(f"({ors})")
    params.extend(f"%{t}%" for t in tokens)

    if favorite:
        clauses.append("p.is_favorite = TRUE")
    if since is not None:
        clauses.append("p.taken_at >= %s")
        params.append(since)
    if until is not None:
        clauses.append("p.taken_at <= %s")
        params.append(until)
    if person_id is not None:
        clauses.append("EXISTS (SELECT 1 FROM faces f WHERE f.photo_id = p.id AND f.person_id = %s)")
        params.append(person_id)

    params.append(limit)
    cur.execute(
        f"""
        SELECT p.id, p.file_path, p.thumbnail_path, p.taken_at, p.is_favorite
          FROM photos p
         WHERE {" AND ".join(clauses)}
         ORDER BY p.taken_at DESC NULLS LAST, p.id DESC
         LIMIT %s
        """,
        params,
    )
    return [(int(r[0]), r[1], r[2], r[3], bool(r[4])) for r in cur.fetchall()]


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
