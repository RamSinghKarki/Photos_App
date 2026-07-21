"""Tests for thumbnail generation and the UI read helpers."""

from __future__ import annotations

from pathlib import Path

from PIL import Image

from config.settings import get_settings
from database import db
from scanner.scanner import scan_directory
from thumbnails.generator import generate_thumbnails

READABLE = 4  # openable images in the fixture tree (broken.jpg excluded)


def test_thumbnails_generated_and_recorded(clean_db, photo_tree: Path) -> None:
    scan_directory(photo_tree)
    summary = generate_thumbnails()

    assert summary.generated == READABLE
    assert summary.unreadable == 1  # broken.jpg
    assert summary.errors == 0

    size = get_settings().thumbnail_size
    with db.connection() as conn, conn.cursor() as cur:
        cur.execute("SELECT thumbnail_path FROM photos WHERE thumbnail_path IS NOT NULL")
        paths = [r[0] for r in cur.fetchall()]

    assert len(paths) == READABLE
    for path in paths:
        assert Path(path).exists()
        with Image.open(path) as thumb:
            # Longest edge is capped at the configured size; aspect preserved.
            assert max(thumb.size) <= size


def test_thumbnails_are_idempotent(clean_db, photo_tree: Path) -> None:
    scan_directory(photo_tree)
    generate_thumbnails()
    second = generate_thumbnails()  # nothing left without a thumbnail
    assert second.generated == 0


def test_regenerate_rebuilds_all(clean_db, photo_tree: Path) -> None:
    scan_directory(photo_tree)
    generate_thumbnails()
    again = generate_thumbnails(regenerate=True)
    assert again.generated == READABLE


def test_library_stats_and_grid(clean_db, photo_tree: Path) -> None:
    scan_directory(photo_tree)
    generate_thumbnails()

    with db.connection() as conn, conn.cursor() as cur:
        stats = db.library_stats(cur)
        assert stats["photos"] == 5           # includes broken.jpg (identity only)
        assert stats["storage_bytes"] > 0

        grid = db.list_photo_grid(cur, limit=100)
        assert len(grid) == 5
        # Each row is (id, file_path, thumbnail_path, taken_at).
        assert all(len(row) == 4 for row in grid)

        # Basic text search matches on file path.
        hits = db.list_photo_grid(cur, limit=100, search="with_exif")
        assert len(hits) == 1

        detail = db.get_photo_detail(cur, grid[0][0])
        assert detail is not None and "file_path" in detail
