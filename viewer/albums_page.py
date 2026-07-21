"""Albums — manual, user-curated collections (complementing the AI's groups).

Two modes in one page:

* **List** — a grid of album cards (cover + name + count) and "New album".
* **Detail** — the album's photos in the standard virtualized grid, with
  rename, delete, and "remove from this album" (right-click). Photos are only
  ever *referenced*: removing a photo from an album, or deleting the album,
  never touches the photo itself.

Emits :attr:`photo_activated` so opening a photo uses the shared viewer.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Optional

from PySide6 import QtCore, QtGui, QtWidgets

from viewer import data, theme
from viewer.gallery import PhotoGrid, PhotoGridModel

_COVER = 168


def _cover_pixmap(album_id: int, thumb_path: Optional[str]) -> QtGui.QPixmap:
    if thumb_path and Path(thumb_path).exists():
        pm = QtGui.QPixmap(thumb_path)
        if not pm.isNull():
            return pm.scaled(_COVER, _COVER, QtCore.Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                             QtCore.Qt.TransformationMode.SmoothTransformation)
    pm = QtGui.QPixmap(_COVER, _COVER)
    pm.fill(QtCore.Qt.GlobalColor.transparent)
    painter = QtGui.QPainter(pm)
    painter.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing, True)
    top, bottom = theme.tile_colors(album_id * 3 + 7)
    grad = QtGui.QLinearGradient(0, 0, _COVER, _COVER)
    grad.setColorAt(0, top)
    grad.setColorAt(1, bottom)
    path = QtGui.QPainterPath()
    path.addRoundedRect(0, 0, _COVER, _COVER, theme.RADIUS_MD, theme.RADIUS_MD)
    painter.fillPath(path, grad)
    painter.end()
    return pm


class _AlbumCard(QtWidgets.QFrame):
    clicked = QtCore.Signal(int, str)  # album_id, name

    def __init__(self, album: dict[str, Any]) -> None:
        super().__init__()
        self.setObjectName("Card")
        self.setCursor(QtCore.Qt.CursorShape.PointingHandCursor)
        self._id, self._name = album["id"], album["name"]
        v = QtWidgets.QVBoxLayout(self)
        v.setContentsMargins(10, 10, 10, 12)
        v.setSpacing(6)
        cover = QtWidgets.QLabel()
        cover.setPixmap(_cover_pixmap(album["id"], album.get("cover_path")))
        cover.setFixedSize(_COVER, _COVER)
        v.addWidget(cover, 0, QtCore.Qt.AlignmentFlag.AlignHCenter)
        name = QtWidgets.QLabel(album["name"])
        name.setObjectName("H2")
        v.addWidget(name)
        count = QtWidgets.QLabel(
            f"{album['count']} photo{'s' if album['count'] != 1 else ''}")
        count.setObjectName("Muted")
        v.addWidget(count)

    def mousePressEvent(self, event) -> None:  # noqa: N802
        if event.button() == QtCore.Qt.MouseButton.LeftButton:
            self.clicked.emit(self._id, self._name)


class AlbumsPage(QtWidgets.QWidget):
    """List of albums and, on selection, one album's photos."""

    photo_activated = QtCore.Signal(int)

    def __init__(self) -> None:
        super().__init__()
        self._album_id: Optional[int] = None
        self._stack = QtWidgets.QStackedWidget()
        outer = QtWidgets.QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(self._stack)

        self._stack.addWidget(self._build_list())     # index 0
        self._stack.addWidget(self._build_detail())    # index 1

    # -- list view ------------------------------------------------------------

    def _build_list(self) -> QtWidgets.QWidget:
        page = QtWidgets.QWidget()
        v = QtWidgets.QVBoxLayout(page)
        v.setContentsMargins(24, 20, 24, 12)
        v.setSpacing(10)

        header = QtWidgets.QHBoxLayout()
        title = QtWidgets.QLabel("Albums")
        title.setObjectName("H1")
        header.addWidget(title)
        header.addStretch(1)
        new = QtWidgets.QPushButton("New album")
        new.setObjectName("Primary")
        new.clicked.connect(self._on_new_album)
        header.addWidget(new)
        v.addLayout(header)

        self._empty = QtWidgets.QLabel(
            "No albums yet. Create one, then right-click photos to add them.")
        self._empty.setObjectName("Muted")
        v.addWidget(self._empty)

        self._scroll = QtWidgets.QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setFrameShape(QtWidgets.QFrame.Shape.NoFrame)
        self._grid_host = QtWidgets.QWidget()
        self._cards = QtWidgets.QGridLayout(self._grid_host)
        self._cards.setHorizontalSpacing(14)
        self._cards.setVerticalSpacing(14)
        self._cards.setAlignment(QtCore.Qt.AlignmentFlag.AlignTop)
        self._scroll.setWidget(self._grid_host)
        v.addWidget(self._scroll, 1)
        return page

    # -- detail view ----------------------------------------------------------

    def _build_detail(self) -> QtWidgets.QWidget:
        page = QtWidgets.QWidget()
        v = QtWidgets.QVBoxLayout(page)
        v.setContentsMargins(24, 20, 24, 0)
        v.setSpacing(8)

        bar = QtWidgets.QHBoxLayout()
        back = QtWidgets.QPushButton("← Albums")
        back.clicked.connect(lambda: self._stack.setCurrentIndex(0))
        bar.addWidget(back)
        self._detail_title = QtWidgets.QLabel("")
        self._detail_title.setObjectName("H1")
        bar.addSpacing(8)
        bar.addWidget(self._detail_title)
        bar.addStretch(1)
        rename = QtWidgets.QPushButton("Rename")
        rename.clicked.connect(self._on_rename)
        delete = QtWidgets.QPushButton("Delete album")
        delete.clicked.connect(self._on_delete)
        bar.addWidget(rename)
        bar.addWidget(delete)
        v.addLayout(bar)

        self._model = PhotoGridModel()
        self._pgrid = PhotoGrid(self._model)
        self._pgrid.photo_activated.connect(self.photo_activated.emit)
        self._pgrid.remove_from_person_requested.connect(self._on_remove_photos)
        self._pgrid.set_remove_action("Remove from this album")
        v.addWidget(self._pgrid, 1)
        return page

    # -- refresh --------------------------------------------------------------

    def refresh(self) -> None:
        if self._album_id is not None and self._stack.currentIndex() == 1:
            self._open_album(self._album_id, self._detail_title.text())
        self._refresh_list()

    def _refresh_list(self) -> None:
        while self._cards.count():
            w = self._cards.takeAt(0).widget()
            if w is not None:
                w.setParent(None)
                w.deleteLater()
        albums = data.albums()
        self._empty.setVisible(not albums)
        for i, album in enumerate(albums):
            card = _AlbumCard(album)
            card.clicked.connect(self._open_album)
            self._cards.addWidget(card, i // 4, i % 4)

    def _open_album(self, album_id: int, name: str) -> None:
        self._album_id = album_id
        self._detail_title.setText(name)
        self._model.set_fetcher(
            lambda offset, limit: data.album_photos(album_id, limit, offset))
        self._stack.setCurrentIndex(1)

    def current_photo_ids(self) -> list[int]:
        return self._model.photo_ids()

    # -- actions --------------------------------------------------------------

    def _on_new_album(self) -> None:
        name, ok = QtWidgets.QInputDialog.getText(self, "New album", "Album name:")
        if ok and name.strip():
            data.create_album(name.strip())
            self._refresh_list()

    def _on_rename(self) -> None:
        if self._album_id is None:
            return
        name, ok = QtWidgets.QInputDialog.getText(
            self, "Rename album", "Album name:", text=self._detail_title.text())
        if ok and name.strip():
            data.rename_album(self._album_id, name.strip())
            self._detail_title.setText(name.strip())
            self._refresh_list()

    def _on_delete(self) -> None:
        if self._album_id is None:
            return
        if QtWidgets.QMessageBox.question(
            self, "Delete album",
            f"Delete “{self._detail_title.text()}”? Your photos are not affected.",
        ) != QtWidgets.QMessageBox.StandardButton.Yes:
            return
        data.delete_album(self._album_id)
        self._album_id = None
        self._refresh_list()
        self._stack.setCurrentIndex(0)

    def _on_remove_photos(self, photo_ids: list[int]) -> None:
        if self._album_id is None or not photo_ids:
            return
        data.remove_from_album(self._album_id, photo_ids)
        self._open_album(self._album_id, self._detail_title.text())
        self._refresh_list()
