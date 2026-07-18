"""Reusable UI components for the PhotoSphere AI desktop app.

Small, single-responsibility widgets composed by the pages and the main window:
a card frame, stat tile, sidebar, top bar, status bar, person card, and an
honest "planned feature" page for sections whose backend module is not built
yet. Every widget is styled by :mod:`viewer.theme`.
"""

from __future__ import annotations

from typing import Optional

from PySide6 import QtCore, QtGui, QtWidgets

from viewer import theme


def _human_bytes(num: float) -> str:
    """Format a byte count as a compact human-readable string."""
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if abs(num) < 1024.0:
            return f"{num:.0f} {unit}" if unit == "B" else f"{num:.1f} {unit}"
        num /= 1024.0
    return f"{num:.1f} PB"


def make_card(child: QtWidgets.QWidget) -> QtWidgets.QFrame:
    """Wrap a widget in a rounded surface 'card' frame."""
    frame = QtWidgets.QFrame()
    frame.setObjectName("Card")
    layout = QtWidgets.QVBoxLayout(frame)
    layout.setContentsMargins(16, 14, 16, 14)
    layout.addWidget(child)
    return frame


class StatCard(QtWidgets.QFrame):
    """A dashboard tile showing a big value and a caption."""

    def __init__(self, caption: str, value: str = "—", accent: str = theme.PRIMARY) -> None:
        super().__init__()
        self.setObjectName("Card")
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(18, 16, 18, 16)

        self._value = QtWidgets.QLabel(value)
        self._value.setStyleSheet(f"font-size: 28px; font-weight: 700; color: {accent};")
        caption_label = QtWidgets.QLabel(caption)
        caption_label.setObjectName("Muted")

        layout.addWidget(self._value)
        layout.addWidget(caption_label)

    def set_value(self, value: str) -> None:
        """Update the headline number."""
        self._value.setText(value)


class Sidebar(QtWidgets.QFrame):
    """Left navigation. Emits :attr:`navigate` with a page key on selection."""

    navigate = QtCore.Signal(str)

    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("Sidebar")
        self.setFixedWidth(210)

        outer = QtWidgets.QVBoxLayout(self)
        outer.setContentsMargins(0, 10, 0, 10)
        outer.setSpacing(0)

        self._buttons: dict[str, QtWidgets.QPushButton] = {}
        self._group = QtWidgets.QButtonGroup(self)
        self._group.setExclusive(True)

        for group_name, items in theme.SIDEBAR_SECTIONS:
            heading = QtWidgets.QLabel(group_name.upper())
            heading.setObjectName("SidebarGroup")
            outer.addWidget(heading)
            for label, key, glyph in items:
                button = QtWidgets.QPushButton(f"  {glyph}   {label}")
                button.setObjectName("NavItem")
                button.setCheckable(True)
                button.setCursor(QtCore.Qt.CursorShape.PointingHandCursor)
                button.clicked.connect(lambda _=False, k=key: self.navigate.emit(k))
                self._group.addButton(button)
                self._buttons[key] = button
                outer.addWidget(button)
        outer.addStretch(1)

    def select(self, key: str) -> None:
        """Programmatically check the nav item for ``key``."""
        if key in self._buttons:
            self._buttons[key].setChecked(True)


class TopBar(QtWidgets.QFrame):
    """Top bar: logo, always-available search box, and an Import button."""

    search_changed = QtCore.Signal(str)
    import_requested = QtCore.Signal()

    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("TopBar")
        self.setFixedHeight(56)

        layout = QtWidgets.QHBoxLayout(self)
        layout.setContentsMargins(16, 8, 16, 8)
        layout.setSpacing(12)

        logo = QtWidgets.QLabel("◆ PhotoSphere AI")
        logo.setObjectName("Logo")

        self.search = QtWidgets.QLineEdit()
        self.search.setObjectName("Search")
        self.search.setPlaceholderText("Search photos…  (Ctrl+F)")
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(self.search_changed.emit)
        self.search.setMaximumWidth(520)

        import_btn = QtWidgets.QPushButton("Import Folder")
        import_btn.setObjectName("Primary")
        import_btn.clicked.connect(self.import_requested.emit)

        layout.addWidget(logo)
        layout.addSpacing(8)
        layout.addWidget(self.search, 1)
        layout.addStretch(1)
        layout.addWidget(import_btn)

    def focus_search(self) -> None:
        """Move keyboard focus to the search field (Ctrl+F)."""
        self.search.setFocus()
        self.search.selectAll()


class StatusBar(QtWidgets.QFrame):
    """Bottom status bar with library counts and environment info."""

    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("StatusBar")
        self.setFixedHeight(28)

        layout = QtWidgets.QHBoxLayout(self)
        layout.setContentsMargins(14, 0, 14, 0)
        layout.setSpacing(18)

        self._photos = self._item("Photos: —")
        self._faces = self._item("Faces: —")
        self._people = self._item("People: —")
        self._storage = self._item("Storage: —")
        backend = self._item("PostgreSQL • pgvector")
        ai = self._item("AI: Idle")

        for widget in (self._photos, self._faces, self._people, self._storage):
            layout.addWidget(widget)
        layout.addStretch(1)
        layout.addWidget(backend)
        layout.addWidget(ai)

    @staticmethod
    def _item(text: str) -> QtWidgets.QLabel:
        label = QtWidgets.QLabel(text)
        label.setObjectName("StatusItem")
        return label

    def update_stats(self, stats: dict[str, int]) -> None:
        """Refresh the counters from a :func:`database.db.library_stats` dict."""
        self._photos.setText(f"Photos: {stats.get('photos', 0):,}")
        self._faces.setText(f"Faces: {stats.get('faces', 0):,}")
        self._people.setText(f"People: {stats.get('persons', 0):,}")
        self._storage.setText(f"Storage: {_human_bytes(stats.get('storage_bytes', 0))}")


class PersonCard(QtWidgets.QFrame):
    """A tappable card for one person: round cover + name + photo count."""

    clicked = QtCore.Signal(int)

    def __init__(self, person: dict) -> None:
        super().__init__()
        self.setObjectName("Card")
        self._person_id = person["id"]
        self.setCursor(QtCore.Qt.CursorShape.PointingHandCursor)
        self.setFixedSize(150, 190)

        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(12, 14, 12, 12)
        layout.setAlignment(QtCore.Qt.AlignmentFlag.AlignHCenter)

        cover = QtWidgets.QLabel()
        cover.setFixedSize(96, 96)
        cover.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        cover.setPixmap(self._round_cover(person.get("cover_path")))
        cover.setScaledContents(False)

        name = person.get("display_name") or "Unknown"
        name_label = QtWidgets.QLabel(name)
        name_label.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        name_label.setStyleSheet("font-weight: 600;")
        count_label = QtWidgets.QLabel(f"{person['face_count']} photos")
        count_label.setObjectName("Muted")
        count_label.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)

        layout.addWidget(cover, 0, QtCore.Qt.AlignmentFlag.AlignHCenter)
        layout.addSpacing(6)
        layout.addWidget(name_label)
        layout.addWidget(count_label)

    @staticmethod
    def _round_cover(path: Optional[str]) -> QtGui.QPixmap:
        """Return a 96px circular cover pixmap (placeholder if no crop)."""
        diameter = 96
        source = QtGui.QPixmap(path) if path else QtGui.QPixmap()
        result = QtGui.QPixmap(diameter, diameter)
        result.fill(QtCore.Qt.GlobalColor.transparent)

        painter = QtGui.QPainter(result)
        painter.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing, True)
        path_clip = QtGui.QPainterPath()
        path_clip.addEllipse(0, 0, diameter, diameter)
        painter.setClipPath(path_clip)

        if not source.isNull():
            scaled = source.scaled(
                diameter, diameter,
                QtCore.Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                QtCore.Qt.TransformationMode.SmoothTransformation,
            )
            painter.drawPixmap(0, 0, scaled)
        else:
            painter.fillRect(0, 0, diameter, diameter, QtGui.QColor(theme.SURFACE_ALT))
            painter.setPen(QtGui.QColor(theme.TEXT_MUTED))
            painter.drawText(result.rect(), QtCore.Qt.AlignmentFlag.AlignCenter, "☺")
        painter.end()
        return result

    def mousePressEvent(self, event: QtGui.QMouseEvent) -> None:  # noqa: N802 (Qt name)
        self.clicked.emit(self._person_id)
        super().mousePressEvent(event)


class ComingSoonPage(QtWidgets.QWidget):
    """An honest placeholder for a navigation section whose module is planned.

    This is intentional product state, not stubbed logic: it names the feature
    and the module that will provide it, so the sidebar can mirror the full
    product vision without pretending unbuilt features work.
    """

    def __init__(self, title: str, note: str) -> None:
        super().__init__()
        layout = QtWidgets.QVBoxLayout(self)
        layout.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)

        heading = QtWidgets.QLabel(title)
        heading.setObjectName("H1")
        heading.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        subtitle = QtWidgets.QLabel(note)
        subtitle.setObjectName("Muted")
        subtitle.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)

        layout.addWidget(heading)
        layout.addSpacing(6)
        layout.addWidget(subtitle)
