"""Integration tests for active learning (Stage 9): borderline suggestions.

A face whose best match lands just below a person's threshold becomes a pending
"Is this <name>?" suggestion; confirming teaches the profile, rejecting remembers
"no". Uses ``clean_db`` (skips if Postgres is unreachable).
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
_RNG = np.random.default_rng(29)
_R = normalize_embeddings(_RNG.standard_normal((1, DIM)).astype("float32"))[0]
# A unit vector orthogonal to _R, to dial an exact cosine to the person.
_TMP = _RNG.standard_normal(DIM).astype("float32")
_O = _TMP - (_TMP @ _R) * _R
_O = _O / np.linalg.norm(_O)


def _at_cosine(cos: float) -> np.ndarray:
    """A unit vector at exactly ``cos`` cosine similarity to _R."""
    return cos * _R + math.sqrt(max(0.0, 1.0 - cos * cos)) * _O


def _independent() -> np.ndarray:
    """A fresh unit vector unrelated to _R (and to the borderline probe)."""
    return normalize_embeddings(_RNG.standard_normal((1, DIM)).astype("float32"))[0]


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


def _make_person() -> int:
    """Form one tight person along _R (threshold falls back to the global 0.55)."""
    for i in range(3):
        photo = _photo(f"/virtual/al_person_{i}.jpg")
        _insert_face(photo, _R + _RNG.standard_normal(DIM).astype("float32") * 0.003)
    update_people(eps=0.35, min_samples=2)
    with db.connection() as conn, conn.cursor() as cur:
        cur.execute("SELECT id FROM persons")
        return int(cur.fetchone()[0])


def test_borderline_face_becomes_a_suggestion(clean_db) -> None:
    pid = _make_person()
    # Just below the 0.55 bar (band [0.48, 0.55)) -> a suggestion.
    borderline = _insert_face(_photo("/virtual/al_border.jpg"), _at_cosine(0.52))
    # Clearly unrelated -> no suggestion, no assignment.
    _insert_face(_photo("/virtual/al_far.jpg"), _independent())
    update_people(eps=0.35, min_samples=2)

    suggestions = data.suggestions_for_person(pid)
    face_ids = [s["face_id"] for s in suggestions]
    assert borderline in face_ids
    assert len(suggestions) == 1  # the far face is not offered
    with db.connection() as conn, conn.cursor() as cur:
        cur.execute("SELECT person_id FROM faces WHERE id = %s", (borderline,))
        assert cur.fetchone()[0] is None  # not auto-assigned; awaiting the answer


def test_confirm_assigns_and_teaches(clean_db) -> None:
    pid = _make_person()
    borderline = _insert_face(_photo("/virtual/al_confirm.jpg"), _at_cosine(0.52))
    update_people(eps=0.35, min_samples=2)
    assert borderline in [s["face_id"] for s in data.suggestions_for_person(pid)]

    data.confirm_suggestion(borderline, pid)
    with db.connection() as conn, conn.cursor() as cur:
        cur.execute("SELECT person_id FROM faces WHERE id = %s", (borderline,))
        assert cur.fetchone()[0] == pid                      # now assigned
        assert not data.suggestions_for_person(pid)          # suggestion cleared
        cur.execute(
            "SELECT verdict FROM recognition_feedback WHERE face_id = %s AND person_id = %s",
            (borderline, pid),
        )
        assert cur.fetchone()[0] == "confirm"                # remembered as yes
        cur.execute("SELECT count(*) FROM person_embeddings WHERE person_id = %s", (pid,))
        assert cur.fetchone()[0] >= 1                         # folded into the gallery


def test_reject_is_remembered_and_not_reoffered(clean_db) -> None:
    pid = _make_person()
    borderline = _insert_face(_photo("/virtual/al_reject.jpg"), _at_cosine(0.52))
    update_people(eps=0.35, min_samples=2)
    assert borderline in [s["face_id"] for s in data.suggestions_for_person(pid)]

    data.reject_suggestion(borderline, pid)
    assert not data.suggestions_for_person(pid)  # suggestion cleared
    with db.connection() as conn, conn.cursor() as cur:
        assert borderline in db.fetch_rejections(cur).get(pid, set())

    # A later run must not re-offer the rejected face.
    update_people(eps=0.35, min_samples=2)
    assert not data.suggestions_for_person(pid)
    with db.connection() as conn, conn.cursor() as cur:
        cur.execute("SELECT person_id FROM faces WHERE id = %s", (borderline,))
        assert cur.fetchone()[0] is None  # stays ungrouped, never rejoins
