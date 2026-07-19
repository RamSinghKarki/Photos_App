"""Read-only data access for the Viewer.

The UI never writes SQL: it calls these small functions, which delegate to the
named helpers in :mod:`database.db` over short-lived connections and return
plain Python values. Keeping all database access here means the widgets stay
free of connection handling.
"""

from __future__ import annotations

from typing import Any, Optional

from database import db
from utils.perf import timer


def library_stats() -> dict[str, int]:
    """Headline counts for the dashboard / status bar."""
    with timer("query.library_stats"), db.connection() as conn, conn.cursor() as cur:
        return db.library_stats(cur)


def photo_grid(
    limit: int,
    offset: int = 0,
    person_id: Optional[int] = None,
    search: Optional[str] = None,
) -> list[tuple[int, str, Optional[str], Any]]:
    """A page of (id, file_path, thumbnail_path, taken_at) rows for the gallery."""
    with timer("query.photo_grid"), db.connection() as conn, conn.cursor() as cur:
        return db.list_photo_grid(cur, limit, offset, person_id, search)


def photo_detail(photo_id: int) -> Optional[dict[str, Any]]:
    """Full metadata for one photo, or None."""
    with timer("query.photo_detail"), db.connection() as conn, conn.cursor() as cur:
        return db.get_photo_detail(cur, photo_id)


def persons() -> list[dict[str, Any]]:
    """People with cover-face crop paths, largest first."""
    with timer("query.persons"), db.connection() as conn, conn.cursor() as cur:
        return db.list_persons_with_cover(cur)


def recent_runs(limit: int = 5) -> list[dict[str, Any]]:
    """Recent scan runs for the dashboard activity feed."""
    with timer("query.recent_runs"), db.connection() as conn, conn.cursor() as cur:
        return db.recent_scan_runs(cur, limit)


# -- writes (people editing) ------------------------------------------------
def rename_person(person_id: int, name: Optional[str]) -> None:
    """Set or clear a person's display name."""
    with db.connection() as conn, conn.cursor() as cur:
        db.rename_person(cur, person_id, name)


def delete_person(person_id: int) -> None:
    """Delete a person group (its faces are un-grouped, not deleted)."""
    with db.connection() as conn, conn.cursor() as cur:
        db.delete_person(cur, person_id)


def merge_person_into(source_id: int, target_id: int) -> None:
    """Merge one person into another (faces move to the target)."""
    with db.connection() as conn, conn.cursor() as cur:
        db.merge_persons(cur, source_id, target_id)
