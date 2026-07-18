"""Integration tests for the scanner against a real PostgreSQL database.

These tests require a reachable PostgreSQL server with the pgvector extension
available. They target a dedicated database (``photosphere_test`` by default,
overridable via ``PHOTOSPHERE_DB_NAME``) and truncate its tables between runs,
so they never touch production data. If the database cannot be reached the
tests skip rather than fail, keeping the pure-unit suite runnable anywhere.
"""

from __future__ import annotations

from pathlib import Path

from database import db
from scanner.scanner import scan_directory


def test_scan_counts_and_dedup(clean_db, photo_tree: Path) -> None:
    summary = scan_directory(photo_tree)

    # Five image files; notes.txt is ignored. a_copy.jpg duplicates a.jpg.
    assert summary.processed == 5
    assert summary.duplicates == 1
    assert summary.skipped == 0
    assert summary.errors == 0  # a corrupt image is kept, not an error

    with db.connection() as conn, conn.cursor() as cur:
        assert db.count_photos(cur) == 5
        cur.execute("SELECT count(DISTINCT file_hash) FROM photos")
        assert cur.fetchone()[0] == 4  # two paths share one hash


def test_rescan_is_idempotent(clean_db, photo_tree: Path) -> None:
    scan_directory(photo_tree)
    second = scan_directory(photo_tree)

    assert second.processed == 0
    assert second.skipped == 5

    with db.connection() as conn, conn.cursor() as cur:
        assert db.count_photos(cur) == 5  # no rows added on the second pass


def test_exif_persisted(clean_db, photo_tree: Path) -> None:
    scan_directory(photo_tree)
    with db.connection() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT camera_model, gps_latitude FROM photos WHERE camera_model IS NOT NULL"
        )
        row = cur.fetchone()
    assert row is not None
    assert row[0] == "TestModel"
    assert abs(row[1] - 37.775) < 1e-4
