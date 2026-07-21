"""Reusable UI components for the PhotoSphere AI desktop app.

Small, single-responsibility widgets composed by the pages and the main window:
a card frame, stat tile, sidebar, top bar, status bar, person card, and an
honest "planned feature" page for sections whose backend module is not built
yet. Every widget is styled by :mod:`viewer.theme`.
"""

from __future__ import annotations

from typing import Optional

from PySide6 import QtCore, QtWidgets

from viewer import icons, theme


def _human_bytes(num: float) -> str:
    """Format a byte count as a compact human-readable string."""
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if abs(num) < 1024.0:
            return f"{num:.0f} {unit}" if unit == "B" else f"{num:.1f} {unit}"
        num /= 1024.0
    return f"{num:.1f} PB"


def format_duration(seconds: float) -> str:
    """Format a duration as M:SS, or H:MM:SS past an hour."""
    total = max(0, int(seconds))
    hours, rem = divmod(total, 3600)
    minutes, secs = divmod(rem, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{secs:02d}"
    return f"{minutes}:{secs:02d}"


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
    stop_requested = QtCore.Signal()
    continue_requested = QtCore.Signal()

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
        self.search.setPlaceholderText("Search your memories…   (Ctrl+K)")
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(self.search_changed.emit)
        self.search.setMaximumWidth(520)

        self.continue_btn = QtWidgets.QPushButton("Continue")
        self.continue_btn.clicked.connect(self.continue_requested.emit)
        self.continue_btn.setVisible(False)

        self.stop_btn = QtWidgets.QPushButton("Stop")
        self.stop_btn.clicked.connect(self._on_stop_clicked)
        self.stop_btn.setVisible(False)

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
        layout.addWidget(self.continue_btn)
        layout.addWidget(self.stop_btn)
        layout.addWidget(self.reindex_btn)
        layout.addWidget(self.import_btn)
        self._layout = layout

    def add_trailing(self, widget: QtWidgets.QWidget) -> None:
        """Append a widget (e.g. the notification bell) to the right of the bar."""
        self._layout.addWidget(widget)

    def _on_stop_clicked(self) -> None:
        # Give immediate feedback; the worker stops at the next progress tick.
        self.stop_btn.setEnabled(False)
        self.stop_btn.setText("Stopping…")
        self.stop_requested.emit()

    def set_running(self) -> None:
        """Pipeline started: show Stop, hide Continue, disable import/re-index."""
        self.import_btn.setEnabled(False)
        self.reindex_btn.setEnabled(False)
        self.continue_btn.setVisible(False)
        self.stop_btn.setVisible(True)
        self.stop_btn.setEnabled(True)
        self.stop_btn.setText("Stop")

    def set_stopped(self) -> None:
        """Pipeline stopped by user: offer Continue to resume."""
        self.import_btn.setEnabled(True)
        self.reindex_btn.setEnabled(True)
        self.stop_btn.setVisible(False)
        self.continue_btn.setVisible(True)

    def set_idle(self) -> None:
        """No pipeline running (finished or never started)."""
        self.import_btn.setEnabled(True)
        self.reindex_btn.setEnabled(True)
        self.stop_btn.setVisible(False)
        self.continue_btn.setVisible(False)

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
        self._progress.setFixedWidth(150)
        self._progress.setTextVisible(False)
        self._progress.setVisible(False)
        self._clock = self._item("")           # elapsed + ETA
        self._clock.setVisible(False)

        self._backend = self._item("PostgreSQL • pgvector")
        self._gpu = self._item("GPU: —")
        self._ai = self._item("AI: Idle")
        self._ai.setObjectName("StatusAccent")

        for widget in (self._photos, self._faces, self._people, self._storage):
            layout.addWidget(widget)
        layout.addStretch(1)
        layout.addWidget(self._step)
        layout.addWidget(self._progress)
        layout.addWidget(self._clock)
        layout.addStretch(1)
        layout.addWidget(self._backend)
        layout.addWidget(self._gpu)
        layout.addWidget(self._ai)

        # A 1-second tick keeps the elapsed clock moving between progress calls.
        self._elapsed = QtCore.QElapsedTimer()   # overall pipeline time
        self._stage_elapsed = QtCore.QElapsedTimer()  # current stage, for ETA
        self._last_done = 0
        self._last_total = 0
        self._active = False
        self._stage = ""
        self._tick_timer = QtCore.QTimer(self)
        self._tick_timer.setInterval(1000)
        self._tick_timer.timeout.connect(self._refresh_clock)

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
        """Show/clear the current pipeline stage and toggle the progress + clock."""
        if step:
            self._stage = step
            self._step.setText(step)
            self._ai.setText(f"AI: {step}")
            self._progress.setVisible(True)
            self._clock.setVisible(True)
            self._last_done = 0
            self._last_total = 0
            self._stage_elapsed.restart()      # ETA is measured per stage
            if not self._active:               # overall clock starts once
                self._elapsed.restart()
                self._active = True
                self._tick_timer.start()
            self._refresh_clock()
        else:
            self._active = False
            self._tick_timer.stop()
            self._step.setText("")
            self._ai.setText("AI: Idle")
            self._progress.setVisible(False)
            self._progress.reset()
            self._clock.setVisible(False)
            self._clock.setText("")

    def set_progress(self, done: int, total: int) -> None:
        """Update the progress bar; total == 0 shows an indeterminate (busy) bar."""
        self._last_done = done
        self._last_total = total
        if total <= 0:
            self._progress.setRange(0, 0)  # busy indicator
            self._step.setText(f"{self._stage}  {done}")
        else:
            self._progress.setRange(0, total)
            self._progress.setValue(done)
            pct = int(done * 100 / total) if total else 0
            self._step.setText(f"{self._stage}  {done}/{total}  ({pct}%)")
        self._refresh_clock()

    def _refresh_clock(self) -> None:
        """Update the elapsed time and (when possible) the ETA."""
        if not self._active:
            return
        elapsed_s = self._elapsed.elapsed() / 1000.0
        text = f"⏱ {format_duration(elapsed_s)}"

        # ETA from the current stage's throughput.
        if self._last_total > 0 and self._last_done > 0:
            stage_s = self._stage_elapsed.elapsed() / 1000.0
            rate = self._last_done / stage_s if stage_s > 0 else 0.0
            if rate > 0:
                remaining = (self._last_total - self._last_done) / rate
                text += f"   ETA {format_duration(remaining)}"
        self._clock.setText(text)


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
