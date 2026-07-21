"""Full-screen photo viewer with a collapsible metadata panel.

Opened from any gallery. Shows the original image (loaded only now — never in
the grid) scaled to fit, with previous/next navigation across the photo ids it
was given, and a side panel of read-only metadata. Keyboard: ←/→ navigate,
``I`` toggles the panel, ``F11`` toggles full screen, ``Esc`` closes.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Optional

from PySide6 import QtCore, QtGui, QtWidgets

from viewer import data, theme
from viewer.components import _human_bytes


class _MetadataPanel(QtWidgets.QFrame):
    """Read-only metadata table shown beside the image."""

    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("Surface")
        self.setFixedWidth(280)
        self._form = QtWidgets.QFormLayout(self)
        self._form.setContentsMargins(16, 16, 16, 16)
        self._form.setVerticalSpacing(8)
        self._form.setLabelAlignment(QtCore.Qt.AlignmentFlag.AlignRight)

        title = QtWidgets.QLabel("Metadata")
        title.setObjectName("H2")
        self._form.addRow(title)

    def _row(self, label: str, value: str) -> None:
        key = QtWidgets.QLabel(label)
        key.setObjectName("Muted")
        val = QtWidgets.QLabel(value or "—")
        val.setObjectName("Mono")
        val.setWordWrap(True)
        self._form.addRow(key, val)

    def show_detail(self, detail: dict[str, Any]) -> None:
        # Rebuild rows from scratch each time.
        while self._form.rowCount() > 1:
            self._form.removeRow(1)

        dims = (
            f"{detail['width']} × {detail['height']}"
            if detail.get("width") and detail.get("height") else "—"
        )
        taken = detail["taken_at"].strftime("%Y-%m-%d %H:%M:%S") if detail.get("taken_at") else "—"
        gps = (
            f"{detail['gps_latitude']:.5f}, {detail['gps_longitude']:.5f}"
            if detail.get("gps_latitude") is not None else "—"
        )
        camera = " ".join(
            part for part in (detail.get("camera_make"), detail.get("camera_model")) if part
        ) or "—"

        self._row("File", Path(detail["file_path"]).name)
        self._row("Camera", camera)
        self._row("Taken", taken)
        self._row("Dimensions", dims)
        self._row("Size", _human_bytes(detail.get("file_size") or 0))
        self._row("Format", detail.get("format") or "—")
        self._row("GPS", gps)
        self._row("Path", detail["file_path"])


class PhotoViewer(QtWidgets.QDialog):
    """Modal-ish image viewer navigating a list of photo ids."""

    def __init__(self, photo_ids: list[int], start_index: int, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("PhotoSphere AI — Viewer")
        self.setStyleSheet(theme.build_stylesheet())
        self.resize(1100, 720)

        self._ids = photo_ids
        self._index = max(0, min(start_index, len(photo_ids) - 1)) if photo_ids else 0
        self._source_pixmap: Optional[QtGui.QPixmap] = None

        # Gentle fade-in as the viewer opens (the "zoom from thumbnail" moment,
        # kept within the PDD 220 ms motion cap; skipped under reduced motion).
        self._fade = QtCore.QPropertyAnimation(self, b"windowOpacity", self)
        self._fade.setDuration(theme.MOTION_MS["photo_open"])
        self._fade.setStartValue(0.0)
        self._fade.setEndValue(1.0)
        self._faded_in = False

        root = QtWidgets.QHBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # Image area with prev/next overlay buttons.
        image_side = QtWidgets.QVBoxLayout()
        image_side.setContentsMargins(0, 0, 0, 0)

        self._image = QtWidgets.QLabel()
        self._image.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        self._image.setMinimumSize(400, 300)
        self._image.setStyleSheet(f"background: {theme.BACKGROUND};")

        nav = QtWidgets.QHBoxLayout()
        prev_btn = QtWidgets.QPushButton("←  Prev")
        next_btn = QtWidgets.QPushButton("Next  →")
        self._fav_btn = QtWidgets.QPushButton("♡ Favorite (F)")
        toggle_btn = QtWidgets.QPushButton("Info (I)")
        prev_btn.clicked.connect(self.show_prev)
        next_btn.clicked.connect(self.show_next)
        self._fav_btn.clicked.connect(self.toggle_favorite)
        toggle_btn.clicked.connect(self.toggle_panel)
        self._counter = QtWidgets.QLabel("")
        self._counter.setObjectName("Muted")
        self._is_favorite = False
        nav.setContentsMargins(12, 8, 12, 8)
        nav.addWidget(prev_btn)
        nav.addWidget(next_btn)
        nav.addWidget(self._counter)
        nav.addStretch(1)
        nav.addWidget(self._fav_btn)
        nav.addWidget(toggle_btn)

        image_side.addWidget(self._image, 1)
        image_side.addLayout(nav)

        self._panel = _MetadataPanel()

        root.addLayout(image_side, 1)
        root.addWidget(self._panel)

        if self._ids:
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

    def toggle_panel(self) -> None:
        self._panel.setVisible(not self._panel.isVisible())

    def toggle_favorite(self) -> None:
        """Flip the current photo's favorite flag (a user signal for ranking)."""
        if not self._ids:
            return
        photo_id = self._ids[self._index]
        self._is_favorite = not self._is_favorite
        data.set_favorite(photo_id, self._is_favorite)
        self._update_favorite_button()

    def _update_favorite_button(self) -> None:
        self._fav_btn.setText("♥ Favorited (F)" if self._is_favorite else "♡ Favorite (F)")
        self._fav_btn.setStyleSheet(
            f"color: {theme.ERROR};" if self._is_favorite else ""
        )

    def _load_current(self) -> None:
        photo_id = self._ids[self._index]
        detail = data.photo_detail(photo_id)
        if detail is None:
            return
        self._counter.setText(f"{self._index + 1} / {len(self._ids)}")
        self._panel.show_detail(detail)
        self._is_favorite = bool(detail.get("is_favorite"))
        self._update_favorite_button()

        pixmap = QtGui.QPixmap(detail["file_path"])
        self._source_pixmap = pixmap if not pixmap.isNull() else None
        self._render_image()

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
