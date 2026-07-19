"""Tests for Module 3 (clustering).

Pure-function tests exercise the DBSCAN wrapper directly; integration tests
seed the database with synthetic embeddings that form clearly separated groups
(plus outliers) and verify the persisted person grouping.
"""

from __future__ import annotations

import datetime as _dt

import numpy as np

from clustering.clusterer import (
    NOISE_LABEL,
    cluster_faces,
    normalize_embeddings,
    resolve_algorithm,
    _hdbscan_available,
)
from clustering.processor import recluster
from database import db

DIM = 512


def _synthetic_faces(seed: int = 0):
    """Return (embeddings, expected_group) for 3 tight clusters + 2 outliers.

    ``expected_group`` maps each row index to a group key (or None for the
    outliers) so tests can assert same-group faces end up together.
    """
    rng = np.random.default_rng(seed)
    centers = normalize_embeddings(rng.standard_normal((3, DIM)).astype(np.float32))

    rows: list[np.ndarray] = []
    groups: list[object] = []
    for c, center in enumerate(centers):
        for _ in range(4):  # 4 faces per person
            noise = rng.standard_normal(DIM).astype(np.float32) * 0.01
            rows.append(center + noise)
            groups.append(c)
    # Two lone outliers, each far from everything -> DBSCAN noise.
    for _ in range(2):
        rows.append(normalize_embeddings(rng.standard_normal((1, DIM)).astype(np.float32))[0])
        groups.append(None)

    return np.asarray(rows, dtype=np.float32), groups


# --------------------------------------------------------------------------- #
# Pure function
# --------------------------------------------------------------------------- #
def test_normalize_is_unit_length() -> None:
    vecs = np.array([[3.0, 4.0], [0.0, 0.0]], dtype=np.float32)
    out = normalize_embeddings(vecs)
    assert abs(np.linalg.norm(out[0]) - 1.0) < 1e-6
    assert np.allclose(out[1], 0.0)  # zero vector stays zero, no divide error


def test_cluster_finds_three_groups() -> None:
    embeddings, _ = _synthetic_faces()
    labels = cluster_faces(embeddings, eps=0.35, min_samples=2)
    clusters = {label for label in labels if label != NOISE_LABEL}
    assert len(clusters) == 3
    assert list(labels).count(NOISE_LABEL) == 2  # the two outliers


def test_cluster_empty_input() -> None:
    labels = cluster_faces(np.empty((0, DIM), dtype=np.float32), eps=0.35, min_samples=2)
    assert labels.shape == (0,)


def test_resolve_algorithm() -> None:
    # Explicit choices are honoured; "auto" depends on what's installed.
    assert resolve_algorithm("dbscan") == "dbscan"
    assert resolve_algorithm("hdbscan") == "hdbscan"
    expected_auto = "hdbscan" if _hdbscan_available() else "dbscan"
    assert resolve_algorithm("auto") == expected_auto
    assert resolve_algorithm("") == expected_auto  # empty falls through to auto


def test_cluster_auto_falls_back_to_dbscan_when_needed() -> None:
    # "auto" must always produce a valid result — HDBSCAN if present, else DBSCAN.
    embeddings, _ = _synthetic_faces()
    labels = cluster_faces(embeddings, eps=0.35, min_samples=2, algorithm="auto")
    clusters = {label for label in labels if label != NOISE_LABEL}
    assert len(clusters) == 3


# --------------------------------------------------------------------------- #
# Integration
# --------------------------------------------------------------------------- #
def _seed_faces(embeddings: np.ndarray) -> list[int]:
    """Insert one photo and a face per embedding; return the face ids."""
    meta = db.PhotoMetadata(
        file_path="/virtual/cluster_test.jpg",
        file_hash="0" * 64,
        file_size=1,
        file_mtime=_dt.datetime(2021, 1, 1),
    )
    face_ids: list[int] = []
    with db.connection() as conn, conn.cursor() as cur:
        photo_id = db.insert_photo(cur, meta)
        assert photo_id is not None
        for i, emb in enumerate(embeddings):
            fid = db.insert_face(
                cur, photo_id, (0, 0, 10, 10), emb.tolist(), det_score=0.5 + 0.01 * i
            )
            face_ids.append(fid)
    return face_ids


def test_recluster_groups_and_persists(clean_db) -> None:
    embeddings, groups = _synthetic_faces()
    face_ids = _seed_faces(embeddings)

    summary = recluster(eps=0.35, min_samples=2)

    assert summary.total_faces == 14
    assert summary.persons == 3
    assert summary.grouped == 12
    assert summary.ungrouped == 2

    with db.connection() as conn, conn.cursor() as cur:
        assert db.count_persons(cur) == 3

        # Faces sharing a synthetic group must share one person_id; different
        # groups must differ; outliers must stay ungrouped (NULL).
        cur.execute("SELECT id, person_id FROM faces ORDER BY id")
        person_by_face = {fid: pid for fid, pid in cur.fetchall()}

        group_to_person: dict[object, int] = {}
        for idx, fid in enumerate(face_ids):
            expected = groups[idx]
            pid = person_by_face[fid]
            if expected is None:
                assert pid is None  # outlier left ungrouped
            else:
                assert pid is not None
                group_to_person.setdefault(expected, pid)
                assert group_to_person[expected] == pid
        assert len(set(group_to_person.values())) == 3

        # face_count and cover_face_id are populated correctly.
        cur.execute("SELECT face_count, cover_face_id FROM persons ORDER BY id")
        for face_count, cover in cur.fetchall():
            assert face_count == 4
            assert cover is not None


def test_recluster_is_repeatable(clean_db) -> None:
    embeddings, _ = _synthetic_faces()
    _seed_faces(embeddings)

    first = recluster(eps=0.35, min_samples=2)
    second = recluster(eps=0.35, min_samples=2)

    # Re-running rebuilds the same grouping; no duplicate persons accumulate.
    assert first.persons == second.persons == 3
    with db.connection() as conn, conn.cursor() as cur:
        assert db.count_persons(cur) == 3


def test_recluster_with_no_faces(clean_db) -> None:
    summary = recluster(eps=0.35, min_samples=2)
    assert summary.total_faces == 0
    assert summary.persons == 0
