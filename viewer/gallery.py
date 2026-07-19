"""Virtualized, paged photo grid with asynchronous thumbnail loading.

Two things keep the gallery smooth on very large libraries:

* **Incremental paging** — the model loads photos a page at a time via Qt's
  ``canFetchMore``/``fetchMore`` protocol, so opening the Photos view never
  blocks loading 100k rows at once; more load as you scroll.
* **Off-thread decoding** — thumbnails are decoded on a :class:`QThreadPool`
  as ``QImage`` (thread-safe), then converted to ``QPixmap`` on the GUI thread
  and cached with a bounded LRU. The UI thread never blocks on disk I/O, which
  is what previously made scrolling stutter.
"""

from __future__ import annotations

from collections import OrderedDict
from pathlib import Path
from typing import Any, Callable, Optional

from PySide6 import QtCore, QtGui, QtWidgets

from viewer import theme

# Roles exposed by the model.
PHOTO_ID_ROLE = int(QtCore.Qt.ItemDataRole.UserRole) + 1

# (offset, limit) -> rows of (id, file_path, thumbnail_path, taken_at)
Fetcher = Callable[[int, int], list[tuple[int, str, Optional[str], Any]]]

_PLACEHOLDER_CACHE: dict[int, QtGui.QPixmap] = {}
_PAGE_SIZE = 300


def _placeholder(size: int) -> QtGui.QPixmap:
    """Return a neutral rounded tile shown until a thumbnail is decoded."""
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


class _ThumbSignals(QtCore.QObject):
    """Carries a decoded image back to the model on the GUI thread."""

    loaded = QtCore.Signal(int, int, object)  # generation, row, QImage


class _ThumbTask(QtCore.QRunnable):
    """Decodes and scales one thumbnail on a pool thread."""

    def __init__(self, generation: int, row: int, path: str, size: int, signals: _ThumbSignals):
        super().__init__()
        self._generation = generation
        self._row = row
        self._path = path
        self._size = size
        self._signals = signals

    def run(self) -> None:
        image = QtGui.QImage(self._path)  # QImage is safe to build off the GUI thread
        if not image.isNull():
            image = image.scaled(
                self._size, self._size,
                QtCore.Qt.AspectRatioMode.KeepAspectRatio,
                QtCore.Qt.TransformationMode.SmoothTransformation,
            )
        self._signals.loaded.emit(self._generation, self._row, image)


class PhotoGridModel(QtCore.QAbstractListModel):
    """Paged list model over photo rows with async thumbnail decoding."""

    def __init__(self, tile: int = 168, cache_size: int = 800) -> None:
        super().__init__()
        self._rows: list[tuple[int, str, Optional[str], Any]] = []
        self._fetch: Optional[Fetcher] = None
        self._exhausted = True
        self._tile = tile

        self._cache: "OrderedDict[int, QtGui.QPixmap]" = OrderedDict()
        self._cache_size = cache_size
        self._inflight: set[int] = set()
        self._generation = 0

        self._pool = QtCore.QThreadPool.globalInstance()
        self._signals = _ThumbSignals()
        self._signals.loaded.connect(self._on_thumb_loaded)

    # -- query management ----------------------------------------------------
    def set_fetcher(self, fetch: Fetcher) -> None:
        """Point the model at a new query and load its first page."""
        self.beginResetModel()
        self._fetch = fetch
        self._rows = []
        self._cache.clear()
        self._inflight.clear()
        self._generation += 1  # invalidate in-flight decodes from the old query
        self._exhausted = False
        self.endResetModel()
        self._load_next_page()

    def _load_next_page(self) -> None:
        if self._fetch is None or self._exhausted:
            return
        page = self._fetch(len(self._rows), _PAGE_SIZE)
        if not page:
            self._exhausted = True
            return
        start = len(self._rows)
        self.beginInsertRows(QtCore.QModelIndex(), start, start + len(page) - 1)
        self._rows.extend(page)
        self.endInsertRows()
        if len(page) < _PAGE_SIZE:
            self._exhausted = True

    # -- zoom ----------------------------------------------------------------
    def set_tile_size(self, tile: int) -> None:
        self._tile = tile
        self._cache.clear()
        self._inflight.clear()
        self._generation += 1
        if self._rows:
            self.dataChanged.emit(
                self.index(0), self.index(len(self._rows) - 1),
                [QtCore.Qt.ItemDataRole.DecorationRole],
            )

    def tile_size(self) -> int:
        return self._tile

    def photo_ids(self) -> list[int]:
        return [row[0] for row in self._rows]

    # -- QAbstractListModel --------------------------------------------------
    def rowCount(self, parent: QtCore.QModelIndex = QtCore.QModelIndex()) -> int:  # noqa: N802
        return 0 if parent.isValid() else len(self._rows)

    def canFetchMore(self, parent: QtCore.QModelIndex = QtCore.QModelIndex()) -> bool:  # noqa: N802
        return not parent.isValid() and not self._exhausted

    def fetchMore(self, parent: QtCore.QModelIndex = QtCore.QModelIndex()) -> None:  # noqa: N802
        if not parent.isValid():
            self._load_next_page()

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

    # -- async thumbnail cache ----------------------------------------------
    def _thumbnail(self, row: int, thumb_path: Optional[str]) -> QtGui.QPixmap:
        if row in self._cache:
            self._cache.move_to_end(row)
            return self._cache[row]

        if thumb_path and row not in self._inflight and Path(thumb_path).exists():
            self._inflight.add(row)
            task = _ThumbTask(self._generation, row, thumb_path, self._tile, self._signals)
            self._pool.start(task)

        return _placeholder(self._tile)

    @QtCore.Slot(int, int, object)
    def _on_thumb_loaded(self, generation: int, row: int, image: QtGui.QImage) -> None:
        self._inflight.discard(row)
        if generation != self._generation or row >= len(self._rows):
            return  # result belongs to a superseded query / zoom
        if image.isNull():
            return
        pixmap = QtGui.QPixmap.fromImage(image)  # QPixmap must be built on the GUI thread
        self._cache[row] = pixmap
        if len(self._cache) > self._cache_size:
            self._cache.popitem(last=False)
        self.dataChanged.emit(
            self.index(row), self.index(row), [QtCore.Qt.ItemDataRole.DecorationRole]
        )


class PhotoGrid(QtWidgets.QListView):
    """Icon-mode grid view over a :class:`PhotoGridModel`."""

    photo_activated = QtCore.Signal(int)
    detect_faces_requested = QtCore.Signal(list)  # selected photo ids

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
        self.setSpacing(10)
        self.setWordWrap(False)
        self.verticalScrollBar().setSingleStep(28)
        self._apply_tile()

        self.doubleClicked.connect(self._on_activated)

    def _apply_tile(self) -> None:
        tile = self._model.tile_size()
        self.setIconSize(QtCore.QSize(tile, tile))
        self.setGridSize(QtCore.QSize(tile + 18, tile + 18))

    def set_tile_size(self, tile: int) -> None:
        tile = max(112, min(360, tile))
        self._model.set_tile_size(tile)
        self._apply_tile()

    def zoom(self, delta: int) -> None:
        self.set_tile_size(self._model.tile_size() + delta)

    def selected_photo_ids(self) -> list[int]:
        """Return the photo ids of the currently selected tiles."""
        ids: list[int] = []
        for index in self.selectedIndexes():
            photo_id = index.data(PHOTO_ID_ROLE)
            if photo_id is not None:
                ids.append(int(photo_id))
        return ids

    def contextMenuEvent(self, event: QtGui.QContextMenuEvent) -> None:  # noqa: N802
        ids = self.selected_photo_ids()
        menu = QtWidgets.QMenu(self)
        if ids:
            action = menu.addAction(f"Detect faces on {len(ids)} selected photo(s)")
            action.triggered.connect(lambda: self.detect_faces_requested.emit(ids))
        else:
            hint = menu.addAction("Select photos, then right-click to detect faces")
            hint.setEnabled(False)
        menu.exec(event.globalPos())

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
