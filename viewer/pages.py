"""Top-level pages shown in the main window's stacked content area.

Each page is self-contained and exposes a ``refresh()`` that (re)loads its data
from :mod:`viewer.data`. Pages never touch the database directly.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from PySide6 import QtCore, QtGui, QtWidgets

from viewer import data
from viewer.actions import ActionRunner
from viewer.appearance_strip import AppearanceStrip, SuggestionStrip
from viewer.gallery import PhotoGrid, PhotoGridModel
from viewer.merge_strip import MergeSuggestionStrip
from viewer.people_view import PeopleModel, PeopleView, _circular, _placeholder
from viewer.photo_strip import PhotoStrip
from viewer import theme


def _avatar(crop_path: Optional[str], size: int) -> QtGui.QPixmap:
    """A circular avatar from a face crop, or a neutral placeholder."""
    if crop_path and Path(crop_path).exists():
        image = QtGui.QImage(crop_path)
        if not image.isNull():
            return _circular(image, size)
    return _placeholder(size)


def _seen_line(profile: dict) -> str:
    """Human 'N photos · First seen … · Last seen …' summary."""
    parts = [f"{profile.get('photo_count', 0):,} photos"]
    first, last = profile.get("first_seen"), profile.get("last_seen")
    if first is not None:
        parts.append(f"First seen {first.strftime('%b %Y')}")
    if last is not None:
        parts.append(f"Last seen {last.strftime('%b %d, %Y')}")
    return "   ·   ".join(parts)


def _title(text: str) -> QtWidgets.QLabel:
    label = QtWidgets.QLabel(text)
    label.setObjectName("H1")
    return label


class _ClickCard(QtWidgets.QFrame):
    """A card that behaves like a button (whole surface clickable)."""

    clicked = QtCore.Signal()

    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("Card")
        self.setCursor(QtCore.Qt.CursorShape.PointingHandCursor)

    def mousePressEvent(self, event: QtGui.QMouseEvent) -> None:  # noqa: N802
        if event.button() == QtCore.Qt.MouseButton.LeftButton:
            self.clicked.emit()


class DashboardPage(QtWidgets.QWidget):
    """The activity center (PDD §6.1): what's happening, not raw statistics.

    A time-of-day greeting, an "AI needs your help" card, recent + on-this-day
    memory strips, library health and quick actions. Emits :attr:`navigate` to
    change page and :attr:`photo_activated` to open a photo.
    """

    navigate = QtCore.Signal(str)          # page key
    photo_activated = QtCore.Signal(int)
    import_requested = QtCore.Signal()
    reindex_requested = QtCore.Signal()

    def __init__(self) -> None:
        super().__init__()
        scroll = QtWidgets.QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QtWidgets.QFrame.Shape.NoFrame)
        page_layout = QtWidgets.QVBoxLayout(self)
        page_layout.setContentsMargins(0, 0, 0, 0)
        page_layout.addWidget(scroll)

        body = QtWidgets.QWidget()
        layout = QtWidgets.QVBoxLayout(body)
        layout.setContentsMargins(28, 24, 28, 24)
        layout.setSpacing(16)
        scroll.setWidget(body)

        self._greeting = QtWidgets.QLabel("Welcome back")
        self._greeting.setStyleSheet("font-size: 30px; font-weight: 700;")
        self._summary = QtWidgets.QLabel("")
        self._summary.setObjectName("Muted")
        layout.addWidget(self._greeting)
        layout.addWidget(self._summary)

        # --- top cards: Review · Health · Quick actions ---
        cards = QtWidgets.QHBoxLayout()
        cards.setSpacing(14)

        self._review_card = _ClickCard()
        self._review_card.clicked.connect(lambda: self.navigate.emit("review"))
        rc = QtWidgets.QVBoxLayout(self._review_card)
        rc.setContentsMargins(18, 16, 18, 16)
        self._review_title = QtWidgets.QLabel("AI needs your help")
        self._review_title.setObjectName("H2")
        self._review_detail = QtWidgets.QLabel("Nothing to review")
        self._review_detail.setObjectName("Muted")
        self._review_detail.setWordWrap(True)
        rc.addWidget(self._review_title)
        rc.addWidget(self._review_detail)
        rc.addStretch(1)
        cards.addWidget(self._review_card, 1)

        health = QtWidgets.QFrame()
        health.setObjectName("Card")
        hc = QtWidgets.QVBoxLayout(health)
        hc.setContentsMargins(18, 16, 18, 16)
        htitle = QtWidgets.QLabel("Library health")
        htitle.setObjectName("H2")
        self._health_gpu = QtWidgets.QLabel("—")
        self._health_gpu.setObjectName("Muted")
        self._health_kb = QtWidgets.QLabel("Knowledge base · Healthy")
        self._health_kb.setObjectName("Muted")
        self._health_index = QtWidgets.QLabel("—")
        self._health_index.setObjectName("Muted")
        hc.addWidget(htitle)
        for w in (self._health_gpu, self._health_kb, self._health_index):
            hc.addWidget(w)
        hc.addStretch(1)
        cards.addWidget(health, 1)

        actions = QtWidgets.QFrame()
        actions.setObjectName("Card")
        ac = QtWidgets.QVBoxLayout(actions)
        ac.setContentsMargins(18, 16, 18, 16)
        atitle = QtWidgets.QLabel("Quick actions")
        atitle.setObjectName("H2")
        ac.addWidget(atitle)
        row = QtWidgets.QHBoxLayout()
        import_btn = QtWidgets.QPushButton("Import")
        import_btn.setObjectName("Primary")
        import_btn.clicked.connect(self.import_requested.emit)
        search_btn = QtWidgets.QPushButton("Search")
        search_btn.clicked.connect(lambda: self.navigate.emit("search"))
        update_btn = QtWidgets.QPushButton("Update")
        update_btn.clicked.connect(self.reindex_requested.emit)
        for b in (import_btn, search_btn, update_btn):
            row.addWidget(b)
        row.addStretch(1)
        ac.addLayout(row)
        ac.addStretch(1)
        cards.addWidget(actions, 1)
        layout.addLayout(cards)

        # --- memory strips ---
        self._recent_title = QtWidgets.QLabel("Recently added")
        self._recent_title.setObjectName("H2")
        layout.addWidget(self._recent_title)
        self._recent = PhotoStrip()
        self._recent.photo_activated.connect(self.photo_activated.emit)
        layout.addWidget(self._recent)

        self._otd_title = QtWidgets.QLabel("On this day")
        self._otd_title.setObjectName("H2")
        layout.addWidget(self._otd_title)
        self._otd = PhotoStrip()
        self._otd.photo_activated.connect(self.photo_activated.emit)
        layout.addWidget(self._otd)

        self._empty = QtWidgets.QLabel(
            "Your library is empty — press Import to add your photos."
        )
        self._empty.setObjectName("Muted")
        layout.addWidget(self._empty)
        layout.addStretch(1)

    def current_photo_ids(self) -> list[int]:
        return [t._photo_id for t in self._recent._thumbs]

    def set_gpu_badge(self, badge: str) -> None:
        self._health_gpu.setText(badge.replace("GPU:", "AI ·").strip())

    def refresh(self) -> None:
        import datetime as _dt

        hour = _dt.datetime.now().hour
        self._greeting.setText(
            "Good morning" if hour < 12 else "Good afternoon" if hour < 18 else "Good evening"
        )
        stats = data.library_stats()
        photos = stats.get("photos", 0)
        self._summary.setText(
            f"{photos:,} photos · {stats.get('persons', 0):,} people · "
            f"{stats.get('faces', 0):,} faces"
        )
        self._empty.setVisible(photos == 0)

        review = data.review_count()
        if review:
            self._review_title.setText(f"AI needs your help  ·  {review}")
            self._review_detail.setText(
                f"{review} question(s) waiting — click to review.")
        else:
            self._review_title.setText("All caught up")
            self._review_detail.setText("Nothing needs your attention right now.")

        self._health_kb.setText("Knowledge base · Healthy" if photos else "Knowledge base · Empty")
        self._health_index.setText(f"{photos:,} photos indexed" if photos else "Nothing indexed yet")

        recent = data.recent_photos(12)
        self._recent.set_photos(recent)
        self._recent_title.setVisible(bool(recent))
        self._recent.setVisible(bool(recent))

        otd = data.on_this_day(12)
        self._otd.set_photos(otd)
        self._otd_title.setVisible(bool(otd))
        self._otd.setVisible(bool(otd))


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
        self._runner = ActionRunner(self)  # merges rebuild galleries: off-thread

        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(24, 20, 24, 12)
        layout.setSpacing(12)
        layout.addWidget(_title("People"))

        # "Same person?" — the merge scan's questions, answered in place.
        self._merge_strip = MergeSuggestionStrip()
        self._merge_strip.merge_requested.connect(self._on_merge_pair)
        self._merge_strip.reject_requested.connect(self._on_reject_pair)
        layout.addWidget(self._merge_strip)

        self._model = PeopleModel()
        self._view = PeopleView(self._model)
        self._view.person_activated.connect(self.person_selected.emit)
        self._view.rename_requested.connect(self._on_rename_person)
        layout.addWidget(self._view, 1)

        self._empty = QtWidgets.QLabel("No people yet — run face detection and clustering.")
        self._empty.setObjectName("Muted")
        layout.addWidget(self._empty)

    def refresh(self) -> None:
        people = data.persons()
        self._empty.setVisible(not people)
        self._model.set_people(people)
        self._merge_strip.set_pairs(data.merge_suggestions())

    # -- merge suggestions ---------------------------------------------------
    def _action_failed(self, message: str) -> None:
        QtWidgets.QMessageBox.warning(self, "Action failed", message)

    def _on_merge_pair(self, source_id: int, target_id: int) -> None:
        self._runner.run(
            lambda: data.merge_person_into(source_id, target_id),
            on_done=lambda _r: self._after_merge(target_id),
            on_error=self._action_failed,
        )

    def _after_merge(self, target_id: int) -> None:
        self.refresh()
        # The natural moment to name someone: right after confirming identity.
        person = next((p for p in data.persons() if p["id"] == target_id), None)
        if person is not None and not person.get("display_name"):
            self._prompt_rename(target_id)

    def _on_reject_pair(self, person_a: int, person_b: int) -> None:
        self._runner.run(
            lambda: data.reject_merge_suggestion(person_a, person_b),
            on_done=lambda _r: self.refresh(),
            on_error=self._action_failed,
        )

    # -- inline rename (right-click a person card) ---------------------------
    def _on_rename_person(self, person_id: int) -> None:
        self._prompt_rename(person_id)

    def _prompt_rename(self, person_id: int) -> None:
        person = next((p for p in data.persons() if p["id"] == person_id), None)
        current = (person or {}).get("display_name") or ""
        name, ok = QtWidgets.QInputDialog.getText(
            self, "Name person", "Who is this?", text=current
        )
        if ok:
            data.rename_person(person_id, name)
            self.refresh()


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
        # Corrections rebuild galleries (seconds on a large person) — they run
        # on this runner, never on the UI thread.
        self._runner = ActionRunner(self)

        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(16, 12, 16, 0)
        layout.setSpacing(10)

        # Top row: back + actions.
        top = QtWidgets.QHBoxLayout()
        back = QtWidgets.QPushButton("←  People")
        back.clicked.connect(self.back_requested.emit)
        rename_btn = QtWidgets.QPushButton("Rename")
        rename_btn.clicked.connect(self._on_rename)
        merge_btn = QtWidgets.QPushButton("Merge…")
        merge_btn.clicked.connect(self._on_merge)
        delete_btn = QtWidgets.QPushButton("Delete")
        delete_btn.clicked.connect(self._on_delete)
        top.addWidget(back)
        top.addStretch(1)
        top.addWidget(rename_btn)
        top.addWidget(merge_btn)
        top.addWidget(delete_btn)
        layout.addLayout(top)

        # Profile header: avatar + name + seen line + appears-with.
        header = QtWidgets.QHBoxLayout()
        header.setSpacing(16)
        self._avatar = QtWidgets.QLabel()
        self._avatar.setFixedSize(72, 72)
        header.addWidget(self._avatar, 0, QtCore.Qt.AlignmentFlag.AlignTop)

        ident = QtWidgets.QVBoxLayout()
        ident.setSpacing(4)
        self._name = QtWidgets.QLabel("Person")
        self._name.setObjectName("H1")
        self._name.setCursor(QtCore.Qt.CursorShape.PointingHandCursor)
        self._name.setToolTip("Click to rename")
        self._name.mousePressEvent = lambda _e: self._on_rename()  # click name to rename
        self._subtitle = QtWidgets.QLabel("")
        self._subtitle.setObjectName("Muted")
        ident.addWidget(self._name)
        ident.addWidget(self._subtitle)

        aw_row = QtWidgets.QHBoxLayout()
        aw_row.setSpacing(6)
        self._aw_label = QtWidgets.QLabel("Appears with")
        self._aw_label.setObjectName("Muted")
        aw_row.addWidget(self._aw_label)
        self._aw_container = QtWidgets.QHBoxLayout()
        self._aw_container.setSpacing(6)
        aw_row.addLayout(self._aw_container)
        aw_row.addStretch(1)
        ident.addLayout(aw_row)

        header.addLayout(ident, 1)
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

        profile = data.person_profile(person_id)
        self._avatar.setPixmap(_avatar(profile.get("cover_path"), 72))
        self._subtitle.setText(_seen_line(profile))
        self._populate_appears_with(person_id)

        self._appearances.set_representatives(data.person_representatives(person_id))
        self._suggestions.set_suggestions(
            data.suggestions_for_person(person_id), name or "Unknown"
        )
        self._model.set_fetcher(
            lambda offset, limit: data.photo_grid(
                limit=limit, offset=offset, person_id=person_id
            )
        )

    def _populate_appears_with(self, person_id: int) -> None:
        while self._aw_container.count():
            w = self._aw_container.takeAt(0).widget()
            if w is not None:
                w.setParent(None)
                w.deleteLater()
        companions = data.appears_with(person_id, limit=6)
        self._aw_label.setVisible(bool(companions))
        for person in companions:
            chip = QtWidgets.QToolButton()
            chip.setToolButtonStyle(QtCore.Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
            chip.setAutoRaise(True)
            chip.setCursor(QtCore.Qt.CursorShape.PointingHandCursor)
            chip.setIcon(QtGui.QIcon(_avatar(person.get("crop_path"), 24)))
            chip.setIconSize(QtCore.QSize(24, 24))
            chip.setText(" " + (person.get("display_name") or "Unknown"))
            chip.clicked.connect(lambda _c=False, pid=person["id"]: self.open_person_requested.emit(pid))
            self._aw_container.addWidget(chip)

    def _reload_person(self) -> None:
        if self._person_id is not None:
            who = self._name.text()
            self.show_person(self._person_id, None if who == "Unknown" else who)

    # -- corrections (gallery-rebuilding writes; run off the UI thread) ------
    def _run_correction(self, fn, after) -> None:
        """Run a correction on the background runner; refresh (or fail) on GUI.

        ``after(result)`` runs on the GUI thread once the write committed.
        A second correction while one is in flight is ignored (single-flight).
        """
        self._runner.run(fn, on_done=after, on_error=self._action_failed)

    def _action_failed(self, message: str) -> None:
        QtWidgets.QMessageBox.warning(self, "Action failed", message)

    def _after_change(self, _result: object = None, back_if_empty: bool = True) -> None:
        """Standard post-correction refresh: notify, reload, back out if emptied."""
        self.person_changed.emit()
        self._reload_person()
        if back_if_empty and not self._model.photo_ids():
            self.back_requested.emit()  # person emptied out (and was removed)

    def _on_confirm_suggestion(self, face_id: int) -> None:
        if self._person_id is None:
            return
        person_id = self._person_id
        self._run_correction(
            lambda: data.confirm_suggestion(face_id, person_id), self._after_change
        )

    def _on_reject_suggestion(self, face_id: int) -> None:
        if self._person_id is None:
            return
        person_id = self._person_id
        self._run_correction(
            lambda: data.reject_suggestion(face_id, person_id),
            lambda _r: self._reload_person(),
        )

    def _on_reject_representative(self, face_id: int) -> None:
        """User dropped one learned appearance from the person."""
        if self._person_id is None:
            return
        person_id = self._person_id
        self._run_correction(
            lambda: data.reject_representative(person_id, face_id), self._after_change
        )

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
        person_id = self._person_id
        self._run_correction(
            lambda: data.remove_faces_from_person(person_id, photo_ids),
            self._after_change,
        )

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
        source_id = self._person_id
        target_id = target["id"]

        def _after_merge(_r: object) -> None:
            self.person_changed.emit()
            self.open_person_requested.emit(target_id)  # show the merged result

        # Merging rebuilds the target's gallery — off the UI thread.
        self._run_correction(lambda: data.merge_person_into(source_id, target_id), _after_merge)
