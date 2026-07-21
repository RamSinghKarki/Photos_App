"""Immersive photo viewer workspace (PDD §6.3).

Opened from any gallery. A dark stage holds the full-resolution image; a tabbed
inspector on the right shows **People / Info / Text / Similar** for the current
photo; a filmstrip along the bottom navigates the set. Keyboard: ←/→ move,
**Space** hides all chrome (image only), **F** favorites, **I** toggles the
inspector, **F11** full screen, **Esc** closes. Clicking a person opens their
profile; "Find similar" runs a visual search — both surface via
:attr:`requested_person` / :attr:`requested_similar`, read by the caller after
the dialog closes (so navigation happens on the main window, not behind a modal).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Optional

from PySide6 import QtCore, QtGui, QtWidgets

from viewer import data, theme
from viewer.appearance_strip import _rounded_square
from viewer.components import _human_bytes
from viewer.photo_strip import PhotoStrip


class _InfoTab(QtWidgets.QScrollArea):
    """Read-only metadata, rebuilt per photo."""

    def __init__(self) -> None:
        super().__init__()
        self.setWidgetResizable(True)
        self.setFrameShape(QtWidgets.QFrame.Shape.NoFrame)
        body = QtWidgets.QWidget()
        self._form = QtWidgets.QFormLayout(body)
        self._form.setContentsMargins(16, 16, 16, 16)
        self._form.setVerticalSpacing(8)
        self._form.setLabelAlignment(QtCore.Qt.AlignmentFlag.AlignRight)
        self.setWidget(body)

    def _row(self, label: str, value: str) -> None:
        key = QtWidgets.QLabel(label)
        key.setObjectName("Muted")
        val = QtWidgets.QLabel(value or "—")
        val.setObjectName("Mono")
        val.setWordWrap(True)
        self._form.addRow(key, val)

    def show_detail(self, detail: dict[str, Any]) -> None:
        while self._form.rowCount():
            self._form.removeRow(0)
        dims = (
            f"{detail['width']} × {detail['height']}"
            if detail.get("width") and detail.get("height") else "—"
        )
        taken = detail["taken_at"].strftime("%b %d, %Y  %H:%M") if detail.get("taken_at") else "—"
        gps = (
            f"{detail['gps_latitude']:.5f}, {detail['gps_longitude']:.5f}"
            if detail.get("gps_latitude") is not None else "—"
        )
        camera = " ".join(
            part for part in (detail.get("camera_make"), detail.get("camera_model")) if part
        ) or "—"
        self._row("File", Path(detail["file_path"]).name)
        self._row("Taken", taken)
        self._row("Camera", camera)
        self._row("Dimensions", dims)
        self._row("Size", _human_bytes(detail.get("file_size") or 0))
        self._row("Format", detail.get("format") or "—")
        self._row("Place", gps)


class PhotoViewer(QtWidgets.QDialog):
    """Immersive viewer navigating a list of photo ids."""

    def __init__(self, photo_ids: list[int], start_index: int, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("PhotoSphere AI — Viewer")
        self.setStyleSheet(theme.build_stylesheet())
        self.resize(1180, 780)

        self._ids = photo_ids
        self._index = max(0, min(start_index, len(photo_ids) - 1)) if photo_ids else 0
        self._source_pixmap: Optional[QtGui.QPixmap] = None
        self._is_favorite = False
        self._immersive = False
        # Deferred navigation the caller performs after the dialog closes.
        self.requested_person: Optional[int] = None
        self.requested_similar: Optional[int] = None

        self._fade = QtCore.QPropertyAnimation(self, b"windowOpacity", self)
        self._fade.setDuration(theme.motion_ms("photo_open"))
        self._fade.setStartValue(0.0)
        self._fade.setEndValue(1.0)
        self._faded_in = False

        root = QtWidgets.QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        content = QtWidgets.QHBoxLayout()
        content.setContentsMargins(0, 0, 0, 0)
        content.setSpacing(0)

        # --- stage (image + slim action bar) ---
        stage = QtWidgets.QVBoxLayout()
        stage.setContentsMargins(0, 0, 0, 0)
        stage.setSpacing(0)
        self._image = QtWidgets.QLabel()
        self._image.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        self._image.setMinimumSize(400, 300)
        self._image.setStyleSheet("background: #101216;")

        self._bar = QtWidgets.QFrame()
        self._bar.setObjectName("TopBar")
        bar = QtWidgets.QHBoxLayout(self._bar)
        bar.setContentsMargins(12, 8, 12, 8)
        prev_btn = QtWidgets.QPushButton("←")
        next_btn = QtWidgets.QPushButton("→")
        prev_btn.clicked.connect(self.show_prev)
        next_btn.clicked.connect(self.show_next)
        self._counter = QtWidgets.QLabel("")
        self._counter.setObjectName("Muted")
        self._fav_btn = QtWidgets.QPushButton("♡")
        self._fav_btn.setToolTip("Favorite (F)")
        self._fav_btn.clicked.connect(self.toggle_favorite)
        info_btn = QtWidgets.QPushButton("Details (I)")
        info_btn.clicked.connect(self.toggle_panel)
        hide_btn = QtWidgets.QPushButton("Immersive (Space)")
        hide_btn.clicked.connect(self.toggle_immersive)
        for wdg in (prev_btn, next_btn, self._counter):
            bar.addWidget(wdg)
        bar.addStretch(1)
        for wdg in (self._fav_btn, info_btn, hide_btn):
            bar.addWidget(wdg)
        stage.addWidget(self._image, 1)
        stage.addWidget(self._bar)
        content.addLayout(stage, 1)

        # --- tabbed inspector ---
        self._tabs = QtWidgets.QTabWidget()
        self._tabs.setFixedWidth(300)
        self._people_tab = QtWidgets.QScrollArea()
        self._people_tab.setWidgetResizable(True)
        self._people_tab.setFrameShape(QtWidgets.QFrame.Shape.NoFrame)
        self._info_tab = _InfoTab()
        self._text_tab = QtWidgets.QLabel("")
        self._text_tab.setWordWrap(True)
        self._text_tab.setAlignment(QtCore.Qt.AlignmentFlag.AlignTop)
        self._text_tab.setContentsMargins(16, 16, 16, 16)
        similar = QtWidgets.QWidget()
        sl = QtWidgets.QVBoxLayout(similar)
        sl.setContentsMargins(16, 16, 16, 16)
        find_btn = QtWidgets.QPushButton("Find similar photos")
        find_btn.setObjectName("Primary")
        find_btn.clicked.connect(self._request_similar)
        sl.addWidget(find_btn)
        sl.addStretch(1)
        self._tabs.addTab(self._people_tab, "People")
        self._tabs.addTab(self._info_tab, "Info")
        self._tabs.addTab(self._text_tab, "Text")
        self._tabs.addTab(similar, "Similar")
        content.addWidget(self._tabs)

        root.addLayout(content, 1)

        # --- filmstrip ---
        self._film = PhotoStrip()
        self._film.photo_activated.connect(self._jump_to)
        root.addWidget(self._film)

        if self._ids:
            self._film.set_photos(data.photos_brief(self._ids))
            self._load_current()

    def showEvent(self, event: QtGui.QShowEvent) -> None:  # noqa: N802
        super().showEvent(event)
        if not self._faded_in:
            self._faded_in = True
            self.setWindowOpacity(0.0)
            self._fade.start()

    # -- navigation ----------------------------------------------------------
    def show_next(self) -> None:
        if self._ids and self._index < len(self._ids) - 1:
            self._index += 1
            self._load_current()

    def show_prev(self) -> None:
        if self._ids and self._index > 0:
            self._index -= 1
            self._load_current()

    def _jump_to(self, photo_id: int) -> None:
        if photo_id in self._ids:
            self._index = self._ids.index(photo_id)
            self._load_current()

    # -- chrome --------------------------------------------------------------
    def toggle_panel(self) -> None:
        self._tabs.setVisible(not self._tabs.isVisible())

    def toggle_immersive(self) -> None:
        """Hide all chrome — just the photo on black (Space)."""
        self._immersive = not self._immersive
        for w in (self._bar, self._tabs, self._film):
            w.setVisible(not self._immersive)

    def toggle_favorite(self) -> None:
        if not self._ids:
            return
        self._is_favorite = not self._is_favorite
        data.set_favorite(self._ids[self._index], self._is_favorite)
        self._update_favorite_button()

    def _update_favorite_button(self) -> None:
        self._fav_btn.setText("♥" if self._is_favorite else "♡")
        self._fav_btn.setStyleSheet(f"color: {theme.ERROR};" if self._is_favorite else "")

    def _request_similar(self) -> None:
        if self._ids:
            self.requested_similar = self._ids[self._index]
            self.close()

    # -- content -------------------------------------------------------------
    def _load_current(self) -> None:
        photo_id = self._ids[self._index]
        detail = data.photo_detail(photo_id)
        if detail is None:
            return
        self._counter.setText(f"{self._index + 1} / {len(self._ids)}")
        self._info_tab.show_detail(detail)
        self._is_favorite = bool(detail.get("is_favorite"))
        self._update_favorite_button()

        ocr = (detail.get("ocr_text") or "").strip()
        self._text_tab.setText(ocr if ocr else "No text found in this photo.")
        self._text_tab.setObjectName("" if ocr else "Muted")

        self._populate_people(photo_id)

        pixmap = QtGui.QPixmap(detail["file_path"])
        self._source_pixmap = pixmap if not pixmap.isNull() else None
        self._render_image()

    def _populate_people(self, photo_id: int) -> None:
        holder = QtWidgets.QWidget()
        col = QtWidgets.QVBoxLayout(holder)
        col.setContentsMargins(12, 12, 12, 12)
        col.setSpacing(8)
        col.setAlignment(QtCore.Qt.AlignmentFlag.AlignTop)
        people = data.photo_people(photo_id)
        if not people:
            note = QtWidgets.QLabel("No named people here yet.")
            note.setObjectName("Muted")
            col.addWidget(note)
        for person in people:
            btn = QtWidgets.QToolButton()
            btn.setToolButtonStyle(QtCore.Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
            btn.setAutoRaise(True)
            btn.setCursor(QtCore.Qt.CursorShape.PointingHandCursor)
            btn.setIcon(QtGui.QIcon(_rounded_square(person.get("crop_path"), 40)))
            btn.setIconSize(QtCore.QSize(40, 40))
            btn.setText("  " + (person.get("display_name") or "Unknown"))
            btn.clicked.connect(lambda _c=False, pid=person["id"]: self._open_person(pid))
            col.addWidget(btn)
        self._people_tab.setWidget(holder)

    def _open_person(self, person_id: int) -> None:
        self.requested_person = person_id
        self.close()

    def _render_image(self) -> None:
        if self._source_pixmap is None:
            self._image.setText("Unable to load image")
            return
        scaled = self._source_pixmap.scaled(
            self._image.size(),
            QtCore.Qt.AspectRatioMode.KeepAspectRatio,
            QtCore.Qt.TransformationMode.SmoothTransformation,
        )
        self._image.setPixmap(scaled)

    # -- Qt events -----------------------------------------------------------
    def resizeEvent(self, event: QtGui.QResizeEvent) -> None:  # noqa: N802
        super().resizeEvent(event)
        self._render_image()

    def keyPressEvent(self, event: QtGui.QKeyEvent) -> None:  # noqa: N802
        key = event.key()
        if key == QtCore.Qt.Key.Key_Right:
            self.show_next()
        elif key == QtCore.Qt.Key.Key_Left:
            self.show_prev()
        elif key == QtCore.Qt.Key.Key_Space:
            self.toggle_immersive()
        elif key == QtCore.Qt.Key.Key_I:
            self.toggle_panel()
        elif key == QtCore.Qt.Key.Key_F:
            self.toggle_favorite()
        elif key == QtCore.Qt.Key.Key_F11:
            self.setWindowState(self.windowState() ^ QtCore.Qt.WindowState.WindowFullScreen)
        elif key == QtCore.Qt.Key.Key_Escape:
            self.close()
        else:
            super().keyPressEvent(event)
