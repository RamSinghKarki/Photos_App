"""The page registry — the single source of truth for navigation (PDD Phase 1).

Adding a page used to touch four places (sidebar sections, the main window's
stack loop, the implemented-pages set, and the planned-notes dict) — and missing
one silently showed a "planned" page for a built feature (audit item A2). Now
every consumer derives from :data:`PAGES`:

* ``viewer/theme.py`` derives the sidebar sections and implemented set,
* ``viewer/main_window.py`` derives the planned-notes dict,

so a new page is exactly one :class:`PageSpec` entry (plus its widget wiring).
Keys marked ``planned`` render the honest "coming soon" page; reserved future
sections (Videos, Documents, Maps, …) live here too, per the PDD's
future-reservation rule.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class PageSpec:
    """One navigable page: identity, placement, and build status."""

    key: str                 # stable id used by show_page()/state restore
    label: str               # sidebar text
    section: str             # sidebar group heading
    planned: Optional[str] = None  # note => "coming soon" page; None => built


PAGES: tuple[PageSpec, ...] = (
    # Library
    PageSpec("dashboard", "Dashboard", "Library"),
    PageSpec("photos", "Photos", "Library"),
    PageSpec("timeline", "Timeline", "Library"),
    PageSpec("videos", "Videos", "Library",
             planned="Videos — planned. Video indexing is a future module."),
    # AI
    PageSpec("people", "People", "AI"),
    PageSpec("search", "Search", "AI"),
    PageSpec("objects", "Objects", "AI",
             planned="Object Detection — planned AI module."),
    PageSpec("similar", "Similar Photos", "AI",
             planned="Similar Photos — planned AI module."),
    # Organization
    PageSpec("albums", "Albums", "Organization",
             planned="Albums — planned organization module."),
    PageSpec("favorites", "Favorites", "Organization",
             planned="Favorites — planned organization module."),
    PageSpec("archive", "Archive", "Organization",
             planned="Archive — planned organization module."),
    PageSpec("trash", "Trash", "Organization",
             planned="Trash — planned. Deletions will be database-only; "
                     "originals are never touched."),
    # System
    PageSpec("settings", "Settings", "System",
             planned="Settings — planned configuration module."),
    PageSpec("about", "About", "System",
             planned="PhotoSphere AI — a fully offline, local AI photo manager."),
)


def sidebar_sections() -> list[tuple[str, list[tuple[str, str]]]]:
    """Sidebar groups as (section, [(label, key), …]) in declaration order."""
    sections: list[tuple[str, list[tuple[str, str]]]] = []
    for page in PAGES:
        if not sections or sections[-1][0] != page.section:
            sections.append((page.section, []))
        sections[-1][1].append((page.label, page.key))
    return sections


def implemented_keys() -> set[str]:
    """Keys whose pages are fully built (everything else shows 'planned')."""
    return {page.key for page in PAGES if page.planned is None}


def planned_notes() -> dict[str, str]:
    """key -> honest note for pages whose backend module is not built yet."""
    return {page.key: page.planned for page in PAGES if page.planned is not None}
