"""Reset-to-zero: wipes all library tables + caches, never originals."""

from __future__ import annotations

import datetime as _dt
from pathlib import Path

from database import db


def _seed(cur):
    meta = db.PhotoMetadata(file_path="/orig/photo.jpg", file_hash="h1",
                            file_size=1, file_mtime=_dt.datetime(2024, 1, 1))
    pid = db.insert_photo(cur, meta)
    f = db.insert_face(cur, pid, (0, 0, 10, 10), [0.1] * 512, det_score=0.9)
    person = db.create_person(cur, 1, f)
    db.assign_faces_to_person(cur, person, [f])
    db.rename_person(cur, person, "Ram")
    aid = db.create_album(cur, "Trip")
    db.add_photos_to_album(cur, aid, [pid])
    db.record_duplicate_dismissal(cur, [pid])
    return pid


def test_reset_library_clears_every_table(clean_db) -> None:
    with db.connection() as conn, conn.cursor() as cur:
        _seed(cur)
        db.reset_library(cur)
        for table in db._LIBRARY_TABLES:
            cur.execute(f"SELECT count(*) FROM {table}")
            assert cur.fetchone()[0] == 0, f"{table} not cleared"


def test_reset_orchestrator_clears_caches_not_originals(clean_db, tmp_path, monkeypatch) -> None:
    import reset_library as rl
    from config.settings import get_settings

    # Point ALL generated dirs at a temp area via the data-dir override.
    monkeypatch.setenv("PHOTOSPHERE_DATA_DIR", str(tmp_path / "appdata"))
    get_settings.cache_clear()
    thumbs = get_settings().thumbnails_dir
    thumbs.mkdir(parents=True, exist_ok=True)
    (thumbs / "t1.jpg").write_bytes(b"thumb")
    original = tmp_path / "originals" / "photo.jpg"     # outside app data
    original.parent.mkdir()
    original.write_bytes(b"the irreplaceable original")

    with db.connection() as conn, conn.cursor() as cur:
        _seed(cur)

    report = rl.reset_library(clear_caches=True)

    assert report.photos_before == 1
    assert not (thumbs / "t1.jpg").exists()      # thumbnail cache wiped
    assert thumbs.exists()                        # dir recreated empty
    assert original.read_bytes() == b"the irreplaceable original"  # untouched
    with db.connection() as conn, conn.cursor() as cur:
        cur.execute("SELECT count(*) FROM photos")
        assert cur.fetchone()[0] == 0
    get_settings.cache_clear()


def test_reset_cli_requires_confirmation(clean_db, monkeypatch, capsys) -> None:
    import reset_library as rl
    with db.connection() as conn, conn.cursor() as cur:
        _seed(cur)

    monkeypatch.setattr("builtins.input", lambda _prompt="": "no")
    assert rl._main([]) == 1                       # declined -> exit 1
    with db.connection() as conn, conn.cursor() as cur:
        cur.execute("SELECT count(*) FROM photos")
        assert cur.fetchone()[0] == 1              # nothing wiped

    assert rl._main(["--yes", "--keep-thumbnails"]) == 0   # forced, DB only
    with db.connection() as conn, conn.cursor() as cur:
        cur.execute("SELECT count(*) FROM photos")
        assert cur.fetchone()[0] == 0
