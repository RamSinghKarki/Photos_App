"""Virtualized photo grid for the gallery.

A :class:`PhotoGridModel` backs a :class:`PhotoGrid` (``QListView`` in icon
mode). Only visible tiles request data, and thumbnails are decoded lazily and
cached with a bounded LRU, so a 100k-photo library scrolls smoothly without
loading every image — the core performance requirement for the gallery.
"""

from __future__ import annotations

from collections import OrderedDict
from pathlib import Path
from typing import Any, Optional

from PySide6 import QtCore, QtGui, QtWidgets

from viewer import theme

# Roles exposed by the model.
PHOTO_ID_ROLE = int(QtCore.Qt.ItemDataRole.UserRole) + 1

_PLACEHOLDER_CACHE: dict[int, QtGui.QPixmap] = {}


def _placeholder(size: int) -> QtGui.QPixmap:
    """Return a neutral rounded tile used before/without a thumbnail."""
    if size not in _PLACEHOLDER_CACHE:
        pm = QtGui.QPixmap(size, size)
        pm.fill(QtCore.Qt.GlobalColor.transparent)
        painter = QtGui.QPainter(pm)
        painter.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing, True)
        painter.setBrush(QtGui.QColor(theme.SURFACE))
        painter.setPen(QtGui.QColor(theme.BORDER))
        painter.drawRoundedRect(0, 0, size - 1, size - 1, theme.RADIUS, theme.RADIUS)
        painter.end()
        _PLACEHOLDER_CACHE[size] = pm
    return _PLACEHOLDER_CACHE[size]


class PhotoGridModel(QtCore.QAbstractListModel):
    """List model over photo rows, decoding thumbnails on demand.

    Rows are (id, file_path, thumbnail_path, taken_at). Thumbnail pixmaps are
    built lazily in :meth:`data` and held in a bounded LRU cache so memory stays
    flat regardless of library size.
    """

    def __init__(self, tile: int = 160, cache_size: int = 500) -> None:
        super().__init__()
        self._rows: list[tuple[int, str, Optional[str], Any]] = []
        self._tile = tile
        self._cache: "OrderedDict[int, QtGui.QPixmap]" = OrderedDict()
        self._cache_size = cache_size

    # -- data management -----------------------------------------------------
    def set_rows(self, rows: list[tuple[int, str, Optional[str], Any]]) -> None:
        """Replace the model's rows and clear the pixmap cache."""
        self.beginResetModel()
        self._rows = rows
        self._cache.clear()
        self.endResetModel()

    def set_tile_size(self, tile: int) -> None:
        """Change the thumbnail tile size (zoom) and refresh."""
        self._tile = tile
        self._cache.clear()
        if self._rows:
            top = self.index(0)
            bottom = self.index(len(self._rows) - 1)
            self.dataChanged.emit(top, bottom, [QtCore.Qt.ItemDataRole.DecorationRole])

    def tile_size(self) -> int:
        return self._tile

    def photo_id_at(self, row: int) -> Optional[int]:
        if 0 <= row < len(self._rows):
            return self._rows[row][0]
        return None

    def photo_ids(self) -> list[int]:
        return [row[0] for row in self._rows]

    # -- QAbstractListModel --------------------------------------------------
    def rowCount(self, parent: QtCore.QModelIndex = QtCore.QModelIndex()) -> int:  # noqa: N802
        return 0 if parent.isValid() else len(self._rows)

    def data(self, index: QtCore.QModelIndex, role: int = QtCore.Qt.ItemDataRole.DisplayRole):
        if not index.isValid() or not (0 <= index.row() < len(self._rows)):
            return None
        photo_id, file_path, thumb_path, _taken = self._rows[index.row()]

        if role == PHOTO_ID_ROLE:
            return photo_id
        if role == QtCore.Qt.ItemDataRole.ToolTipRole:
            return Path(file_path).name
        if role == QtCore.Qt.ItemDataRole.DecorationRole:
            return self._thumbnail(index.row(), thumb_path)
        return None

    # -- thumbnail cache -----------------------------------------------------
    def _thumbnail(self, row: int, thumb_path: Optional[str]) -> QtGui.QPixmap:
        if row in self._cache:
            self._cache.move_to_end(row)
            return self._cache[row]

        pixmap = QtGui.QPixmap()
        if thumb_path and Path(thumb_path).exists():
            pixmap = QtGui.QPixmap(thumb_path)

        if pixmap.isNull():
            pixmap = _placeholder(self._tile)
        else:
            pixmap = pixmap.scaled(
                self._tile, self._tile,
                QtCore.Qt.AspectRatioMode.KeepAspectRatio,
                QtCore.Qt.TransformationMode.SmoothTransformation,
            )

        self._cache[row] = pixmap
        if len(self._cache) > self._cache_size:
            self._cache.popitem(last=False)  # evict least-recently-used
        return pixmap


class PhotoGrid(QtWidgets.QListView):
    """Icon-mode grid view over a :class:`PhotoGridModel`."""

    photo_activated = QtCore.Signal(int)

    def __init__(self, model: PhotoGridModel) -> None:
        super().__init__()
        self.setObjectName("PhotoGrid")
        self.setModel(model)
        self._model = model

        self.setViewMode(QtWidgets.QListView.ViewMode.IconMode)
        self.setResizeMode(QtWidgets.QListView.ResizeMode.Adjust)
        self.setMovement(QtWidgets.QListView.Movement.Static)
        self.setSelectionMode(QtWidgets.QAbstractItemView.SelectionMode.ExtendedSelection)
        self.setUniformItemSizes(True)
        self.setSpacing(8)
        self.setWordWrap(False)
        self.verticalScrollBar().setSingleStep(24)
        self._apply_tile()

        self.doubleClicked.connect(self._on_activated)

    def _apply_tile(self) -> None:
        tile = self._model.tile_size()
        self.setIconSize(QtCore.QSize(tile, tile))
        self.setGridSize(QtCore.QSize(tile + 16, tile + 16))

    def set_tile_size(self, tile: int) -> None:
        """Zoom the grid tiles (bounded)."""
        tile = max(96, min(360, tile))
        self._model.set_tile_size(tile)
        self._apply_tile()

    def zoom(self, delta: int) -> None:
        """Grow/shrink tiles by ``delta`` px (keyboard +/-)."""
        self.set_tile_size(self._model.tile_size() + delta)

    def _on_activated(self, index: QtCore.QModelIndex) -> None:
        photo_id = index.data(PHOTO_ID_ROLE)
        if photo_id is not None:
            self.photo_activated.emit(int(photo_id))

    def keyPressEvent(self, event: QtGui.QKeyEvent) -> None:  # noqa: N802
        if event.key() in (QtCore.Qt.Key.Key_Return, QtCore.Qt.Key.Key_Enter):
            index = self.currentIndex()
            if index.isValid():
                self._on_activated(index)
                return
        super().keyPressEvent(event)
