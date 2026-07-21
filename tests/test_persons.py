"""Tests for editing people: rename, delete (ungroup), and merge."""

from __future__ import annotations

import datetime as _dt

import numpy as np

from clustering.clusterer import normalize_embeddings
from clustering.processor import recluster
from database import db

DIM = 512


def _seed_two_people() -> None:
    """Create one photo with two tight face clusters -> two persons."""
    rng = np.random.default_rng(7)
    centers = normalize_embeddings(rng.standard_normal((2, DIM)).astype("float32"))
    meta = db.PhotoMetadata(
        file_path="/virtual/persons_test.jpg",
        file_hash="0" * 64,
        file_size=1,
        file_mtime=_dt.datetime(2021, 1, 1),
    )
    with db.connection() as conn, conn.cursor() as cur:
        photo_id = db.insert_photo(cur, meta)
        for ci, center in enumerate(centers):
            for _ in range(4):
                emb = (center + rng.standard_normal(DIM).astype("float32") * 0.01).tolist()
                db.insert_face(cur, photo_id, (0, 0, 10, 10), emb, det_score=0.9)
    recluster(eps=0.35, min_samples=2)


def _person_ids() -> list[int]:
    with db.connection() as conn, conn.cursor() as cur:
        cur.execute("SELECT id FROM persons ORDER BY id")
        return [r[0] for r in cur.fetchall()]


def test_rename_person(clean_db) -> None:
    _seed_two_people()
    pid = _person_ids()[0]
    with db.connection() as conn, conn.cursor() as cur:
        db.rename_person(cur, pid, "  Alice  ")
    with db.connection() as conn, conn.cursor() as cur:
        cur.execute("SELECT display_name FROM persons WHERE id = %s", (pid,))
        assert cur.fetchone()[0] == "Alice"  # trimmed
        # Empty/whitespace clears the name.
        db.rename_person(cur, pid, "   ")
        cur.execute("SELECT display_name FROM persons WHERE id = %s", (pid,))
        assert cur.fetchone()[0] is None


def test_delete_person_ungroups_faces(clean_db) -> None:
    _seed_two_people()
    ids = _person_ids()
    assert len(ids) == 2
    with db.connection() as conn, conn.cursor() as cur:
        cur.execute("SELECT count(*) FROM faces WHERE person_id = %s", (ids[0],))
        n_faces = cur.fetchone()[0]
        db.delete_person(cur, ids[0])
    with db.connection() as conn, conn.cursor() as cur:
        assert db.count_persons(cur) == 1               # person gone
        cur.execute("SELECT count(*) FROM faces")
        assert cur.fetchone()[0] == 8                   # faces kept, not deleted
        cur.execute("SELECT count(*) FROM faces WHERE person_id IS NULL")
        assert cur.fetchone()[0] == n_faces             # its faces are ungrouped


def test_merge_persons(clean_db) -> None:
    _seed_two_people()
    source, target = _person_ids()
    with db.connection() as conn, conn.cursor() as cur:
        db.merge_persons(cur, source, target)
    with db.connection() as conn, conn.cursor() as cur:
        assert db.count_persons(cur) == 1               # source removed
        cur.execute("SELECT face_count FROM persons WHERE id = %s", (target,))
        assert cur.fetchone()[0] == 8                   # 4 + 4 faces
        cur.execute("SELECT count(*) FROM faces WHERE person_id = %s", (target,))
        assert cur.fetchone()[0] == 8
        cur.execute("SELECT count(*) FROM faces WHERE person_id IS NULL")
        assert cur.fetchone()[0] == 0                   # nothing left ungrouped


def test_merge_into_self_is_noop(clean_db) -> None:
    _seed_two_people()
    pid = _person_ids()[0]
    with db.connection() as conn, conn.cursor() as cur:
        db.merge_persons(cur, pid, pid)
    with db.connection() as conn, conn.cursor() as cur:
        assert db.count_persons(cur) == 2  # unchanged
