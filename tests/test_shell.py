"""Headless tests for the 2.0 shell components (command palette, notifications,
inspector, three-pane wiring). Qt runs offscreen; no display needed."""

from __future__ import annotations

import os

import pytest

os.environ["QT_QPA_PLATFORM"] = "offscreen"

pytest.importorskip("PySide6")


@pytest.fixture(scope="module")
def qapp():
    from viewer.app import create_application

    yield create_application([])


def test_command_palette_filters_and_runs(qapp) -> None:
    from viewer.command_palette import Command, CommandPalette

    host = __import__("PySide6").QtWidgets.QWidget()
    palette = CommandPalette(host)
    ran: list[str] = []
    palette.set_commands([
        Command("Import folder…", lambda: ran.append("import"), keywords="add photos"),
        Command("Go to People", lambda: ran.append("people")),
        Command("Go to Photos", lambda: ran.append("photos")),
    ])
    palette._refilter("")
    assert palette._list.count() == 3

    palette._refilter("peop")            # fuzzy subsequence
    assert palette._list.count() == 1
    palette._run_current()
    assert ran == ["people"]

    palette._refilter("addph")           # matches keywords, not just title
    assert palette._list.count() == 1


def test_notification_center_badge_and_history(qapp) -> None:
    from viewer.notifications import NotificationCenter

    host = __import__("PySide6").QtWidgets.QWidget()
    nc = NotificationCenter(host)
    counts: list[int] = []
    nc.changed.connect(counts.append)

    nc.notify("Import finished", "1,204 photos added")
    nc.notify("Duplicates found", "3 possible")
    assert nc._unread == 2
    # isVisible() is False while the host isn't shown; isHidden() reflects intent.
    assert not nc._badge.isHidden() and nc._badge.text() == "2"

    nc._toggle_panel()                   # opening clears unread
    assert nc._unread == 0
    assert counts[-1] == 0
    assert nc._badge.isHidden()          # badge cleared
    assert len(nc._items) == 2           # history retained


def test_inspector_shows_and_clears(qapp) -> None:
    from viewer.inspector import Inspector

    insp = Inspector()
    insp.show_sections([("LIBRARY", "10 photos"), ("TIP", "hello")])
    labels = [w.text() for w in insp.findChildren(__import__("PySide6").QtWidgets.QLabel)]
    assert "LIBRARY" in labels and any("10 photos" in t for t in labels)
    assert insp._empty.isHidden()        # idle state hidden while content shows

    insp.clear()
    assert not insp._empty.isHidden()    # idle state restored


def test_dashboard_activity_center(qapp, clean_db) -> None:
    from viewer.pages import DashboardPage

    page = DashboardPage()
    nav: list[str] = []
    page.navigate.connect(nav.append)
    page.refresh()  # empty library

    # Greeting is time-of-day; summary and empty state present.
    assert page._greeting.text() in ("Good morning", "Good afternoon", "Good evening")
    assert "0 photos" in page._summary.text()
    assert not page._empty.isHidden()             # empty-library prompt
    assert page._review_title.text() == "All caught up"
    assert page._recent.isHidden()                # no strips with no photos

    # The review card routes to the Review center.
    page._review_card.clicked.emit()
    assert nav == ["review"]


def test_gallery_tile_delegate_and_roles(qapp, clean_db, photo_tree) -> None:
    from scanner.scanner import scan_directory
    from thumbnails.generator import generate_thumbnails
    from viewer.gallery import DATE_ROLE, NAME_ROLE, PhotoGrid, PhotoGridModel, PhotoTileDelegate
    from viewer import data

    scan_directory(photo_tree)
    generate_thumbnails()

    model = PhotoGridModel()
    model.set_fetcher(lambda offset, limit: data.photo_grid(limit=limit, offset=offset))
    grid = PhotoGrid(model)
    assert isinstance(grid.itemDelegate(), PhotoTileDelegate)
    assert model.rowCount() == 5

    idx = model.index(0)
    assert model.data(idx, NAME_ROLE)                     # filename exposed
    assert isinstance(model.data(idx, DATE_ROLE), str)    # date string (may be "")

    # Hover row is tracked for the delegate to highlight.
    grid._delegate.set_hover_row(2)
    assert grid._delegate._hover_row == 2


def test_person_profile_header(qapp, clean_db) -> None:
    import datetime as _dt
    import numpy as np
    from clustering.clusterer import normalize_embeddings
    from database import db
    from viewer.pages import PersonDetailPage

    def _emb():
        v = normalize_embeddings(np.random.default_rng().standard_normal((1, 512)).astype("float32"))
        return v[0].tolist()

    with db.connection() as conn, conn.cursor() as cur:
        ram = db.create_person(cur, 0, None)
        hari = db.create_person(cur, 0, None)
        db.rename_person(cur, ram, "Ram")
        db.rename_person(cur, hari, "Hari")
        for i in range(4):
            meta = db.PhotoMetadata(
                file_path=f"/v/pp{i}.jpg", file_hash=f"h{i}", file_size=1,
                file_mtime=_dt.datetime(2020, 1, 1),
                taken_at=_dt.datetime(2020, 1, 1) + _dt.timedelta(days=i * 30),
            )
            pid = db.insert_photo(cur, meta)
            db.assign_faces_to_person(cur, ram,
                [db.insert_face(cur, pid, (0, 0, 40, 40), _emb(), det_score=0.9)])
            db.assign_faces_to_person(cur, hari,
                [db.insert_face(cur, pid, (40, 0, 40, 40), _emb(), det_score=0.9)])

    page = PersonDetailPage()
    page.show_person(ram, "Ram")
    assert page._name.text() == "Ram"
    assert "4 photos" in page._subtitle.text()
    assert "First seen" in page._subtitle.text()
    # "Appears with" shows Hari (shares every photo).
    assert page._aw_container.count() == 1


def test_timeline_rail_and_hero(qapp, clean_db, photo_tree) -> None:
    from scanner.scanner import scan_directory
    from viewer.timeline_page import TimelinePage, _MonthRow

    scan_directory(photo_tree)  # one dated photo: with_exif.jpg, 2021-07

    page = TimelinePage()
    page.refresh()

    # The rail carries exactly one month row (July 2021) and it's auto-selected.
    rows = page.findChildren(_MonthRow)
    assert len(rows) == 1
    assert page._selected == (2021, 7)
    assert rows[0].property("selected") == "true"

    # Hero header and count reflect the selected month.
    assert page._hero.text() == "July 2021"
    assert page._subtitle.text() == "1 photo"          # singular
    assert page._empty.isHidden()      # empty prompt hidden when photos exist
    assert not page._grid.isHidden()   # grid shown

    # Re-selecting the same month is a no-op (no animation restart).
    page._show_month(2021, 7)
    assert page._selected == (2021, 7)


def test_timeline_empty_state(qapp, clean_db) -> None:
    from viewer.timeline_page import TimelinePage, _MonthRow

    page = TimelinePage()
    page.refresh()  # empty library
    assert page.findChildren(_MonthRow) == []
    assert page._hero.text() == "Timeline"
    assert not page._empty.isHidden()   # empty prompt shown
    assert page._grid.isHidden()        # grid hidden with nothing to show


def test_search_idle_suggestions_and_why_chips(qapp) -> None:
    from types import SimpleNamespace

    from viewer.search_page import _SUGGESTIONS, SearchPage

    page = SearchPage()

    # Idle: suggestion chips shown, grid hidden, no evidence chips.
    assert page._suggest.isVisibleTo(page)
    assert page._grid.isHidden()
    chips = [b for b in page.findChildren(__import__("PySide6").QtWidgets.QPushButton)
             if b.objectName() == "SearchSuggest"]
    assert len(chips) == len(_SUGGESTIONS)
    assert page._input.placeholderText() == "Search your memories…"

    # "Why matched" aggregation from a result set.
    res = [
        SimpleNamespace(matched_person="Ram", similarity=0.4, matched_text=False),
        SimpleNamespace(matched_person=None, similarity=0.2, matched_text=True),
    ]
    assert page._why_chips(res) == ["☺ Ram", "Visual match", "Text in photo"]
    assert page._why_chips([SimpleNamespace(matched_person=None, similarity=0.0,
                                            matched_text=False)]) == []

    # show_rows (Find Similar path) swaps to the results state and clears why.
    page._add_why("stale")
    page.show_rows([(1, "/a.jpg", None, None)], "3 similar photos")
    assert not page._suggest.isVisibleTo(page)
    assert not page._grid.isHidden()
    assert page._why.count() == 0                    # evidence cleared
    assert page._status.text() == "3 similar photos"

    # Clearing the box and submitting returns to the idle suggestions.
    page._input.clear()
    page._run()
    assert page._suggest.isVisibleTo(page)


def test_review_center_lists_and_resolves(qapp, clean_db) -> None:
    import datetime as _dt
    import numpy as np
    from clustering.clusterer import normalize_embeddings
    from database import db
    from viewer.review_page import ReviewPage, _FaceRow, _MergeRow

    def _emb():
        v = normalize_embeddings(np.random.default_rng().standard_normal((1, 512)).astype("float32"))
        return v[0].tolist()

    with db.connection() as conn, conn.cursor() as cur:
        meta = db.PhotoMetadata(file_path="/v/r.jpg", file_hash="hr", file_size=1,
                                file_mtime=_dt.datetime(2020, 1, 1))
        pid = db.insert_photo(cur, meta)
        named_face = db.insert_face(cur, pid, (0, 0, 40, 40), _emb(),
                                    det_score=0.9, crop_path="/v/named.jpg")
        person = db.create_person(cur, 1, named_face)
        db.assign_faces_to_person(cur, person, [named_face])
        db.rename_person(cur, person, "Ram")
        # A second (unnamed) profile to suggest merging into Ram.
        other_face = db.insert_face(cur, pid, (60, 0, 40, 40), _emb(),
                                    det_score=0.9, crop_path="/v/other.jpg")
        other = db.create_person(cur, 1, other_face)
        db.assign_faces_to_person(cur, other, [other_face])
        db.replace_merge_suggestions(cur, [(person, other, 0.61)])
        # An ungrouped face suggested as Ram.
        loose = db.insert_face(cur, pid, (0, 60, 40, 40), _emb(),
                               det_score=0.9, crop_path="/v/loose.jpg")
        db.record_suggestion(cur, loose, person, 0.55)

    page = ReviewPage()
    signals: list[int] = []
    page.changed.connect(lambda: signals.append(1))
    page.refresh()

    assert len(page.findChildren(_MergeRow)) == 1
    assert len(page.findChildren(_FaceRow)) == 1
    assert "2 questions waiting" in page._subtitle.text()
    assert not page._empty.isVisible() or not page._empty.isVisibleTo(page)

    # Accept the face suggestion; the runner works off-thread, so pump until done.
    face_row = page.findChild(_FaceRow)
    face_row.confirmed.emit(loose, person)  # simulate the Yes button
    deadline = __import__("time").time() + 5
    while page._runner.busy() and __import__("time").time() < deadline:
        qapp.processEvents()
    qapp.processEvents()

    assert signals                              # changed fired
    with db.connection() as conn, conn.cursor() as cur:
        assert db.count_suggestions(cur) == 0   # the suggestion was consumed


def test_review_center_empty_state(qapp, clean_db) -> None:
    from viewer.review_page import ReviewPage, _FaceRow, _MergeRow

    page = ReviewPage()
    page.refresh()
    assert page.findChildren(_MergeRow) == [] and page.findChildren(_FaceRow) == []
    assert not page._empty.isHidden()
    assert page._scroll.isHidden()


def test_main_window_has_three_pane_shell(qapp, clean_db) -> None:
    from viewer.main_window import MainWindow

    win = MainWindow()
    try:
        assert win._inspector is not None
        assert win._palette is not None
        # The bell was added to the top bar (reparented there by add_trailing).
        assert win._notify.bell.parent() is win._topbar
        # Palette command set covers navigation + the key actions.
        titles = [c.title for c in win._build_commands()]
        assert any("Import" in t for t in titles)
        assert any("People" in t for t in titles)
        # Inspector fills with context on navigation (does not raise).
        win.show_page("people")
        win.show_page("dashboard")
    finally:
        win.close()
