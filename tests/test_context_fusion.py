"""Integration test: context fusion lifts a borderline face over the line.

Same face similarity, two contexts: taken the same day + place as the person's
photos (assigned), vs. an unrelated time/place (left as a suggestion). Uses
``clean_db`` (skips if Postgres is unreachable).
"""

from __future__ import annotations

import datetime as _dt
import math

import numpy as np

from clustering.clusterer import normalize_embeddings
from clustering.incremental import update_people
from database import db
from viewer import data

DIM = 512
_RNG = np.random.default_rng(31)
_R = normalize_embeddings(_RNG.standard_normal((1, DIM)).astype("float32"))[0]
_TMP = _RNG.standard_normal(DIM).astype("float32")
_O = _TMP - (_TMP @ _R) * _R
_O = _O / np.linalg.norm(_O)

_DAY = _dt.datetime(2021, 7, 4, 10, 0, 0)
_LAT, _LON = 37.775, -122.419


def _at_cosine(cos: float) -> np.ndarray:
    return cos * _R + math.sqrt(max(0.0, 1.0 - cos * cos)) * _O


def _photo(path, taken_at=None, lat=None, lon=None) -> int:
    meta = db.PhotoMetadata(
        file_path=path, file_hash="0" * 64, file_size=1,
        file_mtime=_dt.datetime(2021, 1, 1),
        taken_at=taken_at, gps_latitude=lat, gps_longitude=lon,
    )
    with db.connection() as conn, conn.cursor() as cur:
        return db.insert_photo(cur, meta)


def _insert_face(photo_id: int, emb: np.ndarray) -> int:
    with db.connection() as conn, conn.cursor() as cur:
        return db.insert_face(cur, photo_id, (0, 0, 120, 120), emb.tolist(), det_score=0.9)


def _make_person_with_context() -> int:
    """A person whose photos are all on _DAY at (_LAT, _LON)."""
    for i in range(3):
        photo = _photo(f"/virtual/ctx_person_{i}.jpg", _DAY, _LAT, _LON)
        _insert_face(photo, _R + _RNG.standard_normal(DIM).astype("float32") * 0.003)
    update_people(eps=0.35, min_samples=2)
    with db.connection() as conn, conn.cursor() as cur:
        cur.execute("SELECT id FROM persons")
        return int(cur.fetchone()[0])


def test_matching_context_promotes_a_borderline_face(clean_db) -> None:
    pid = _make_person_with_context()
    # Borderline similarity (0.52 < 0.55), BUT same day + same place.
    photo = _photo("/virtual/ctx_same.jpg", _DAY, _LAT, _LON)
    face = _insert_face(photo, _at_cosine(0.52))
    update_people(eps=0.35, min_samples=2)

    with db.connection() as conn, conn.cursor() as cur:
        cur.execute("SELECT person_id FROM faces WHERE id = %s", (face,))
        assert cur.fetchone()[0] == pid          # context lifted it to a match
    assert not data.suggestions_for_person(pid)  # accepted, not merely suggested


def test_without_matching_context_it_stays_a_suggestion(clean_db) -> None:
    pid = _make_person_with_context()
    # Same borderline similarity, but a different day and no location.
    photo = _photo("/virtual/ctx_other.jpg", _dt.datetime(2010, 1, 1, 8, 0, 0))
    face = _insert_face(photo, _at_cosine(0.52))
    update_people(eps=0.35, min_samples=2)

    with db.connection() as conn, conn.cursor() as cur:
        cur.execute("SELECT person_id FROM faces WHERE id = %s", (face,))
        assert cur.fetchone()[0] is None         # no boost -> not assigned
    assert face in [s["face_id"] for s in data.suggestions_for_person(pid)]
