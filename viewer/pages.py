"""Top-level pages shown in the main window's stacked content area.

Each page is self-contained and exposes a ``refresh()`` that (re)loads its data
from :mod:`viewer.data`. Pages never touch the database directly.
"""

from __future__ import annotations

from typing import Optional

from PySide6 import QtCore, QtWidgets

from viewer import data
from viewer.components import PersonCard, StatCard, _human_bytes
from viewer.flow_layout import FlowLayout
from viewer.gallery import PhotoGrid, PhotoGridModel
from viewer import theme

# How many photo rows to load into a grid at once. Rows are light (ids + paths);
# thumbnails load lazily. Paged/infinite loading is a future refinement.
_GRID_PAGE = 100_000


def _title(text: str) -> QtWidgets.QLabel:
    label = QtWidgets.QLabel(text)
    label.setObjectName("H1")
    return label


class DashboardPage(QtWidgets.QWidget):
    """Landing page: headline stats and recent activity."""

    def __init__(self) -> None:
        super().__init__()
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(24, 20, 24, 20)
        layout.setSpacing(16)

        layout.addWidget(_title("Dashboard"))

        cards = QtWidgets.QHBoxLayout()
        cards.setSpacing(14)
        self._photos = StatCard("Indexed Photos", accent=theme.PRIMARY)
        self._faces = StatCard("Faces Found", accent=theme.ACCENT)
        self._people = StatCard("People", accent=theme.PRIMARY)
        self._storage = StatCard("Storage Used", accent=theme.WARNING)
        for card in (self._photos, self._faces, self._people, self._storage):
            cards.addWidget(card)
        layout.addLayout(cards)

        activity_title = QtWidgets.QLabel("Recent Activity")
        activity_title.setObjectName("H2")
        layout.addWidget(activity_title)

        self._activity = QtWidgets.QListWidget()
        self._activity.setObjectName("Card")
        layout.addWidget(self._activity, 1)

    def refresh(self) -> None:
        stats = data.library_stats()
        self._photos.set_value(f"{stats['photos']:,}")
        self._faces.set_value(f"{stats['faces']:,}")
        self._people.set_value(f"{stats['persons']:,}")
        self._storage.set_value(_human_bytes(stats["storage_bytes"]))

        self._activity.clear()
        runs = data.recent_runs(8)
        if not runs:
            self._activity.addItem("No scans yet — use Import Folder to add photos.")
        for run in runs:
            when = run["started_at"].strftime("%Y-%m-%d %H:%M") if run["started_at"] else "—"
            self._activity.addItem(
                f"{when}   {run['root_path']}   "
                f"(+{run['processed']} new, {run['duplicates']} dup, {run['errors']} err)"
            )


class GalleryPage(QtWidgets.QWidget):
    """The photo grid. Emits :attr:`photo_activated` with a photo id."""

    photo_activated = QtCore.Signal(int)

    def __init__(self, person_id: Optional[int] = None) -> None:
        super().__init__()
        self._person_id = person_id
        self._search: Optional[str] = None

        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self._model = PhotoGridModel(tile=160)
        self._grid = PhotoGrid(self._model)
        self._grid.photo_activated.connect(self.photo_activated.emit)
        layout.addWidget(self._grid)

    def set_search(self, term: Optional[str]) -> None:
        self._search = term or None
        self.refresh()

    def zoom(self, delta: int) -> None:
        self._grid.zoom(delta)

    def current_photo_ids(self) -> list[int]:
        return self._model.photo_ids()

    def refresh(self) -> None:
        rows = data.photo_grid(
            limit=_GRID_PAGE, person_id=self._person_id, search=self._search
        )
        self._model.set_rows(rows)


class PeoplePage(QtWidgets.QWidget):
    """A reflowing grid of person cards. Emits :attr:`person_selected`."""

    person_selected = QtCore.Signal(int)

    def __init__(self) -> None:
        super().__init__()
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(24, 20, 24, 12)
        layout.setSpacing(12)
        layout.addWidget(_title("People"))

        self._scroll = QtWidgets.QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setFrameShape(QtWidgets.QFrame.Shape.NoFrame)
        self._container = QtWidgets.QWidget()
        self._flow = FlowLayout(margin=4, spacing=14)
        self._container.setLayout(self._flow)
        self._scroll.setWidget(self._container)
        layout.addWidget(self._scroll, 1)

        self._empty = QtWidgets.QLabel("No people yet — run face detection and clustering.")
        self._empty.setObjectName("Muted")
        layout.addWidget(self._empty)

    def refresh(self) -> None:
        # Clear existing cards.
        while self._flow.count():
            item = self._flow.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

        people = data.persons()
        self._empty.setVisible(not people)
        for person in people:
            card = PersonCard(person)
            card.clicked.connect(self.person_selected.emit)
            self._flow.addWidget(card)


class PersonDetailPage(QtWidgets.QWidget):
    """Photos for one person, with a back button and name header."""

    back_requested = QtCore.Signal()
    photo_activated = QtCore.Signal(int)

    def __init__(self) -> None:
        super().__init__()
        self._person_id: Optional[int] = None

        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(16, 12, 16, 0)
        layout.setSpacing(10)

        header = QtWidgets.QHBoxLayout()
        back = QtWidgets.QPushButton("←  People")
        back.clicked.connect(self.back_requested.emit)
        self._name = QtWidgets.QLabel("Person")
        self._name.setObjectName("H1")
        header.addWidget(back)
        header.addSpacing(10)
        header.addWidget(self._name)
        header.addStretch(1)
        layout.addLayout(header)

        self._model = PhotoGridModel(tile=160)
        self._grid = PhotoGrid(self._model)
        self._grid.photo_activated.connect(self.photo_activated.emit)
        layout.addWidget(self._grid, 1)

    def current_photo_ids(self) -> list[int]:
        return self._model.photo_ids()

    def show_person(self, person_id: int, name: Optional[str]) -> None:
        self._person_id = person_id
        self._name.setText(name or "Unknown")
        rows = data.photo_grid(limit=_GRID_PAGE, person_id=person_id)
        self._model.set_rows(rows)
