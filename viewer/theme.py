"""Windows 11 Fluent-inspired dark theme for PhotoSphere AI.

A single source of truth for colours, radii, and the application stylesheet.
The look leans on soft dark surfaces, a light-blue accent, subtle borders and
hover states, and a left accent indicator on the selected nav item — so the app
reads as modern native desktop software, not a web page.
"""

from __future__ import annotations

import os

# --- Palette (PhotoSphere 2.0 dark identity, PDD §4) -----------------------
# Layered surfaces L0..L3 (window → cards → dialogs → popups); a neutral ramp
# with a faint cool bias toward the accent, one blue accent, semantic status.
BACKGROUND = "#1a1c20"     # L0 — app background
SURFACE = "#22252b"        # L1 — cards, sidebar, bars
SURFACE_ALT = "#2a2e37"    # L2 — hover / elevated / dialogs
SURFACE_HI = "#313640"     # L3 — popups / palette / pressed
BORDER = "#34383f"
PRIMARY = "#5b9cf5"        # accent blue (hover/lines)
PRIMARY_DEEP = "#4a8df0"   # filled buttons
ACCENT_SOFT = "rgba(74, 141, 240, 0.16)"  # accent wash (selection)
ACCENT = "#4dbb7a"         # green — active / success
WARNING = "#d9a13b"        # amber
ERROR = "#e5695f"          # red
TEXT = "#e8eaee"           # primary text
TEXT_MUTED = "#9aa1ac"     # secondary / metadata
TEXT_FAINT = "#6b7280"     # tertiary / hints

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


def reduced_motion() -> bool:
    """True when the user asked to minimize animation (accessibility, PDD §4).

    Honours ``PHOTOSPHERE_REDUCED_MOTION`` (1/true/yes/on). When set, motion
    durations collapse to 0 so transitions land instantly with no movement.
    """
    return os.environ.get("PHOTOSPHERE_REDUCED_MOTION", "").strip().lower() in (
        "1", "true", "yes", "on",
    )


def motion_ms(key: str) -> int:
    """Duration for a named motion token — 0 when reduced motion is requested."""
    return 0 if reduced_motion() else MOTION_MS[key]


def tile_colors(seed: int):
    """Two HSL colours for a photo-tile placeholder gradient, keyed by ``seed``.

    Empty/loading tiles get a soft coloured gradient (like the design prototype)
    instead of flat grey, so grids and strips read as alive before thumbnails
    decode. The hue is deterministic per seed, so a tile keeps its colour.
    """
    from PySide6 import QtGui

    hue = (int(seed) * 47) % 360
    top = QtGui.QColor.fromHslF(hue / 360.0, 0.30, 0.32)
    bottom = QtGui.QColor.fromHslF(((hue + 40) % 360) / 360.0, 0.35, 0.20)
    return top, bottom


def build_stylesheet() -> str:
    """Return the global Qt stylesheet (QSS) for the application."""
    return f"""
    * {{
        font-family: "Segoe UI Variable", "Segoe UI", "Inter", "DejaVu Sans", sans-serif;
        font-size: 14px;
        outline: none;
    }}
    QWidget {{ background-color: {BACKGROUND}; color: {TEXT}; }}
    /* Labels ride their parent's surface — never paint their own box. */
    QLabel {{ background: transparent; }}

    QLabel#H1 {{ font-size: 27px; font-weight: 600; }}
    QLabel#H2 {{ font-size: 18px; font-weight: 600; }}
    QLabel#Hero {{ font-size: 34px; font-weight: 600; }}
    QLabel#Muted {{ color: {TEXT_MUTED}; }}
    QLabel#Mono {{ font-family: "Cascadia Code", "Consolas", "DejaVu Sans Mono", monospace; color: {TEXT}; }}

    QFrame#Card, QFrame#Surface {{
        background-color: {SURFACE};
        border: 1px solid {BORDER};
        border-radius: {RADIUS_MD}px;
    }}
    QFrame#Card:hover {{ border-color: {PRIMARY}; }}

    /* Right context inspector (three-pane layout) */
    QFrame#Inspector {{ background-color: {SURFACE_ALT}; border: none; border-left: 1px solid {BORDER}; }}
    QLabel#InspectorLabel {{
        color: {TEXT_FAINT}; font-size: 11px; font-weight: 700;
        letter-spacing: 1px; padding: 14px 2px 6px 2px;
    }}
    QLabel#InspectorEmpty {{ color: {TEXT_FAINT}; }}

    /* Command palette + overlay dialogs */
    QFrame#Palette {{
        background-color: {SURFACE_ALT}; border: 1px solid {BORDER};
        border-radius: {RADIUS_LG}px;
    }}
    QLineEdit#PaletteInput {{
        background: transparent; border: none; border-bottom: 1px solid {BORDER};
        padding: 16px 18px; font-size: 16px; color: {TEXT};
    }}
    QListWidget#PaletteList {{ border: none; background: transparent; padding: 8px; }}
    QListWidget#PaletteList::item {{ padding: 10px 12px; border-radius: {RADIUS}px; color: {TEXT_MUTED}; }}
    QListWidget#PaletteList::item:selected {{ background-color: {ACCENT_SOFT}; color: {TEXT}; }}

    /* Notifications */
    QToolButton#Bell {{ border: none; border-radius: {RADIUS}px; padding: 6px; color: {TEXT_MUTED}; }}
    QToolButton#Bell:hover {{ background-color: {SURFACE_ALT}; color: {TEXT}; }}
    QFrame#NotifPanel {{ background-color: {SURFACE_ALT}; border: 1px solid {BORDER}; border-radius: {RADIUS_MD}px; }}
    QLabel#NotifTitle {{ font-weight: 600; }}
    QLabel#Toast {{
        background-color: {SURFACE_HI}; border: 1px solid {BORDER};
        border-radius: {RADIUS_MD}px; padding: 12px 20px; color: {TEXT};
    }}
    QLabel#Pill {{
        background-color: {ACCENT_SOFT}; color: {PRIMARY};
        border-radius: 9px; padding: 1px 8px; font-size: 11px; font-weight: 700;
    }}

    /* Top bar */
    QFrame#TopBar {{ background-color: {SURFACE}; border: none; border-bottom: 1px solid {BORDER}; }}
    QLabel#Logo {{ font-size: 15px; font-weight: 700; color: {TEXT}; }}
    QLabel#Lens {{
        border: 3px solid {PRIMARY}; border-radius: 10px;
        background-color: {ACCENT_SOFT};
    }}
    QLabel#Kbd {{
        color: {TEXT_FAINT}; font-size: 11px; font-weight: 600;
        border: 1px solid {BORDER}; border-radius: 4px; padding: 1px 5px;
        background-color: {SURFACE};
    }}

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
    QPushButton#NavItem:focus {{ background-color: {SURFACE_ALT}; color: {TEXT}; }}
    QPushButton#NavItem:checked {{
        background-color: {ACCENT_SOFT}; color: {TEXT};
        border-left: 3px solid {PRIMARY}; padding-left: 11px; font-weight: 600;
    }}

    /* Buttons */
    QPushButton {{
        background-color: {SURFACE_ALT}; border: 1px solid {BORDER};
        border-radius: {RADIUS}px; padding: 8px 16px; color: {TEXT};
    }}
    QPushButton:hover {{ border-color: {PRIMARY}; }}
    QPushButton:focus {{ border-color: {PRIMARY}; }}
    QPushButton:pressed {{ background-color: {SURFACE}; }}
    QPushButton#Primary {{ background-color: {PRIMARY_DEEP}; border: none; color: #ffffff; font-weight: 600; }}
    QPushButton#Primary:hover {{ background-color: {PRIMARY}; }}
    QPushButton#Primary:focus {{ background-color: {PRIMARY}; }}

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

    /* Filter chips (Review categories) */
    QPushButton#FilterChip {{
        background-color: {SURFACE_ALT}; border: 1px solid {BORDER};
        border-radius: 14px; padding: 5px 14px; color: {TEXT_MUTED}; font-size: 13px;
    }}
    QPushButton#FilterChip:hover {{ background-color: {SURFACE_HI}; color: {TEXT}; }}
    QPushButton#FilterChip:checked {{
        background-color: {ACCENT_SOFT}; border-color: {PRIMARY}; color: {TEXT};
    }}

    /* Insights stat cards */
    QLabel#StatValue {{ font-size: 30px; font-weight: 800; color: {TEXT}; }}
    QLabel#StatLabel {{ font-size: 13px; font-weight: 600; color: {TEXT_MUTED}; }}

    /* Search: suggestion chips (idle state) + "why matched" evidence chips */
    QPushButton#SearchSuggest {{
        background-color: {SURFACE_ALT}; border: 1px solid {BORDER};
        border-radius: 16px; padding: 9px 16px; color: {TEXT}; font-size: 13px;
    }}
    QPushButton#SearchSuggest:hover {{ border-color: {PRIMARY}; background-color: {SURFACE_HI}; }}
    QPushButton#SearchSuggest:focus {{ border-color: {PRIMARY}; background-color: {SURFACE_HI}; }}
    QLabel#SearchHint {{ color: {TEXT_MUTED}; font-size: 15px; }}
    QLabel#SearchHintSmall {{ color: {TEXT_FAINT}; font-size: 12px; }}
    QLabel#WhyChip {{
        background-color: {ACCENT_SOFT}; color: {PRIMARY};
        border-radius: 10px; padding: 3px 10px; font-size: 12px; font-weight: 600;
    }}

    /* Timeline scrubber rail (Year → month, replaces the old tree) */
    QScrollArea#TimelineRail {{ background-color: {SURFACE}; border: none; border-right: 1px solid {BORDER}; }}
    QScrollArea#TimelineRail > QWidget > QWidget {{ background-color: {SURFACE}; }}
    QLabel#TimelineYear {{
        color: {TEXT}; font-size: 15px; font-weight: 800;
        padding: 16px 10px 4px 12px;
    }}
    QFrame#TimelineMonth {{
        border: none; border-radius: {RADIUS}px; margin: 1px 6px;
        border-left: 3px solid transparent;
    }}
    QFrame#TimelineMonth:hover {{ background-color: {SURFACE_ALT}; }}
    QFrame#TimelineMonth[selected="true"] {{
        background-color: {ACCENT_SOFT}; border-left: 3px solid {PRIMARY};
    }}
    QLabel#TimelineMonthName {{ color: {TEXT_MUTED}; font-size: 13px; padding: 0; }}
    QFrame#TimelineMonth:hover QLabel#TimelineMonthName {{ color: {TEXT}; }}
    QFrame#TimelineMonth[selected="true"] QLabel#TimelineMonthName {{ color: {TEXT}; font-weight: 600; }}
    QLabel#TimelineCount {{ color: {TEXT_FAINT}; font-size: 12px; }}
    QLabel#TimelineHero {{ font-size: 26px; font-weight: 800; }}

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
