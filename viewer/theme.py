"""Dark-first visual theme for the PhotoSphere AI desktop UI.

A single source of truth for colours, radii, and the application stylesheet, so
every widget looks like one native app rather than a web page. The palette
follows the design brief: near-black background, dark-gray surfaces, a blue
primary, a green "active" accent, amber warnings and red errors, with 8–12 px
rounded corners.
"""

from __future__ import annotations

# --- Palette ---------------------------------------------------------------
BACKGROUND = "#0f1115"     # near-black app background
SURFACE = "#181b21"        # cards, panels
SURFACE_ALT = "#212530"    # hover / elevated surfaces
BORDER = "#2a2f3a"
PRIMARY = "#4a9eff"        # blue — selection, links, focus
ACCENT = "#3ecf8e"         # green — active indexing / success
WARNING = "#f5a623"        # amber
ERROR = "#ff5c5c"          # red
TEXT = "#e6e8eb"           # primary text
TEXT_MUTED = "#9aa0a8"     # secondary/metadata text

RADIUS = 10                # default corner radius (px)

# Sidebar sections -> (label, page-key, glyph). Glyphs are plain unicode so no
# icon assets are required for a first version.
SIDEBAR_SECTIONS: list[tuple[str, list[tuple[str, str, str]]]] = [
    ("Library", [
        ("Dashboard", "dashboard", "▦"),
        ("Photos", "photos", "▨"),
        ("Timeline", "timeline", "🕒"),
        ("Videos", "videos", "▷"),
    ]),
    ("AI", [
        ("People", "people", "☺"),
        ("Search", "search", "⌕"),
        ("Objects", "objects", "◈"),
        ("Similar Photos", "similar", "❏"),
    ]),
    ("Organization", [
        ("Albums", "albums", "▤"),
        ("Favorites", "favorites", "★"),
        ("Archive", "archive", "▢"),
        ("Trash", "trash", "🗑"),
    ]),
    ("System", [
        ("Settings", "settings", "⚙"),
        ("About", "about", "ⓘ"),
    ]),
]

# Page keys that are fully implemented in this module; everything else renders
# an honest "planned" page tied to a future backend module.
IMPLEMENTED_PAGES = {"dashboard", "photos", "people"}


def build_stylesheet() -> str:
    """Return the global Qt stylesheet (QSS) for the application."""
    return f"""
    QWidget {{
        background-color: {BACKGROUND};
        color: {TEXT};
        font-family: "Segoe UI", "DejaVu Sans", sans-serif;
        font-size: 14px;
    }}
    QLabel#H1 {{ font-size: 26px; font-weight: 600; }}
    QLabel#H2 {{ font-size: 18px; font-weight: 600; }}
    QLabel#Muted {{ color: {TEXT_MUTED}; }}
    QLabel#Mono {{ font-family: "DejaVu Sans Mono", monospace; color: {TEXT_MUTED}; }}

    /* Surfaces / cards */
    QFrame#Card, QFrame#Surface {{
        background-color: {SURFACE};
        border: 1px solid {BORDER};
        border-radius: {RADIUS}px;
    }}

    /* Top bar */
    QFrame#TopBar {{
        background-color: {SURFACE};
        border: none;
        border-bottom: 1px solid {BORDER};
    }}
    QLabel#Logo {{ font-size: 16px; font-weight: 700; color: {PRIMARY}; }}

    /* Search box */
    QLineEdit#Search {{
        background-color: {SURFACE_ALT};
        border: 1px solid {BORDER};
        border-radius: {RADIUS}px;
        padding: 7px 12px;
        selection-background-color: {PRIMARY};
    }}
    QLineEdit#Search:focus {{ border: 1px solid {PRIMARY}; }}

    /* Sidebar */
    QFrame#Sidebar {{
        background-color: {SURFACE};
        border: none;
        border-right: 1px solid {BORDER};
    }}
    QLabel#SidebarGroup {{
        color: {TEXT_MUTED};
        font-size: 11px;
        font-weight: 700;
        padding: 6px 14px 2px 14px;
    }}
    QPushButton#NavItem {{
        text-align: left;
        border: none;
        border-radius: {RADIUS}px;
        padding: 8px 12px;
        margin: 1px 8px;
        color: {TEXT};
        background: transparent;
    }}
    QPushButton#NavItem:hover {{ background-color: {SURFACE_ALT}; }}
    QPushButton#NavItem:checked {{
        background-color: {PRIMARY};
        color: #ffffff;
        font-weight: 600;
    }}

    /* Generic buttons */
    QPushButton {{
        background-color: {SURFACE_ALT};
        border: 1px solid {BORDER};
        border-radius: {RADIUS}px;
        padding: 7px 14px;
    }}
    QPushButton:hover {{ border-color: {PRIMARY}; }}
    QPushButton#Primary {{ background-color: {PRIMARY}; border: none; color: #fff; font-weight: 600; }}

    /* Status bar */
    QFrame#StatusBar {{
        background-color: {SURFACE};
        border: none;
        border-top: 1px solid {BORDER};
    }}
    QLabel#StatusItem {{ color: {TEXT_MUTED}; font-family: "DejaVu Sans Mono", monospace; font-size: 12px; }}

    /* Photo grid */
    QListView#PhotoGrid {{
        background-color: {BACKGROUND};
        border: none;
    }}
    QListView#PhotoGrid::item {{ border-radius: {RADIUS}px; }}
    QListView#PhotoGrid::item:selected {{ background-color: {SURFACE_ALT}; }}

    QScrollBar:vertical {{ background: transparent; width: 10px; margin: 0; }}
    QScrollBar::handle:vertical {{ background: {BORDER}; border-radius: 5px; min-height: 30px; }}
    QScrollBar::handle:vertical:hover {{ background: {TEXT_MUTED}; }}
    QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; }}
    """
