"""Virtualized People grid (Model/View + async covers).

Replaces the eager approach (one `PersonCard` widget per person, each decoding
its cover synchronously) that made the People tab freeze on large libraries.
Here a `QListView` renders only visible items from a `QAbstractListModel`, and
cover images are decoded off the UI thread — the same technique the photo grid
uses. This keeps the tab switch instant regardless of how many people exist.
"""

from __future__ import annotations

from collections import OrderedDict
from pathlib import Path
from typing import Any, Optional

from PySide6 import QtCore, QtGui, QtWidgets

from viewer import theme

PERSON_ID_ROLE = int(QtCore.Qt.ItemDataRole.UserRole) + 1
_COVER = 96  # cover diameter in px


def _circular(image: QtGui.QImage, diameter: int) -> QtGui.QPixmap:
    """Return a circular pixmap of ``image`` cropped to ``diameter``."""
    scaled = image.scaled(
        diameter, diameter,
        QtCore.Qt.AspectRatioMode.KeepAspectRatioByExpanding,
        QtCore.Qt.TransformationMode.SmoothTransformation,
    )
    out = QtGui.QPixmap(diameter, diameter)
    out.fill(QtCore.Qt.GlobalColor.transparent)
    painter = QtGui.QPainter(out)
    painter.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing, True)
    clip = QtGui.QPainterPath()
    clip.addEllipse(0, 0, diameter, diameter)
    painter.setClipPath(clip)
    x = (scaled.width() - diameter) // 2
    y = (scaled.height() - diameter) // 2
    painter.drawImage(-x, -y, scaled)
    painter.end()
    return out


def _placeholder(diameter: int) -> QtGui.QPixmap:
    pm = QtGui.QPixmap(diameter, diameter)
    pm.fill(QtCore.Qt.GlobalColor.transparent)
    painter = QtGui.QPainter(pm)
    painter.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing, True)
    painter.setBrush(QtGui.QColor(theme.SURFACE_ALT))
    painter.setPen(QtCore.Qt.PenStyle.NoPen)
    painter.drawEllipse(0, 0, diameter, diameter)
    painter.setPen(QtGui.QColor(theme.TEXT_MUTED))
    painter.drawText(pm.rect(), QtCore.Qt.AlignmentFlag.AlignCenter, "☺")
    painter.end()
    return pm


class _CoverSignals(QtCore.QObject):
    loaded = QtCore.Signal(int, int, object)  # generation, row, QImage


class _CoverTask(QtCore.QRunnable):
    """Decode a person's cover crop off the GUI thread."""

    def __init__(self, generation: int, row: int, path: str, signals: _CoverSignals):
        super().__init__()
        self._generation = generation
        self._row = row
        self._path = path
        self._signals = signals

    def run(self) -> None:
        image = QtGui.QImage(self._path)  # QImage is safe off-thread
        self._signals.loaded.emit(self._generation, self._row, image)


class PeopleModel(QtCore.QAbstractListModel):
    """List model over person dicts with async circular covers."""

    def __init__(self) -> None:
        super().__init__()
        self._rows: list[dict[str, Any]] = []
        self._cache: "OrderedDict[int, QtGui.QPixmap]" = OrderedDict()
        self._inflight: set[int] = set()
        self._generation = 0
        self._pool = QtCore.QThreadPool.globalInstance()
        self._signals = _CoverSignals()
        self._signals.loaded.connect(self._on_cover_loaded)

    def set_people(self, people: list[dict[str, Any]]) -> None:
        self.beginResetModel()
        self._rows = people
        self._cache.clear()
        self._inflight.clear()
        self._generation += 1
        self.endResetModel()

    def person_id_at(self, row: int) -> Optional[int]:
        if 0 <= row < len(self._rows):
            return self._rows[row]["id"]
        return None

    def rowCount(self, parent: QtCore.QModelIndex = QtCore.QModelIndex()) -> int:  # noqa: N802
        return 0 if parent.isValid() else len(self._rows)

    def data(self, index: QtCore.QModelIndex, role: int = QtCore.Qt.ItemDataRole.DisplayRole):
        if not index.isValid() or not (0 <= index.row() < len(self._rows)):
            return None
        person = self._rows[index.row()]
        if role == PERSON_ID_ROLE:
            return person["id"]
        if role == QtCore.Qt.ItemDataRole.DisplayRole:
            name = person.get("display_name") or "Unknown"
            return f"{name}\n{person['face_count']} photos"
        if role == QtCore.Qt.ItemDataRole.TextAlignmentRole:
            return int(QtCore.Qt.AlignmentFlag.AlignHCenter | QtCore.Qt.AlignmentFlag.AlignTop)
        if role == QtCore.Qt.ItemDataRole.DecorationRole:
            return self._cover(index.row(), person.get("cover_path"))
        return None

    def _cover(self, row: int, cover_path: Optional[str]) -> QtGui.QPixmap:
        if row in self._cache:
            self._cache.move_to_end(row)
            return self._cache[row]
        if cover_path and row not in self._inflight and Path(cover_path).exists():
            self._inflight.add(row)
            self._pool.start(_CoverTask(self._generation, row, cover_path, self._signals))
        return _placeholder(_COVER)

    @QtCore.Slot(int, int, object)
    def _on_cover_loaded(self, generation: int, row: int, image: QtGui.QImage) -> None:
        self._inflight.discard(row)
        if generation != self._generation or row >= len(self._rows):
            return
        pixmap = _circular(image, _COVER) if not image.isNull() else _placeholder(_COVER)
        self._cache[row] = pixmap
        if len(self._cache) > 600:
            self._cache.popitem(last=False)
        idx = self.index(row)
        self.dataChanged.emit(idx, idx, [QtCore.Qt.ItemDataRole.DecorationRole])


class PeopleView(QtWidgets.QListView):
    """Icon-mode grid of people; emits :attr:`person_activated` with an id."""

    person_activated = QtCore.Signal(int)
    rename_requested = QtCore.Signal(int)  # right-click -> "Rename person…"

    def __init__(self, model: PeopleModel) -> None:
        super().__init__()
        self.setModel(model)
        self._model = model
        self.setViewMode(QtWidgets.QListView.ViewMode.IconMode)
        self.setResizeMode(QtWidgets.QListView.ResizeMode.Adjust)
        self.setMovement(QtWidgets.QListView.Movement.Static)
        self.setUniformItemSizes(True)
        self.setIconSize(QtCore.QSize(_COVER, _COVER))
        self.setGridSize(QtCore.QSize(150, 156))
        self.setSpacing(8)
        self.setWordWrap(True)
        self.setSelectionMode(QtWidgets.QAbstractItemView.SelectionMode.SingleSelection)
        self.setStyleSheet("QListView { background: transparent; border: none; }")
        self.clicked.connect(self._on_clicked)

    def _on_clicked(self, index: QtCore.QModelIndex) -> None:
        person_id = index.data(PERSON_ID_ROLE)
        if person_id is not None:
            self.person_activated.emit(int(person_id))

    def contextMenuEvent(self, event: QtGui.QContextMenuEvent) -> None:  # noqa: N802
        index = self.indexAt(event.pos())
        person_id = index.data(PERSON_ID_ROLE) if index.isValid() else None
        if person_id is None:
            return
        menu = QtWidgets.QMenu(self)
        rename = menu.addAction("Rename person…")
        rename.triggered.connect(lambda: self.rename_requested.emit(int(person_id)))
        open_action = menu.addAction("Open")
        open_action.triggered.connect(lambda: self.person_activated.emit(int(person_id)))
        menu.exec(event.globalPos())
