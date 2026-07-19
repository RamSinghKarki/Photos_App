"""Integration tests for the per-person appearance gallery data (Stage 12).

Covers `data.person_representatives` (what the person page shows) and
`data.reject_representative` (dropping a learned appearance). Uses ``clean_db``.
"""

from __future__ import annotations

import datetime as _dt

import numpy as np

from clustering.clusterer import normalize_embeddings, person_centroid
from clustering.incremental import rebuild_person_gallery
from database import db
from viewer import data

DIM = 512
_RNG = np.random.default_rng(23)
_APPEARANCES = normalize_embeddings(_RNG.standard_normal((5, DIM)).astype("float32"))


def _photo(path: str) -> int:
    meta = db.PhotoMetadata(
        file_path=path, file_hash="0" * 64, file_size=1,
        file_mtime=_dt.datetime(2021, 1, 1),
    )
    with db.connection() as conn, conn.cursor() as cur:
        return db.insert_photo(cur, meta)


def _person_with_appearances() -> tuple[int, list[int]]:
    face_ids = []
    for i in range(5):
        photo = _photo(f"/virtual/appear_{i}.jpg")
        with db.connection() as conn, conn.cursor() as cur:
            face_ids.append(
                db.insert_face(cur, photo, (0, 0, 120, 120), _APPEARANCES[i].tolist(), det_score=0.9)
            )
    with db.connection() as conn, conn.cursor() as cur:
        pid = db.create_person(cur, face_count=5, cover_face_id=face_ids[0])
        db.assign_faces_to_person(cur, pid, face_ids)
        db.set_person_centroid(cur, pid, person_centroid(_APPEARANCES))
        rebuild_person_gallery(cur, pid)
    return pid, face_ids


def test_person_representatives_returns_display_rows(clean_db) -> None:
    pid, _ = _person_with_appearances()
    reps = data.person_representatives(pid)
    assert len(reps) == 5  # five distinct appearances -> five representatives
    top = reps[0]
    assert {"face_id", "crop_path", "quality", "photo_id", "taken_at"} <= top.keys()
    qualities = [r["quality"] for r in reps]
    assert qualities == sorted(qualities, reverse=True)  # best-first


def test_reject_representative_drops_and_remembers(clean_db) -> None:
    pid, _ = _person_with_appearances()
    target = data.person_representatives(pid)[0]["face_id"]

    remaining = data.reject_representative(pid, target)
    assert remaining == 4

    reps = data.person_representatives(pid)
    assert target not in [r["face_id"] for r in reps]
    with db.connection() as conn, conn.cursor() as cur:
        assert target in db.fetch_rejections(cur).get(pid, set())
        cur.execute("SELECT person_id FROM faces WHERE id = %s", (target,))
        assert cur.fetchone()[0] is None  # detached from the person
