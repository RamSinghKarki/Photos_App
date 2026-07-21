"""Integration tests for recognition engine v2 (representative gallery).

These use the shared ``clean_db`` fixture (skipping if Postgres is unreachable).
Faces are given a large bounding box so their quality clears the learning bar —
recognition then hinges on the representative gallery, not on box size.
"""

from __future__ import annotations

import datetime as _dt

import numpy as np

from clustering.clusterer import normalize_embeddings, person_centroid
from clustering.incremental import rebuild_person_gallery, update_people
from clustering.processor import recluster
from database import db
from viewer import data

DIM = 512
_RNG = np.random.default_rng(7)
# Five clearly-distinct appearances of one identity (orthogonal-ish directions).
_APPEARANCES = normalize_embeddings(_RNG.standard_normal((5, DIM)).astype("float32"))


def _photo(path: str) -> int:
    meta = db.PhotoMetadata(
        file_path=path, file_hash="0" * 64, file_size=1,
        file_mtime=_dt.datetime(2021, 1, 1),
    )
    with db.connection() as conn, conn.cursor() as cur:
        return db.insert_photo(cur, meta)


def _insert_face(photo_id: int, emb: np.ndarray, det: float = 0.9) -> int:
    with db.connection() as conn, conn.cursor() as cur:
        return db.insert_face(cur, photo_id, (0, 0, 120, 120), emb.tolist(), det_score=det)


def _near(center: np.ndarray, scale: float = 0.01) -> np.ndarray:
    return center + _RNG.standard_normal(DIM).astype("float32") * scale


def test_gallery_keeps_diverse_reps_and_sets_threshold(clean_db) -> None:
    photo = _photo("/virtual/recog_gallery.jpg")
    face_ids = [_insert_face(photo, _APPEARANCES[i]) for i in range(5)]
    with db.connection() as conn, conn.cursor() as cur:
        pid = db.create_person(cur, face_count=5, cover_face_id=face_ids[0])
        db.assign_faces_to_person(cur, pid, face_ids)
        db.set_person_centroid(cur, pid, person_centroid(_APPEARANCES))
        rebuild_person_gallery(cur, pid)

    with db.connection() as conn, conn.cursor() as cur:
        stored, _quals, _embs = db.fetch_person_gallery(cur, pid)
        assert len(stored) == 5  # every high-quality face is stored
        cur.execute(
            "SELECT count(*) FROM person_embeddings "
            "WHERE person_id = %s AND is_representative",
            (pid,),
        )
        assert cur.fetchone()[0] >= 3  # distinct appearances -> multiple reps
        cur.execute("SELECT adaptive_threshold FROM persons WHERE id = %s", (pid,))
        threshold = cur.fetchone()[0]
        assert threshold is not None and 0.45 <= threshold <= 0.62


def test_recognizes_a_new_face_by_its_best_representative(clean_db) -> None:
    photo = _photo("/virtual/recog_match.jpg")
    face_ids = [_insert_face(photo, _APPEARANCES[i]) for i in range(5)]
    with db.connection() as conn, conn.cursor() as cur:
        pid = db.create_person(cur, face_count=5, cover_face_id=face_ids[0])
        db.assign_faces_to_person(cur, pid, face_ids)
        db.set_person_centroid(cur, pid, person_centroid(_APPEARANCES))
        rebuild_person_gallery(cur, pid)

    # A new face that looks like appearance #2 (a profile the centroid matches
    # only weakly) should still be recognized via that representative.
    new_photo = _photo("/virtual/recog_match_b.jpg")
    _insert_face(new_photo, _near(_APPEARANCES[2]))
    summary = update_people()

    assert summary.recognized == 1
    assert summary.new_people == 0
    with db.connection() as conn, conn.cursor() as cur:
        assert db.count_persons(cur) == 1
        assert db.count_ungrouped_faces(cur) == 0


def test_backfill_gives_pre_gallery_people_a_gallery(clean_db) -> None:
    photo = _photo("/virtual/recog_backfill.jpg")
    for _ in range(4):
        _insert_face(photo, _near(_APPEARANCES[0]))
    recluster(eps=0.35, min_samples=2)  # forms a person WITHOUT a gallery

    with db.connection() as conn, conn.cursor() as cur:
        assert db.persons_missing_gallery(cur)  # gallery is missing before backfill

    update_people()  # runs the one-time backfill

    with db.connection() as conn, conn.cursor() as cur:
        assert not db.persons_missing_gallery(cur)
        cur.execute("SELECT id FROM persons")
        pid = cur.fetchone()[0]
        stored, _q, _e = db.fetch_person_gallery(cur, pid)
        assert len(stored) >= 1


def test_merge_rebuilds_target_gallery(clean_db) -> None:
    photo = _photo("/virtual/recog_merge.jpg")
    a_ids = [_insert_face(photo, _near(_APPEARANCES[0])) for _ in range(3)]
    b_ids = [_insert_face(photo, _near(_APPEARANCES[1])) for _ in range(3)]
    update_people(eps=0.35, min_samples=2)  # two people, each with a gallery

    with db.connection() as conn, conn.cursor() as cur:
        cur.execute("SELECT person_id FROM faces WHERE id = %s", (a_ids[0],))
        person_a = cur.fetchone()[0]
        cur.execute("SELECT person_id FROM faces WHERE id = %s", (b_ids[0],))
        person_b = cur.fetchone()[0]
        assert person_a != person_b

    data.merge_person_into(person_b, person_a)  # rebuilds A's gallery

    with db.connection() as conn, conn.cursor() as cur:
        assert db.count_persons(cur) == 1
        stored, _q, _e = db.fetch_person_gallery(cur, person_a)
        assert len(stored) == 6  # all faces from both appearances
        cur.execute(
            "SELECT count(*) FROM person_embeddings "
            "WHERE person_id = %s AND is_representative",
            (person_a,),
        )
        assert cur.fetchone()[0] >= 2  # both appearances represented
