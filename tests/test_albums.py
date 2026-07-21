"""Albums: DB CRUD + membership (integration) and the page (headless)."""

from __future__ import annotations

import datetime as _dt
import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from database import db


def _photos(cur, n):
    ids = []
    for i in range(n):
        meta = db.PhotoMetadata(
            file_path=f"/v/al{i}.jpg", file_hash=f"al{i}", file_size=100,
            file_mtime=_dt.datetime(2024, 1, 1))
        ids.append(db.insert_photo(cur, meta))
    return ids


def test_album_crud_and_membership(clean_db) -> None:
    with db.connection() as conn, conn.cursor() as cur:
        p = _photos(cur, 3)
        aid = db.create_album(cur, "Trip")

        assert db.add_photos_to_album(cur, aid, p[:2]) == 2
        assert db.add_photos_to_album(cur, aid, p[:2]) == 0   # idempotent

        albums = db.list_albums(cur)
        assert len(albums) == 1
        assert albums[0]["name"] == "Trip" and albums[0]["count"] == 2

        # First-added photo became the cover.
        cur.execute("SELECT cover_photo_id FROM albums WHERE id = %s", (aid,))
        assert cur.fetchone()[0] == p[0]

        photos = db.list_album_photos(cur, aid, limit=50)
        assert {r[0] for r in photos} == set(p[:2])

        db.remove_photos_from_album(cur, aid, [p[0]])
        assert db.list_albums(cur)[0]["count"] == 1

        db.rename_album(cur, aid, "Summer")
        assert db.list_albums(cur)[0]["name"] == "Summer"


def test_deleting_album_keeps_photos(clean_db) -> None:
    with db.connection() as conn, conn.cursor() as cur:
        p = _photos(cur, 2)
        aid = db.create_album(cur, "Temp")
        db.add_photos_to_album(cur, aid, p)
        db.delete_album(cur, aid)
        assert db.count_albums(cur) == 0
        cur.execute("SELECT count(*) FROM photos")
        assert cur.fetchone()[0] == 2                 # photos untouched
        cur.execute("SELECT count(*) FROM album_photos")
        assert cur.fetchone()[0] == 0                 # membership cascaded


def test_albums_page_list_and_open(qapp_module, clean_db):
    from viewer.albums_page import AlbumsPage, _AlbumCard

    with db.connection() as conn, conn.cursor() as cur:
        p = _photos(cur, 2)
        aid = db.create_album(cur, "Beach")
        db.add_photos_to_album(cur, aid, p)

    page = AlbumsPage()
    page.refresh()
    cards = page.findChildren(_AlbumCard)
    assert len(cards) == 1

    page._open_album(aid, "Beach")
    assert page._stack.currentIndex() == 1
    assert page._detail_title.text() == "Beach"
    assert set(page.current_photo_ids()) == set(p)

    # Removing from the album leaves the photos in the library.
    page._on_remove_photos([p[0]])
    with db.connection() as conn, conn.cursor() as cur:
        assert db.list_albums(cur)[0]["count"] == 1
        cur.execute("SELECT count(*) FROM photos")
        assert cur.fetchone()[0] == 2


@pytest.fixture(scope="module")
def qapp_module():
    from viewer.app import create_application
    yield create_application([])
