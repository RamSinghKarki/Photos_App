"""Round-trip tests for knowledge backup/restore (backup.knowledge)."""

from __future__ import annotations

import datetime as _dt
from pathlib import Path

import numpy as np
import pytest

from backup.knowledge import (
    load_backup,
    restore_knowledge,
    save_backup,
    validate_backup,
)
from clustering.clusterer import normalize_embeddings
from database import db


def _emb():
    v = normalize_embeddings(
        np.random.default_rng().standard_normal((1, 512)).astype("float32"))
    return v[0].tolist()


def _seed(cur):
    """Two photos; Ram named with two faces; one favorite; one rejection."""
    pids = []
    for i in range(2):
        meta = db.PhotoMetadata(
            file_path=f"/v/bk{i}.jpg", file_hash=f"bk{i}", file_size=1,
            file_mtime=_dt.datetime(2024, 1, 1))
        pids.append(db.insert_photo(cur, meta))
    f1 = db.insert_face(cur, pids[0], (0, 0, 40, 40), _emb(), det_score=0.9)
    f2 = db.insert_face(cur, pids[1], (10, 10, 40, 40), _emb(), det_score=0.9)
    ram = db.create_person(cur, 2, f1)
    db.assign_faces_to_person(cur, ram, [f1, f2])
    db.rename_person(cur, ram, "Ram")
    stray = db.insert_face(cur, pids[1], (60, 0, 30, 30), _emb(), det_score=0.9)
    db.record_feedback(cur, stray, ram, "reject")
    cur.execute("UPDATE photos SET is_favorite = TRUE WHERE id = %s", (pids[0],))
    return ram


def test_backup_round_trip_restores_knowledge(clean_db, tmp_path: Path) -> None:
    with db.connection() as conn, conn.cursor() as cur:
        _seed(cur)
        data = save_backup(cur, tmp_path / "k.json")

    assert validate_backup(data) == []
    assert (tmp_path / "k.json").exists()

    # Simulate losing the knowledge layer: people gone, favorites cleared.
    with db.connection() as conn, conn.cursor() as cur:
        cur.execute("DELETE FROM recognition_feedback")
        db.clear_persons(cur)
        cur.execute("UPDATE photos SET is_favorite = FALSE")

    loaded = load_backup(tmp_path / "k.json")
    with db.connection() as conn, conn.cursor() as cur:
        report = restore_knowledge(cur, loaded)

    assert report["people"] == 1 and report["faces_assigned"] == 2
    assert report["favorites"] == 1 and report["feedback"] == 1
    with db.connection() as conn, conn.cursor() as cur:
        cur.execute("SELECT display_name FROM persons WHERE display_name IS NOT NULL")
        assert [r[0] for r in cur.fetchall()] == ["Ram"]
        cur.execute("SELECT count(*) FROM faces WHERE person_id IS NOT NULL")
        assert cur.fetchone()[0] == 2
        cur.execute("SELECT count(*) FROM photos WHERE is_favorite")
        assert cur.fetchone()[0] == 1
        cur.execute("SELECT verdict FROM recognition_feedback")
        assert [r[0] for r in cur.fetchall()] == ["reject"]


def test_restore_is_additive_and_idempotent(clean_db, tmp_path: Path) -> None:
    with db.connection() as conn, conn.cursor() as cur:
        _seed(cur)
        data = save_backup(cur, tmp_path / "k.json")

    # Restoring over an intact library must not duplicate or destroy anything.
    with db.connection() as conn, conn.cursor() as cur:
        restore_knowledge(cur, data)
        restore_knowledge(cur, data)
        cur.execute("SELECT count(*) FROM persons WHERE display_name = 'Ram'")
        assert cur.fetchone()[0] == 1
        cur.execute("SELECT count(*) FROM faces WHERE person_id IS NOT NULL")
        assert cur.fetchone()[0] == 2


def test_restore_refuses_invalid_and_skips_unmatched(clean_db) -> None:
    with db.connection() as conn, conn.cursor() as cur:
        with pytest.raises(ValueError):
            restore_knowledge(cur, {"format": 99})
        # Valid structure, but nothing matches this library: all skipped.
        ghost = {"format": 1, "favorites": ["nope"], "feedback": [],
                 "people": [{"name": "Ghost", "faces": [["nope", 0, 0, 1, 1]]}]}
        report = restore_knowledge(cur, ghost)
        assert report["people"] == 0 and report["faces_skipped"] == 1
        assert report["favorites_skipped"] == 1
