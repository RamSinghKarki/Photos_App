"""Integration tests for Module 2 (faces) using a stub detector.

The real InsightFace model needs a GPU/model download, so these tests inject a
deterministic stub detector. That exercises everything the pipeline owns —
crop saving, database writes (including the pgvector embedding column), batching
and per-photo error isolation — without the heavy runtime.
"""

from __future__ import annotations

from pathlib import Path
from typing import List

import numpy as np

from database import db
from faces.detector import DetectedFace
from faces.processor import process_faces
from scanner.scanner import scan_directory


class StubDetector:
    """Return a fixed number of deterministic faces for any image.

    Embeddings have the configured dimension so they land in the ``vector(512)``
    column exactly like real ones.
    """

    def __init__(self, faces_per_image: int = 1, dim: int = 512) -> None:
        self.faces_per_image = faces_per_image
        self.dim = dim

    def detect(self, image_rgb: np.ndarray) -> List[DetectedFace]:
        height, width = image_rgb.shape[:2]
        out: List[DetectedFace] = []
        for i in range(self.faces_per_image):
            # A small in-bounds box; deterministic embedding seeded by index.
            bbox = (i, i, max(1, width // 2), max(1, height // 2))
            embedding = ((np.arange(self.dim, dtype=np.float32) + i) / self.dim).tolist()
            out.append(DetectedFace(bbox=bbox, det_score=0.9, embedding=embedding))
        return out


def _scan(photo_tree: Path) -> None:
    scan_directory(photo_tree)


# The fixture tree has 5 stored photos, of which 4 are real, openable images
# (a.jpg, sub/b.png, sub/a_copy.jpg, with_exif.jpg) and one (broken.jpg) has an
# image extension but invalid bytes, so the face module cannot open it.
READABLE = 4


def test_faces_detected_and_stored(clean_db, photo_tree: Path) -> None:
    _scan(photo_tree)
    summary = process_faces(StubDetector(faces_per_image=1))

    assert summary.photos == READABLE     # 4 openable images
    assert summary.faces == READABLE      # one face each
    assert summary.unreadable == 1        # broken.jpg
    assert summary.errors == 0

    with db.connection() as conn, conn.cursor() as cur:
        assert db.count_faces(cur) == READABLE
        # Embedding round-trips at the right dimension.
        cur.execute("SELECT vector_dims(embedding) FROM faces LIMIT 1")
        assert cur.fetchone()[0] == 512
        # Every photo is flagged processed (readable + unreadable alike).
        cur.execute("SELECT count(*) FROM photos WHERE faces_processed = FALSE")
        assert cur.fetchone()[0] == 0

    # A crop file was written to the cache for each face.
    with db.connection() as conn, conn.cursor() as cur:
        cur.execute("SELECT crop_path FROM faces")
        for (crop_path,) in cur.fetchall():
            assert Path(crop_path).exists()


def test_multiple_faces_per_photo(clean_db, photo_tree: Path) -> None:
    _scan(photo_tree)
    summary = process_faces(StubDetector(faces_per_image=3))

    assert summary.faces == READABLE * 3
    with db.connection() as conn, conn.cursor() as cur:
        # a.jpg (the lowest id, a real image) gets exactly 3 faces.
        cur.execute("SELECT count(*) FROM faces WHERE photo_id = (SELECT min(id) FROM photos)")
        assert cur.fetchone()[0] == 3


def test_no_faces_counts_as_no_faces(clean_db, photo_tree: Path) -> None:
    _scan(photo_tree)
    summary = process_faces(StubDetector(faces_per_image=0))

    assert summary.faces == 0
    assert summary.photos == READABLE
    assert summary.no_faces == READABLE
    with db.connection() as conn, conn.cursor() as cur:
        assert db.count_faces(cur) == 0
        # Photos are still marked processed so they aren't re-examined forever.
        cur.execute("SELECT count(*) FROM photos WHERE faces_processed = FALSE")
        assert cur.fetchone()[0] == 0


def test_processing_is_idempotent(clean_db, photo_tree: Path) -> None:
    _scan(photo_tree)
    process_faces(StubDetector(1))
    second = process_faces(StubDetector(1))

    assert second.photos == 0        # nothing left pending
    assert second.unreadable == 0    # broken.jpg was marked processed already
    with db.connection() as conn, conn.cursor() as cur:
        assert db.count_faces(cur) == READABLE  # no duplicate faces added


def test_reprocess_replaces_not_appends(clean_db, photo_tree: Path) -> None:
    _scan(photo_tree)
    process_faces(StubDetector(1))
    process_faces(StubDetector(2), reprocess=True)

    with db.connection() as conn, conn.cursor() as cur:
        # 4 readable photos * 2 faces, NOT 4*(1+2): old faces were cleared first.
        assert db.count_faces(cur) == READABLE * 2


def test_streaming_survives_frequent_commits(clean_db, photo_tree: Path) -> None:
    # batch_size=1 commits the write connection after every photo *while* the
    # read connection is still streaming pending photos. This guards the
    # two-connection design against a regression to a single connection (where
    # committing would invalidate the server-side read cursor).
    _scan(photo_tree)
    summary = process_faces(StubDetector(1), batch_size=1)

    assert summary.photos == READABLE
    assert summary.faces == READABLE
    with db.connection() as conn, conn.cursor() as cur:
        assert db.count_faces(cur) == READABLE


def test_detect_faces_on_selected_photos_only(clean_db, photo_tree: Path) -> None:
    _scan(photo_tree)
    # Pick two specific real photos to process manually.
    with db.connection() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT id FROM photos WHERE file_path LIKE '%a.jpg' "
            "OR file_path LIKE '%b.png' ORDER BY id"
        )
        chosen = [r[0] for r in cur.fetchall()]
    assert len(chosen) == 2

    summary = process_faces(StubDetector(1), photo_ids=chosen)

    assert summary.photos == 2          # only the selected photos
    assert summary.faces == 2
    with db.connection() as conn, conn.cursor() as cur:
        assert db.count_faces(cur) == 2
        # Faces belong only to the chosen photos.
        cur.execute("SELECT DISTINCT photo_id FROM faces ORDER BY photo_id")
        assert [r[0] for r in cur.fetchall()] == chosen


def test_selected_detection_replaces_existing_faces(clean_db, photo_tree: Path) -> None:
    _scan(photo_tree)
    with db.connection() as conn, conn.cursor() as cur:
        cur.execute("SELECT id FROM photos WHERE file_path LIKE '%a.jpg'")
        chosen = [cur.fetchone()[0]]

    process_faces(StubDetector(1), photo_ids=chosen)
    process_faces(StubDetector(3), photo_ids=chosen)  # re-run replaces, not appends

    with db.connection() as conn, conn.cursor() as cur:
        assert db.count_faces(cur) == 3  # 3 faces, not 1 + 3


def test_one_bad_photo_does_not_abort_batch(clean_db, photo_tree: Path) -> None:
    _scan(photo_tree)
    # Delete one *real* image after scanning so its row points at a missing file.
    with db.connection() as conn, conn.cursor() as cur:
        cur.execute("SELECT file_path FROM photos WHERE file_path LIKE '%with_exif.jpg'")
        (path,) = cur.fetchone()
    Path(path).unlink()

    summary = process_faces(StubDetector(1))

    # broken.jpg + the now-missing with_exif.jpg are both unreadable; the other
    # three real images still process successfully.
    assert summary.unreadable == 2
    assert summary.photos == 3
    assert summary.errors == 0
    with db.connection() as conn, conn.cursor() as cur:
        assert db.count_faces(cur) == 3
