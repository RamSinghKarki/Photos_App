"""Tests for the self-improving loop: incremental, name-preserving recognition."""

from __future__ import annotations

import datetime as _dt

import numpy as np

from clustering.clusterer import normalize_embeddings
from clustering.incremental import update_people
from clustering.processor import recluster
from database import db

DIM = 512


def _photo() -> int:
    meta = db.PhotoMetadata(
        file_path="/virtual/inc_test.jpg", file_hash="0" * 64, file_size=1,
        file_mtime=_dt.datetime(2021, 1, 1),
    )
    with db.connection() as conn, conn.cursor() as cur:
        pid = db.insert_photo(cur, meta)
    return pid


def _insert_faces(photo_id: int, center: np.ndarray, n: int, noise: float = 0.01) -> None:
    rng = np.random.default_rng(int(abs(center.sum() * 1000)) % (2**32))
    with db.connection() as conn, conn.cursor() as cur:
        for _ in range(n):
            emb = (center + rng.standard_normal(DIM).astype("float32") * noise).tolist()
            db.insert_face(cur, photo_id, (0, 0, 10, 10), emb, det_score=0.9)


def _two_centers():
    rng = np.random.default_rng(42)
    return normalize_embeddings(rng.standard_normal((2, DIM)).astype("float32"))


def test_names_are_preserved_across_updates(clean_db) -> None:
    """The headline fix: updating people must NOT wipe user-assigned names."""
    photo = _photo()
    center_a, _ = _two_centers()
    _insert_faces(photo, center_a, 4)
    recluster(eps=0.35, min_samples=2)  # forms one person with a centroid

    with db.connection() as conn, conn.cursor() as cur:
        cur.execute("SELECT id FROM persons ORDER BY id")
        ram = cur.fetchone()[0]
        db.rename_person(cur, ram, "Ram")

    # New photos of the same person arrive.
    _insert_faces(photo, center_a, 3)
    summary = update_people(eps=0.35, min_samples=2)

    assert summary.recognized == 3          # auto-assigned to the existing person
    assert summary.new_people == 0
    with db.connection() as conn, conn.cursor() as cur:
        cur.execute("SELECT display_name, face_count FROM persons WHERE id = %s", (ram,))
        name, count = cur.fetchone()
        assert name == "Ram"                # name survived!
        assert count == 7                   # 4 + 3 folded into the profile
        assert db.count_persons(cur) == 1


def test_new_person_is_discovered_without_touching_existing(clean_db) -> None:
    photo = _photo()
    center_a, center_b = _two_centers()
    _insert_faces(photo, center_a, 4)
    recluster(eps=0.35, min_samples=2)
    with db.connection() as conn, conn.cursor() as cur:
        cur.execute("SELECT id FROM persons")
        ram = cur.fetchone()[0]
        db.rename_person(cur, ram, "Ram")

    # A different person's faces appear.
    _insert_faces(photo, center_b, 4)
    summary = update_people(eps=0.35, min_samples=2)

    assert summary.recognized == 0          # not close to Ram
    assert summary.new_people == 1          # a new group is discovered
    with db.connection() as conn, conn.cursor() as cur:
        assert db.count_persons(cur) == 2
        cur.execute("SELECT display_name FROM persons WHERE id = %s", (ram,))
        assert cur.fetchone()[0] == "Ram"   # existing person untouched


def test_low_confidence_faces_stay_ungrouped(clean_db) -> None:
    photo = _photo()
    center_a, center_b = _two_centers()
    _insert_faces(photo, center_a, 4)
    recluster(eps=0.35, min_samples=2)

    # A single far-away face: not close enough to assign, too few to cluster.
    _insert_faces(photo, center_b, 1)
    summary = update_people(eps=0.35, min_samples=2, threshold=0.55)

    assert summary.recognized == 0
    assert summary.new_people == 0
    with db.connection() as conn, conn.cursor() as cur:
        assert db.count_ungrouped_faces(cur) == 1   # left for later, not misfiled


def test_first_run_creates_people_like_before(clean_db) -> None:
    photo = _photo()
    center_a, center_b = _two_centers()
    _insert_faces(photo, center_a, 4)
    _insert_faces(photo, center_b, 4)
    # No existing people: update_people should discover both groups.
    summary = update_people(eps=0.35, min_samples=2)
    assert summary.recognized == 0
    assert summary.new_people == 2
    with db.connection() as conn, conn.cursor() as cur:
        assert db.count_persons(cur) == 2
