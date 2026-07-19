"""Top-level pages shown in the main window's stacked content area.

Each page is self-contained and exposes a ``refresh()`` that (re)loads its data
from :mod:`viewer.data`. Pages never touch the database directly.
"""

from __future__ import annotations

from typing import Optional

from PySide6 import QtCore, QtWidgets

from viewer import data
from viewer.appearance_strip import AppearanceStrip, SuggestionStrip
from viewer.components import StatCard, _human_bytes
from viewer.gallery import PhotoGrid, PhotoGridModel
from viewer.people_view import PeopleModel, PeopleView
from viewer import theme


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
    detect_faces_requested = QtCore.Signal(list)
    find_similar_requested = QtCore.Signal(int)

    def __init__(self, person_id: Optional[int] = None) -> None:
        super().__init__()
        self._person_id = person_id
        self._search: Optional[str] = None

        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self._model = PhotoGridModel()
        self._grid = PhotoGrid(self._model)
        self._grid.photo_activated.connect(self.photo_activated.emit)
        self._grid.detect_faces_requested.connect(self.detect_faces_requested.emit)
        self._grid.find_similar_requested.connect(self.find_similar_requested.emit)
        layout.addWidget(self._grid)

        # Debounce search so a full reload doesn't run on every keystroke.
        self._search_timer = QtCore.QTimer(self)
        self._search_timer.setSingleShot(True)
        self._search_timer.setInterval(250)
        self._search_timer.timeout.connect(self._reload)

    def set_search(self, term: Optional[str]) -> None:
        self._search = term or None
        self._search_timer.start()

    def zoom(self, delta: int) -> None:
        self._grid.zoom(delta)

    def set_tile_size(self, tile: int) -> None:
        self._grid.set_tile_size(tile)

    def tile_size(self) -> int:
        return self._model.tile_size()

    def current_photo_ids(self) -> list[int]:
        return self._model.photo_ids()

    def _reload(self) -> None:
        person = self._person_id
        search = self._search
        self._model.set_fetcher(
            lambda offset, limit: data.photo_grid(
                limit=limit, offset=offset, person_id=person, search=search
            )
        )

    def refresh(self) -> None:
        self._reload()


class PeoplePage(QtWidgets.QWidget):
    """A virtualized grid of people. Emits :attr:`person_selected`."""

    person_selected = QtCore.Signal(int)

    def __init__(self) -> None:
        super().__init__()
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(24, 20, 24, 12)
        layout.setSpacing(12)
        layout.addWidget(_title("People"))

        self._model = PeopleModel()
        self._view = PeopleView(self._model)
        self._view.person_activated.connect(self.person_selected.emit)
        layout.addWidget(self._view, 1)

        self._empty = QtWidgets.QLabel("No people yet — run face detection and clustering.")
        self._empty.setObjectName("Muted")
        layout.addWidget(self._empty)

    def refresh(self) -> None:
        people = data.persons()
        self._empty.setVisible(not people)
        self._model.set_people(people)


class PersonDetailPage(QtWidgets.QWidget):
    """Photos for one person, with a name header and rename/merge/delete."""

    back_requested = QtCore.Signal()
    photo_activated = QtCore.Signal(int)
    detect_faces_requested = QtCore.Signal(list)
    find_similar_requested = QtCore.Signal(int)
    person_changed = QtCore.Signal()          # people list needs refreshing
    open_person_requested = QtCore.Signal(int)  # navigate to another person

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

        rename_btn = QtWidgets.QPushButton("Rename")
        rename_btn.clicked.connect(self._on_rename)
        merge_btn = QtWidgets.QPushButton("Merge…")
        merge_btn.clicked.connect(self._on_merge)
        delete_btn = QtWidgets.QPushButton("Delete")
        delete_btn.clicked.connect(self._on_delete)

        header.addWidget(back)
        header.addSpacing(10)
        header.addWidget(self._name)
        header.addStretch(1)
        header.addWidget(rename_btn)
        header.addWidget(merge_btn)
        header.addWidget(delete_btn)
        layout.addLayout(header)

        self._model = PhotoGridModel()
        self._grid = PhotoGrid(self._model)
        self._grid.photo_activated.connect(self.photo_activated.emit)
        self._grid.detect_faces_requested.connect(self.detect_faces_requested.emit)
        self._grid.find_similar_requested.connect(self.find_similar_requested.emit)
        self._grid.remove_from_person_requested.connect(self._on_remove_from_person)

        self._suggestions = SuggestionStrip()
        self._suggestions.confirmed.connect(self._on_confirm_suggestion)
        self._suggestions.rejected.connect(self._on_reject_suggestion)
        layout.addWidget(self._suggestions)

        self._appearances = AppearanceStrip()
        self._appearances.representative_rejected.connect(self._on_reject_representative)
        layout.addWidget(self._appearances)

        layout.addWidget(self._grid, 1)

    def current_photo_ids(self) -> list[int]:
        return self._model.photo_ids()

    def show_person(self, person_id: int, name: Optional[str]) -> None:
        self._person_id = person_id
        self._name.setText(name or "Unknown")
        self._grid.set_person_context(name or "")
        self._appearances.set_representatives(data.person_representatives(person_id))
        self._suggestions.set_suggestions(
            data.suggestions_for_person(person_id), name or "Unknown"
        )
        self._model.set_fetcher(
            lambda offset, limit: data.photo_grid(
                limit=limit, offset=offset, person_id=person_id
            )
        )

    def _reload_person(self) -> None:
        if self._person_id is not None:
            who = self._name.text()
            self.show_person(self._person_id, None if who == "Unknown" else who)

    def _on_confirm_suggestion(self, face_id: int) -> None:
        if self._person_id is None:
            return
        data.confirm_suggestion(face_id, self._person_id)
        self.person_changed.emit()
        self._reload_person()

    def _on_reject_suggestion(self, face_id: int) -> None:
        if self._person_id is None:
            return
        data.reject_suggestion(face_id, self._person_id)
        self._reload_person()

    def _on_reject_representative(self, face_id: int) -> None:
        """User dropped one learned appearance from the person."""
        if self._person_id is None:
            return
        who = self._name.text()
        remaining = data.reject_representative(self._person_id, face_id)
        self.person_changed.emit()
        if remaining:
            self.show_person(self._person_id, None if who == "Unknown" else who)
        else:
            self.back_requested.emit()  # person emptied out

    def _on_remove_from_person(self, photo_ids: list[int]) -> None:
        """User says these photos are not this person: detach + remember."""
        if self._person_id is None or not photo_ids:
            return
        who = self._name.text()
        reply = QtWidgets.QMessageBox.question(
            self, "Remove from person",
            f"Remove {len(photo_ids)} photo(s) from {who}? "
            "PhotoSphere will remember this and won't re-assign them here.",
        )
        if reply != QtWidgets.QMessageBox.StandardButton.Yes:
            return
        moved = data.remove_faces_from_person(self._person_id, photo_ids)
        if not moved:
            return
        self.person_changed.emit()
        # Reload; if the person has no photos left (it was removed), go back.
        self.show_person(self._person_id, None if who == "Unknown" else who)
        if not self._model.photo_ids():
            self.back_requested.emit()

    # -- editing -------------------------------------------------------------
    def _on_rename(self) -> None:
        if self._person_id is None:
            return
        current = self._name.text() if self._name.text() != "Unknown" else ""
        name, ok = QtWidgets.QInputDialog.getText(
            self, "Rename person", "Name:", text=current
        )
        if ok:
            data.rename_person(self._person_id, name)
            self._name.setText(name.strip() or "Unknown")
            self.person_changed.emit()

    def _on_delete(self) -> None:
        if self._person_id is None:
            return
        reply = QtWidgets.QMessageBox.question(
            self, "Delete person",
            "Remove this person group? The photos and faces are kept — only the "
            "grouping is removed.",
        )
        if reply == QtWidgets.QMessageBox.StandardButton.Yes:
            data.delete_person(self._person_id)
            self.person_changed.emit()
            self.back_requested.emit()

    def _on_merge(self) -> None:
        if self._person_id is None:
            return
        others = [p for p in data.persons() if p["id"] != self._person_id]
        if not others:
            QtWidgets.QMessageBox.information(self, "Merge", "No other people to merge into.")
            return

        labels = [
            f"{p['display_name'] or 'Unknown'}  ({p['face_count']} photos)" for p in others
        ]
        choice, ok = QtWidgets.QInputDialog.getItem(
            self, "Merge person", "Merge this person into:", labels, editable=False
        )
        if not ok:
            return
        target = others[labels.index(choice)]
        data.merge_person_into(self._person_id, target["id"])
        self.person_changed.emit()
        self.open_person_requested.emit(target["id"])  # show the merged result
