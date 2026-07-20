"""Integration tests for the person-merge scan (anti-fragmentation).

The defect this heals: one identity photographed differently (angle, beard,
hairstyle, occlusion) fragments into several person profiles, and nothing ever
joined them. Uses ``clean_db`` (skips if Postgres is unreachable).
"""

from __future__ import annotations

import datetime as _dt
import math

import numpy as np

from clustering.clusterer import normalize_embeddings, person_centroid
from clustering.incremental import rebuild_person_gallery, update_people
from config.settings import get_settings
from clustering.merge_scan import scan_for_merges
from database import db
from viewer import data

DIM = 512
_RNG = np.random.default_rng(53)


def _unit() -> np.ndarray:
    return normalize_embeddings(_RNG.standard_normal((1, DIM)).astype("float32"))[0]


def _at_sim(base: np.ndarray, sim: float) -> np.ndarray:
    """A unit vector at exactly ``sim`` cosine to ``base``."""
    tmp = _RNG.standard_normal(DIM).astype("float32")
    orth = tmp - (tmp @ base) * base
    orth /= np.linalg.norm(orth)
    return sim * base + math.sqrt(max(0.0, 1.0 - sim * sim)) * orth


def _photo(path: str) -> int:
    meta = db.PhotoMetadata(
        file_path=path, file_hash="0" * 64, file_size=1,
        file_mtime=_dt.datetime(2021, 1, 1),
    )
    with db.connection() as conn, conn.cursor() as cur:
        return db.insert_photo(cur, meta)


def _face(photo_id: int, emb: np.ndarray, det: float = 0.9, side: int = 120) -> int:
    with db.connection() as conn, conn.cursor() as cur:
        return db.insert_face(
            cur, photo_id, (0, 0, side, side), emb.tolist(), det_score=det
        )


def _person(center: np.ndarray, n: int, tag: str) -> int:
    face_ids = []
    for i in range(n):
        emb = center + _RNG.standard_normal(DIM).astype("float32") * 0.01
        face_ids.append(_face(_photo(f"/virtual/ms_{tag}_{i}.jpg"), emb))
    with db.connection() as conn, conn.cursor() as cur:
        pid = db.create_person(cur, n, face_ids[0])
        db.assign_faces_to_person(cur, pid, face_ids)
        embs = np.vstack([center] * n)
        db.set_person_centroid(cur, pid, person_centroid(embs))
        rebuild_person_gallery(cur, pid)
    return pid


def test_split_identity_in_one_import_gets_a_suggestion(clean_db) -> None:
    """The reported bug: frontal + bearded shots form two people in one run."""
    frontal = _unit()
    bearded = _at_sim(frontal, 0.60)  # same person, different appearance
    for i in range(4):
        _face(_photo(f"/virtual/ms_f_{i}.jpg"), frontal + _RNG.standard_normal(DIM).astype("float32") * 0.01)
        _face(_photo(f"/virtual/ms_b_{i}.jpg"), bearded + _RNG.standard_normal(DIM).astype("float32") * 0.01)

    summary = update_people(eps=0.35, min_samples=2)
    assert summary.new_people == 2          # DBSCAN split the appearances...
    assert summary.merge_suggested == 1     # ...and the scan asks "Same person?"

    pairs = data.merge_suggestions()
    assert len(pairs) == 1
    assert pairs[0]["score"] >= 0.5


def test_high_similarity_unnamed_pair_is_auto_merged(clean_db) -> None:
    base = _unit()
    a = _person(base, 4, "auto_a")
    b = _person(_at_sim(base, 0.85), 3, "auto_b")  # near-certain same person

    with db.connection() as conn, conn.cursor() as cur:
        result = scan_for_merges(cur, get_settings())

    assert result.auto_merged == 1
    with db.connection() as conn, conn.cursor() as cur:
        assert db.count_persons(cur) == 1
        cur.execute("SELECT id, face_count FROM persons")
        pid, count = cur.fetchone()
        assert pid == a and count == 7      # smaller absorbed into larger
        assert not db.list_merge_suggestions_detail(cur)


def test_named_person_is_never_auto_merged(clean_db) -> None:
    base = _unit()
    a = _person(base, 4, "named_a")
    b = _person(_at_sim(base, 0.85), 3, "named_b")
    with db.connection() as conn, conn.cursor() as cur:
        db.rename_person(cur, a, "Ram")

    with db.connection() as conn, conn.cursor() as cur:
        result = scan_for_merges(cur, get_settings())

    assert result.auto_merged == 0          # a name means: always ask
    assert result.suggested == 1
    with db.connection() as conn, conn.cursor() as cur:
        assert db.count_persons(cur) == 2


def test_rejected_pair_is_never_asked_again(clean_db) -> None:
    base = _unit()
    a = _person(base, 4, "rej_a")
    b = _person(_at_sim(base, 0.85), 3, "rej_b")
    data.reject_merge_suggestion(a, b)      # user: "not the same person"

    with db.connection() as conn, conn.cursor() as cur:
        result = scan_for_merges(cur, get_settings())

    assert result.auto_merged == 0 and result.suggested == 0
    with db.connection() as conn, conn.cursor() as cur:
        assert db.count_persons(cur) == 2   # even above the auto bar


def test_low_quality_faces_cannot_found_a_person(clean_db) -> None:
    """Occluded/blurry detections may join people later, never create them."""
    center = _unit()
    for i in range(4):
        emb = center + _RNG.standard_normal(DIM).astype("float32") * 0.01
        _face(_photo(f"/virtual/ms_lq_{i}.jpg"), emb, det=0.2, side=20)  # junk

    summary = update_people(eps=0.35, min_samples=2)
    assert summary.new_people == 0
    assert summary.still_ungrouped == 4
    with db.connection() as conn, conn.cursor() as cur:
        assert db.count_persons(cur) == 0
