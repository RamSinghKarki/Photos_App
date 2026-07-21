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

    # The review card routes to People.
    page._review_card.clicked.emit()
    assert nav == ["people"]


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
