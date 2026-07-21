"""Duplicate grouping (pure) + DB resolution + review page (headless)."""

from __future__ import annotations

import datetime as _dt
import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from database import db
from duplicates.phash import to_signed
from duplicates.finder import find_duplicate_groups, group_hashes


def test_group_hashes_bands_and_unions() -> None:
    base = 0xA5A5A5A5A5A5A5A5
    rows = [
        (1, to_signed(base)),
        (2, to_signed(base ^ 0b11)),          # 2 bits -> same group
        (3, to_signed(base ^ (0xFFFF << 40))),  # far -> alone
        (4, to_signed(0x1234567812345678)),
        (5, to_signed(0x1234567812345678)),   # identical -> group
    ]
    groups = group_hashes(rows, max_distance=5)
    assert [1, 2] in groups and [4, 5] in groups
    assert all(3 not in g for g in groups)


def _add_photo(cur, i, phash, size=1000, path=None):
    meta = db.PhotoMetadata(
        file_path=path or f"/v/d{i}.jpg", file_hash=f"d{i}", file_size=size,
        file_mtime=_dt.datetime(2024, 1, 1))
    pid = db.insert_photo(cur, meta)
    if phash is not None:
        db.set_phashes(cur, [(pid, to_signed(phash))])
    return pid


def test_find_groups_orders_by_size_and_excludes_dismissed(clean_db) -> None:
    base = 0x0F0F0F0F0F0F0F0F
    with db.connection() as conn, conn.cursor() as cur:
        a = _add_photo(cur, 1, base, size=5000)
        b = _add_photo(cur, 2, base ^ 0b1, size=9000)   # largest
        _add_photo(cur, 3, 0x7777777777777777)          # unique

        groups = find_duplicate_groups(cur)
        assert len(groups) == 1
        ids = [p[0] for p in groups[0]["photos"]]
        assert ids[0] == b            # largest file first (the keeper)
        assert set(ids) == {a, b}

        db.record_duplicate_dismissal(cur, [a, b])
        assert find_duplicate_groups(cur) == []


def test_keep_hides_losers_but_never_deletes(clean_db) -> None:
    base = 0x33CC33CC33CC33CC
    with db.connection() as conn, conn.cursor() as cur:
        keep = _add_photo(cur, 1, base, size=8000)
        drop = _add_photo(cur, 2, base ^ 0b1, size=2000)

        db.mark_duplicates(cur, keep, [keep, drop])

        # The loser is hidden from the grid but still in the table.
        grid_ids = [r[0] for r in db.list_photo_grid(cur, limit=50)]
        assert keep in grid_ids and drop not in grid_ids
        cur.execute("SELECT count(*) FROM photos")
        assert cur.fetchone()[0] == 2                 # nothing deleted
        assert db.count_hidden_duplicates(cur) == 1

        # Resolved group is not offered again, and restore brings it back.
        assert find_duplicate_groups(cur) == []
        db.restore_duplicate(cur, drop)
        assert db.count_hidden_duplicates(cur) == 0
        assert drop in [r[0] for r in db.list_photo_grid(cur, limit=50)]


def test_duplicates_page_resolves(qapp_module, clean_db):
    from viewer.duplicates_page import DuplicatesPage, _DuplicateGroup

    base = 0x5A5A0F0F5A5A0F0F
    with db.connection() as conn, conn.cursor() as cur:
        keep = _add_photo(cur, 1, base, size=9000)
        drop = _add_photo(cur, 2, base ^ 0b11, size=1000)

    page = DuplicatesPage()
    fired = []
    page.changed.connect(lambda: fired.append(1))
    page.refresh()
    assert len(page.findChildren(_DuplicateGroup)) == 1

    card = page.findChild(_DuplicateGroup)
    card.keep_requested.emit(page._groups[0]["key"], keep)
    import time as _t
    deadline = _t.time() + 5
    while page._runner.busy() and _t.time() < deadline:
        qapp_module.processEvents()
    qapp_module.processEvents()

    assert fired
    with db.connection() as conn, conn.cursor() as cur:
        assert db.count_hidden_duplicates(cur) == 1
    assert not page._empty.isHidden()          # queue now empty
    assert "hidden as duplicates" in page._footer.text()


@pytest.fixture(scope="module")
def qapp_module():
    from viewer.app import create_application
    yield create_application([])
