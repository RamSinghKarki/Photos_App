"""Reusable UI components for the PhotoSphere AI desktop app.

Small, single-responsibility widgets composed by the pages and the main window:
a card frame, stat tile, sidebar, top bar, status bar, person card, and an
honest "planned feature" page for sections whose backend module is not built
yet. Every widget is styled by :mod:`viewer.theme`.
"""

from __future__ import annotations

from typing import Optional

from PySide6 import QtCore, QtGui, QtWidgets

from viewer import icons, theme


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
            for label, key in items:
                button = QtWidgets.QPushButton(f"  {label}")
                button.setObjectName("NavItem")
                button.setCheckable(True)
                button.setIcon(icons.nav_icon(key, theme.TEXT))
                button.setIconSize(QtCore.QSize(20, 20))
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
    reindex_requested = QtCore.Signal()

    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("TopBar")
        self.setFixedHeight(56)

        layout = QtWidgets.QHBoxLayout(self)
        layout.setContentsMargins(16, 8, 16, 8)
        layout.setSpacing(10)

        logo_mark = QtWidgets.QLabel("◆")
        logo_mark.setObjectName("LogoMark")
        logo = QtWidgets.QLabel("PhotoSphere AI")
        logo.setObjectName("Logo")

        self.search = QtWidgets.QLineEdit()
        self.search.setObjectName("Search")
        self.search.setPlaceholderText("Search photos…  (Ctrl+F)")
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(self.search_changed.emit)
        self.search.setMaximumWidth(520)

        self.reindex_btn = QtWidgets.QPushButton("Re-index")
        self.reindex_btn.clicked.connect(self.reindex_requested.emit)

        self.import_btn = QtWidgets.QPushButton("Import Folder")
        self.import_btn.setObjectName("Primary")
        self.import_btn.clicked.connect(self.import_requested.emit)

        layout.addWidget(logo_mark)
        layout.addWidget(logo)
        layout.addSpacing(12)
        layout.addWidget(self.search, 1)
        layout.addStretch(1)
        layout.addWidget(self.reindex_btn)
        layout.addWidget(self.import_btn)

    def set_busy(self, busy: bool) -> None:
        """Disable the import/re-index buttons while a pipeline is running."""
        self.import_btn.setEnabled(not busy)
        self.reindex_btn.setEnabled(not busy)

    def focus_search(self) -> None:
        """Move keyboard focus to the search field (Ctrl+F)."""
        self.search.setFocus()
        self.search.selectAll()


class StatusBar(QtWidgets.QFrame):
    """Bottom status bar: library counts, live job progress, GPU and AI status."""

    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("StatusBar")
        self.setFixedHeight(30)

        layout = QtWidgets.QHBoxLayout(self)
        layout.setContentsMargins(14, 0, 14, 0)
        layout.setSpacing(16)

        self._photos = self._item("Photos: —")
        self._faces = self._item("Faces: —")
        self._people = self._item("People: —")
        self._storage = self._item("Storage: —")

        # Job progress (hidden until a pipeline runs).
        self._step = self._item("")
        self._progress = QtWidgets.QProgressBar()
        self._progress.setFixedWidth(160)
        self._progress.setTextVisible(False)
        self._progress.setVisible(False)

        self._backend = self._item("PostgreSQL • pgvector")
        self._gpu = self._item("GPU: —")
        self._ai = self._item("AI: Idle")
        self._ai.setObjectName("StatusAccent")

        for widget in (self._photos, self._faces, self._people, self._storage):
            layout.addWidget(widget)
        layout.addStretch(1)
        layout.addWidget(self._step)
        layout.addWidget(self._progress)
        layout.addStretch(1)
        layout.addWidget(self._backend)
        layout.addWidget(self._gpu)
        layout.addWidget(self._ai)

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

    def set_gpu(self, text: str) -> None:
        """Set the GPU badge (e.g. 'GPU: NVIDIA RTX 5060' or 'GPU: CPU only')."""
        self._gpu.setText(text)

    def set_step(self, step: Optional[str]) -> None:
        """Show/clear the current pipeline stage and toggle the progress bar."""
        if step:
            self._step.setText(step)
            self._ai.setText(f"AI: {step}")
            self._progress.setVisible(True)
        else:
            self._step.setText("")
            self._ai.setText("AI: Idle")
            self._progress.setVisible(False)
            self._progress.reset()

    def set_progress(self, done: int, total: int) -> None:
        """Update the progress bar; total == 0 shows an indeterminate (busy) bar."""
        if total <= 0:
            self._progress.setRange(0, 0)  # busy indicator
            self._step_suffix(done, None)
        else:
            self._progress.setRange(0, total)
            self._progress.setValue(done)
            self._step_suffix(done, total)

    def _step_suffix(self, done: int, total: Optional[int]) -> None:
        base = self._step.text().split("  ")[0]
        if not base:
            return
        self._step.setText(f"{base}  {done}/{total}" if total else f"{base}  {done}")


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
