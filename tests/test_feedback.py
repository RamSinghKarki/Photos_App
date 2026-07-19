"""Integration tests for recognition feedback memory (Stage 10).

The promise: once the user corrects an assignment, the recognition engine must
never re-assign that face to that person again. Uses ``clean_db`` (skips if
Postgres is unreachable).
"""

from __future__ import annotations

import datetime as _dt

import numpy as np

from clustering.clusterer import normalize_embeddings
from clustering.incremental import update_people
from database import db
from viewer import data

DIM = 512
_RNG = np.random.default_rng(11)
_CENTER = normalize_embeddings(_RNG.standard_normal((1, DIM)).astype("float32"))[0]


def _photo(path: str) -> int:
    meta = db.PhotoMetadata(
        file_path=path, file_hash="0" * 64, file_size=1,
        file_mtime=_dt.datetime(2021, 1, 1),
    )
    with db.connection() as conn, conn.cursor() as cur:
        return db.insert_photo(cur, meta)


def _insert_face(photo_id: int, emb: np.ndarray) -> int:
    with db.connection() as conn, conn.cursor() as cur:
        return db.insert_face(cur, photo_id, (0, 0, 120, 120), emb.tolist(), det_score=0.9)


def _near(scale: float = 0.01) -> np.ndarray:
    return _CENTER + _RNG.standard_normal(DIM).astype("float32") * scale


def test_rejected_face_is_not_reassigned(clean_db) -> None:
    # One person formed from several near-identical faces, each its own photo.
    photos = [_photo(f"/virtual/fb_{i}.jpg") for i in range(4)]
    for p in photos:
        _insert_face(p, _near())
    update_people(eps=0.35, min_samples=2)

    with db.connection() as conn, conn.cursor() as cur:
        cur.execute("SELECT id FROM persons")
        person_id = cur.fetchone()[0]
        assert db.count_persons(cur) == 1

    # The user says the first photo is NOT this person.
    moved = data.remove_faces_from_person(person_id, [photos[0]])
    assert moved == 1

    with db.connection() as conn, conn.cursor() as cur:
        # A rejection is remembered and the face is detached.
        assert db.fetch_rejections(cur).get(person_id)
        cur.execute("SELECT person_id FROM faces WHERE photo_id = %s", (photos[0],))
        assert cur.fetchone()[0] is None

    # Running recognition again must NOT put it back — even though its embedding
    # still matches the person perfectly.
    update_people(eps=0.35, min_samples=2)
    with db.connection() as conn, conn.cursor() as cur:
        cur.execute("SELECT person_id FROM faces WHERE photo_id = %s", (photos[0],))
        assert cur.fetchone()[0] != person_id  # stays out (None or a different group)


def test_removing_all_faces_deletes_the_person(clean_db) -> None:
    photos = [_photo(f"/virtual/fb_all_{i}.jpg") for i in range(3)]
    for p in photos:
        _insert_face(p, _near())
    update_people(eps=0.35, min_samples=2)
    with db.connection() as conn, conn.cursor() as cur:
        cur.execute("SELECT id FROM persons")
        person_id = cur.fetchone()[0]

    moved = data.remove_faces_from_person(person_id, photos)
    assert moved == 3
    with db.connection() as conn, conn.cursor() as cur:
        assert db.count_persons(cur) == 0  # empty group removed
        # Its rejections cascade away with the person (person id won't recur).
        assert not db.fetch_rejections(cur)


def test_rejection_is_specific_to_the_face(clean_db) -> None:
    """Rejecting one face must not block a *different* face of the same person."""
    keep = [_photo(f"/virtual/fb_keep_{i}.jpg") for i in range(3)]
    for p in keep:
        _insert_face(p, _near())
    update_people(eps=0.35, min_samples=2)
    with db.connection() as conn, conn.cursor() as cur:
        cur.execute("SELECT id FROM persons")
        person_id = cur.fetchone()[0]

    data.remove_faces_from_person(person_id, [keep[0]])

    # A brand-new face (new photo) of the same person should still be recognized.
    new_photo = _photo("/virtual/fb_new.jpg")
    _insert_face(new_photo, _near())
    summary = update_people(eps=0.35, min_samples=2)
    assert summary.recognized == 1
    with db.connection() as conn, conn.cursor() as cur:
        cur.execute("SELECT person_id FROM faces WHERE photo_id = %s", (new_photo,))
        assert cur.fetchone()[0] == person_id
