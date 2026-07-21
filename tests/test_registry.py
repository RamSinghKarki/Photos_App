"""Unit tests for the page registry — navigation's single source of truth."""

from __future__ import annotations

from viewer.registry import PAGES, implemented_keys, planned_notes, sidebar_sections


def test_keys_are_unique_and_stable() -> None:
    keys = [p.key for p in PAGES]
    assert len(keys) == len(set(keys))
    # State restore depends on these exact keys existing.
    for expected in ("dashboard", "photos", "timeline", "people", "search"):
        assert expected in keys


def test_implemented_and_planned_partition_the_pages() -> None:
    built = implemented_keys()
    notes = planned_notes()
    assert built.isdisjoint(notes)                       # never both
    assert built | set(notes) == {p.key for p in PAGES}  # never neither


def test_sidebar_derives_every_page_in_order() -> None:
    flat = [(label, key) for _sec, entries in sidebar_sections() for label, key in entries]
    assert flat == [(p.label, p.key) for p in PAGES]     # order preserved
    sections = [s for s, _ in sidebar_sections()]
    assert sections == ["Library", "AI", "Organization", "System"]


def test_theme_and_main_window_consume_the_registry() -> None:
    from viewer import theme

    assert theme.SIDEBAR_SECTIONS == sidebar_sections()
    assert theme.IMPLEMENTED_PAGES == implemented_keys()
