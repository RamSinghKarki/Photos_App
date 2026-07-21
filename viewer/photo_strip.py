"""A horizontal row of clickable photo thumbnails (dashboard, memories).

Thumbnails are the small pre-generated cache files, decoded on a background pool
so a strip never blocks the UI thread — the same async pattern the gallery uses,
scaled down for a short, fixed-height row. Emits :attr:`photo_activated`.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Optional

from PySide6 import QtCore, QtGui, QtWidgets

from viewer import theme

_H = 118  # strip thumbnail height (px)


class _Signals(QtCore.QObject):
    loaded = QtCore.Signal(int, object)  # index, QImage


class _Task(QtCore.QRunnable):
    def __init__(self, index: int, path: str, signals: _Signals) -> None:
        super().__init__()
        self._index, self._path, self._signals = index, path, signals

    def run(self) -> None:
        img = QtGui.QImage(self._path)
        if not img.isNull():
            img = img.scaledToHeight(_H, QtCore.Qt.TransformationMode.SmoothTransformation)
        self._signals.loaded.emit(self._index, img)


class _Thumb(QtWidgets.QLabel):
    """One clickable thumbnail; rounded, with a neutral placeholder."""

    clicked = QtCore.Signal(int)  # photo_id

    def __init__(self, photo_id: int) -> None:
        super().__init__()
        self._photo_id = photo_id
        self.setFixedHeight(_H)
        self.setMinimumWidth(64)
        self.setCursor(QtCore.Qt.CursorShape.PointingHandCursor)
        self.setStyleSheet(
            f"border-radius: {theme.RADIUS}px; background: {theme.SURFACE};"
        )

    def set_image(self, image: QtGui.QImage) -> None:
        if image.isNull():
            return
        rounded = QtGui.QPixmap(image.size())
        rounded.fill(QtCore.Qt.GlobalColor.transparent)
        painter = QtGui.QPainter(rounded)
        painter.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing, True)
        clip = QtGui.QPainterPath()
        clip.addRoundedRect(0, 0, image.width(), image.height(), theme.RADIUS, theme.RADIUS)
        painter.setClipPath(clip)
        painter.drawImage(0, 0, image)
        painter.end()
        self.setFixedWidth(image.width())
        self.setPixmap(rounded)

    def mousePressEvent(self, event: QtGui.QMouseEvent) -> None:  # noqa: N802
        if event.button() == QtCore.Qt.MouseButton.LeftButton:
            self.clicked.emit(self._photo_id)


class PhotoStrip(QtWidgets.QScrollArea):
    """Fixed-height horizontal scroller of photo thumbnails."""

    photo_activated = QtCore.Signal(int)

    def __init__(self) -> None:
        super().__init__()
        self.setFixedHeight(_H + 16)
        self.setWidgetResizable(True)
        self.setFrameShape(QtWidgets.QFrame.Shape.NoFrame)
        self.setVerticalScrollBarPolicy(QtCore.Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarPolicy.ScrollBarAsNeeded)

        self._row = QtWidgets.QWidget()
        self._layout = QtWidgets.QHBoxLayout(self._row)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._layout.setSpacing(8)
        self._layout.addStretch(1)
        self.setWidget(self._row)

        self._pool = QtCore.QThreadPool.globalInstance()
        self._signals = _Signals()
        self._signals.loaded.connect(self._on_loaded)
        self._thumbs: list[_Thumb] = []
        self._generation = 0

    def set_photos(self, rows: list[tuple[int, str, Optional[str], Any]]) -> None:
        """Populate from (photo_id, file_path, thumbnail_path, taken_at) rows."""
        self._generation += 1
        while self._layout.count() > 1:
            w = self._layout.takeAt(0).widget()
            if w is not None:
                w.setParent(None)
                w.deleteLater()
        self._thumbs = []
        for index, (photo_id, _fp, thumb_path, _taken) in enumerate(rows):
            thumb = _Thumb(photo_id)
            thumb.clicked.connect(self.photo_activated.emit)
            self._layout.insertWidget(self._layout.count() - 1, thumb)
            self._thumbs.append(thumb)
            if thumb_path and Path(thumb_path).exists():
                self._pool.start(_Task(index, thumb_path, self._signals))

    @QtCore.Slot(int, object)
    def _on_loaded(self, index: int, image: QtGui.QImage) -> None:
        if 0 <= index < len(self._thumbs):
            self._thumbs[index].set_image(image)
