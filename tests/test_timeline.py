"""Integration tests for the Timeline DB helpers.

These use the shared ``clean_db`` fixture (skipping if Postgres is unreachable)
and the ``photo_tree`` fixture, which contains exactly one dated photo
(``with_exif.jpg``, taken 2021-07-04). Timeline buckets and per-month paging are
driven off ``photos.taken_at``, so undated photos never appear.
"""

from __future__ import annotations

from pathlib import Path

from database import db
from scanner.scanner import scan_directory


def test_timeline_buckets_group_dated_photos(clean_db, photo_tree: Path) -> None:
    scan_directory(photo_tree)

    with db.connection() as conn, conn.cursor() as cur:
        buckets = db.list_timeline_buckets(cur)

    # Only with_exif.jpg carries a taken_at date (2021-07); the rest are undated.
    assert buckets == [(2021, 7, 1)]


def test_photos_by_month_returns_that_month_only(clean_db, photo_tree: Path) -> None:
    scan_directory(photo_tree)

    with db.connection() as conn, conn.cursor() as cur:
        july = db.list_photos_by_month(cur, 2021, 7, limit=50)
        august = db.list_photos_by_month(cur, 2021, 8, limit=50)

    assert len(july) == 1
    assert july[0][1].endswith("with_exif.jpg")  # file_path
    assert august == []  # a month with no photos is empty, not an error
