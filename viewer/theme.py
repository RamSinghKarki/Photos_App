"""Windows 11 Fluent-inspired dark theme for PhotoSphere AI.

A single source of truth for colours, radii, and the application stylesheet.
The look leans on soft dark surfaces, a light-blue accent, subtle borders and
hover states, and a left accent indicator on the selected nav item — so the app
reads as modern native desktop software, not a web page.
"""

from __future__ import annotations

# --- Palette (Fluent dark) -------------------------------------------------
BACKGROUND = "#17181d"     # app background
SURFACE = "#20222a"        # cards, bars, panels
SURFACE_ALT = "#2a2d37"    # hover / elevated
BORDER = "#31353f"
PRIMARY = "#4cc2ff"        # Windows 11 accent blue
PRIMARY_DEEP = "#3a86ff"   # stronger blue for filled buttons
ACCENT = "#5bd6a0"         # green — active / success
WARNING = "#f5b445"        # amber
ERROR = "#ff6b6b"          # red
TEXT = "#e8eaed"           # primary text
TEXT_MUTED = "#98a0ad"     # secondary/metadata text

RADIUS = 8                 # default corner radius (px)

# Sidebar groups and the implemented set derive from the single page registry
# (viewer/registry.py) — adding a page is ONE PageSpec entry, never four edits.
# Icons come from viewer.icons keyed by page-key; drawn line-art, never emoji.
from viewer.registry import implemented_keys, sidebar_sections  # noqa: E402

SIDEBAR_SECTIONS: list[tuple[str, list[tuple[str, str]]]] = sidebar_sections()
IMPLEMENTED_PAGES = implemented_keys()

# --- Design tokens (PDD §4) — the only sanctioned spacing/radius/motion values.
# Components take values from here; literal magic numbers in pages are a review
# failure once the Phase-1 component kit lands.
SPACING = (4, 8, 12, 16, 24, 32, 48)          # px steps; nothing arbitrary
RADIUS_SM, RADIUS_MD, RADIUS_LG = 8, 12, 16   # controls / cards / dialogs
MOTION_MS = {
    "hover": 120, "selection": 150, "fade": 150,
    "dialog": 180, "sidebar": 200, "photo_open": 220,
}  # hard cap 250 ms (PDD); every animation interruptible


def build_stylesheet() -> str:
    """Return the global Qt stylesheet (QSS) for the application."""
    return f"""
    * {{
        font-family: "Segoe UI Variable", "Segoe UI", "Inter", "DejaVu Sans", sans-serif;
        font-size: 14px;
        outline: none;
    }}
    QWidget {{ background-color: {BACKGROUND}; color: {TEXT}; }}

    QLabel#H1 {{ font-size: 24px; font-weight: 700; }}
    QLabel#H2 {{ font-size: 16px; font-weight: 600; }}
    QLabel#Muted {{ color: {TEXT_MUTED}; }}
    QLabel#Mono {{ font-family: "Cascadia Code", "Consolas", "DejaVu Sans Mono", monospace; color: {TEXT}; }}

    QFrame#Card, QFrame#Surface {{
        background-color: {SURFACE};
        border: 1px solid {BORDER};
        border-radius: {RADIUS + 2}px;
    }}
    QFrame#Card:hover {{ border-color: {PRIMARY}; }}

    /* Top bar */
    QFrame#TopBar {{ background-color: {SURFACE}; border: none; border-bottom: 1px solid {BORDER}; }}
    QLabel#Logo {{ font-size: 15px; font-weight: 800; color: {TEXT}; }}
    QLabel#LogoMark {{ font-size: 18px; font-weight: 800; color: {PRIMARY}; }}

    /* Search box (pill) */
    QLineEdit#Search {{
        background-color: {BACKGROUND};
        border: 1px solid {BORDER};
        border-radius: 18px;
        padding: 8px 16px;
        selection-background-color: {PRIMARY_DEEP};
    }}
    QLineEdit#Search:focus {{ border: 1px solid {PRIMARY}; background-color: {SURFACE_ALT}; }}

    /* Sidebar */
    QFrame#Sidebar {{ background-color: {SURFACE}; border: none; border-right: 1px solid {BORDER}; }}
    QLabel#SidebarGroup {{
        color: {TEXT_MUTED}; font-size: 11px; font-weight: 700;
        letter-spacing: 1px; padding: 10px 16px 4px 16px;
    }}
    QPushButton#NavItem {{
        text-align: left; border: none; border-radius: {RADIUS}px;
        padding: 9px 12px 9px 14px; margin: 1px 8px; color: {TEXT_MUTED};
        background: transparent; font-size: 14px;
    }}
    QPushButton#NavItem:hover {{ background-color: {SURFACE_ALT}; color: {TEXT}; }}
    QPushButton#NavItem:checked {{
        background-color: {SURFACE_ALT}; color: {TEXT};
        border-left: 3px solid {PRIMARY}; padding-left: 11px; font-weight: 600;
    }}

    /* Buttons */
    QPushButton {{
        background-color: {SURFACE_ALT}; border: 1px solid {BORDER};
        border-radius: {RADIUS}px; padding: 8px 16px; color: {TEXT};
    }}
    QPushButton:hover {{ border-color: {PRIMARY}; }}
    QPushButton:pressed {{ background-color: {SURFACE}; }}
    QPushButton#Primary {{ background-color: {PRIMARY_DEEP}; border: none; color: #ffffff; font-weight: 600; }}
    QPushButton#Primary:hover {{ background-color: {PRIMARY}; }}

    /* Status bar */
    QFrame#StatusBar {{ background-color: {SURFACE}; border: none; border-top: 1px solid {BORDER}; }}
    QLabel#StatusItem {{ color: {TEXT_MUTED}; font-family: "Cascadia Code", "Consolas", "DejaVu Sans Mono", monospace; font-size: 12px; }}
    QLabel#StatusAccent {{ color: {ACCENT}; font-family: "Cascadia Code", "Consolas", monospace; font-size: 12px; font-weight: 600; }}

    /* Progress bar */
    QProgressBar {{
        background-color: {SURFACE_ALT}; border: none; border-radius: 5px;
        height: 6px; text-align: center; color: transparent;
    }}
    QProgressBar::chunk {{ background-color: {PRIMARY}; border-radius: 5px; }}

    /* Photo grid */
    QListView#PhotoGrid {{ background-color: {BACKGROUND}; border: none; padding: 8px; }}
    QListView#PhotoGrid::item {{ border-radius: {RADIUS}px; }}
    QListView#PhotoGrid::item:selected {{ background-color: {SURFACE_ALT}; }}
    QListView#PhotoGrid::item:hover {{ background-color: {SURFACE}; }}

    /* Lists */
    QListWidget {{ border: 1px solid {BORDER}; border-radius: {RADIUS}px; padding: 6px; }}
    QListWidget::item {{ padding: 6px 8px; border-radius: 6px; }}
    QListWidget::item:hover {{ background-color: {SURFACE_ALT}; }}

    /* Scrollbars */
    QScrollBar:vertical {{ background: transparent; width: 12px; margin: 2px; }}
    QScrollBar::handle:vertical {{ background: {BORDER}; border-radius: 5px; min-height: 36px; }}
    QScrollBar::handle:vertical:hover {{ background: {TEXT_MUTED}; }}
    QScrollBar:horizontal {{ background: transparent; height: 12px; margin: 2px; }}
    QScrollBar::handle:horizontal {{ background: {BORDER}; border-radius: 5px; min-width: 36px; }}
    QScrollBar::add-line, QScrollBar::sub-line {{ width: 0; height: 0; }}
    QScrollBar::add-page, QScrollBar::sub-page {{ background: none; }}
    """
