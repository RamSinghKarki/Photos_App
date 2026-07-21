"""AI Review center — the one place the app asks for a human verdict (PDD §6.3).

Everything the recognizer is unsure about collects here as a queue of questions,
grouped by kind, each laid out as **evidence on the left, verdict on the right**:

* **Same person?** — two profiles the merge scan thinks are one person. Merge
  keeps the named/larger profile and re-curates it; "Not the same" is remembered
  forever so the pair is never asked (or auto-merged) again.
* **Is this <name>?** — an ungrouped face the recognizer thinks belongs to a
  known person. "Yes" teaches the profile; "No" is remembered so the face is
  never re-offered.

Writes re-curate galleries (seconds on a large person), so they run off the UI
thread via :class:`~viewer.actions.ActionRunner`; the page refreshes and emits
:attr:`changed` when one lands, so review badges elsewhere stay in step.
"""

from __future__ import annotations

from typing import Any, Optional

from PySide6 import QtCore, QtWidgets

from viewer import data
from viewer.actions import ActionRunner
from viewer.appearance_strip import _rounded_square
from viewer.components import elevate

_THUMB = 60


class _MergeRow(QtWidgets.QFrame):
    """One 'Same person?' pair: two covers + names on the left, verdict right."""

    merge_requested = QtCore.Signal(int, int)   # (source, target)
    reject_requested = QtCore.Signal(int, int)  # (person_a, person_b)

    def __init__(self, pair: dict[str, Any]) -> None:
        super().__init__()
        self.setObjectName("Card")
        elevate(self, blur=16, y=3, alpha=55)
        a, b = int(pair["person_a"]), int(pair["person_b"])
        row = QtWidgets.QHBoxLayout(self)
        row.setContentsMargins(12, 10, 12, 10)
        row.setSpacing(12)

        for cover_key in ("cover_a", "cover_b"):
            face = QtWidgets.QLabel()
            face.setPixmap(_rounded_square(pair.get(cover_key), _THUMB))
            face.setFixedSize(_THUMB, _THUMB)
            row.addWidget(face)

        name_a = pair.get("name_a") or "Unknown"
        name_b = pair.get("name_b") or "Unknown"
        text = QtWidgets.QLabel(
            f"<b>{name_a}</b> ({pair['count_a']}) &nbsp;·&nbsp; "
            f"<b>{name_b}</b> ({pair['count_b']})"
        )
        row.addWidget(text)
        score = QtWidgets.QLabel(f"match {pair['score']:.2f}")
        score.setObjectName("Pill")
        row.addWidget(score)
        row.addStretch(1)

        # Merge keeps the named person; if both/neither are named, the larger.
        if pair.get("name_a") and not pair.get("name_b"):
            source, target = b, a
        elif pair.get("name_b") and not pair.get("name_a"):
            source, target = a, b
        else:
            source, target = (a, b) if pair["count_a"] <= pair["count_b"] else (b, a)

        merge = QtWidgets.QPushButton("Merge")
        merge.setObjectName("Primary")
        merge.setToolTip("These are the same person — combine the profiles")
        merge.clicked.connect(lambda: self.merge_requested.emit(source, target))
        keep = QtWidgets.QPushButton("Not the same")
        keep.setToolTip("Keep them separate and never ask about this pair again")
        keep.clicked.connect(lambda: self.reject_requested.emit(a, b))
        self._buttons = (merge, keep)
        row.addWidget(merge)
        row.addWidget(keep)

    def freeze(self) -> None:
        for btn in self._buttons:
            btn.setEnabled(False)


class _FaceRow(QtWidgets.QFrame):
    """One 'Is this <name>?' suggestion: candidate + reference, then Yes / No."""

    confirmed = QtCore.Signal(int, int)  # (face_id, person_id)
    rejected = QtCore.Signal(int, int)   # (face_id, person_id)

    def __init__(self, sug: dict[str, Any]) -> None:
        super().__init__()
        self.setObjectName("Card")
        elevate(self, blur=16, y=3, alpha=55)
        face_id, person_id = int(sug["face_id"]), int(sug["person_id"])
        name = sug.get("name") or "this person"
        row = QtWidgets.QHBoxLayout(self)
        row.setContentsMargins(12, 10, 12, 10)
        row.setSpacing(12)

        candidate = QtWidgets.QLabel()
        candidate.setPixmap(_rounded_square(sug.get("crop_path"), _THUMB))
        candidate.setFixedSize(_THUMB, _THUMB)
        row.addWidget(candidate)

        arrow = QtWidgets.QLabel("→")
        arrow.setObjectName("Muted")
        row.addWidget(arrow)

        reference = QtWidgets.QLabel()
        reference.setPixmap(_rounded_square(sug.get("cover_path"), _THUMB))
        reference.setFixedSize(_THUMB, _THUMB)
        row.addWidget(reference)

        text = QtWidgets.QLabel(f"Is this <b>{name}</b>?")
        row.addWidget(text)
        score = QtWidgets.QLabel(f"{sug['score']:.2f}")
        score.setObjectName("Pill")
        row.addWidget(score)
        row.addStretch(1)

        yes = QtWidgets.QPushButton("Yes")
        yes.setObjectName("Primary")
        yes.clicked.connect(lambda: self.confirmed.emit(face_id, person_id))
        no = QtWidgets.QPushButton("No")
        no.clicked.connect(lambda: self.rejected.emit(face_id, person_id))
        self._buttons = (yes, no)
        row.addWidget(yes)
        row.addWidget(no)

    def freeze(self) -> None:
        for btn in self._buttons:
            btn.setEnabled(False)


class ReviewPage(QtWidgets.QWidget):
    """A categorized queue of the recognizer's open questions."""

    changed = QtCore.Signal()  # a verdict landed; refresh badges elsewhere

    def __init__(self) -> None:
        super().__init__()
        self._runner = ActionRunner(self)

        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(24, 20, 24, 12)
        layout.setSpacing(8)

        title = QtWidgets.QLabel("Review")
        title.setObjectName("H1")
        layout.addWidget(title)
        self._subtitle = QtWidgets.QLabel("")
        self._subtitle.setObjectName("Muted")
        layout.addWidget(self._subtitle)

        # Filter chips: All / Same person? / Is this…? (counts filled on refresh).
        chip_row = QtWidgets.QHBoxLayout()
        chip_row.setSpacing(8)
        self._chips: dict[str, QtWidgets.QPushButton] = {}
        for key, label in (("all", "All"), ("merges", "Same person?"), ("faces", "Is this…?")):
            chip = QtWidgets.QPushButton(label)
            chip.setObjectName("FilterChip")
            chip.setCheckable(True)
            chip.setCursor(QtCore.Qt.CursorShape.PointingHandCursor)
            chip.clicked.connect(lambda _=False, k=key: self._set_filter(k))
            self._chips[key] = chip
            chip_row.addWidget(chip)
        chip_row.addStretch(1)
        layout.addLayout(chip_row)
        self._filter = "all"
        self._chips["all"].setChecked(True)

        self._empty = QtWidgets.QLabel(
            "✓  All caught up — nothing needs your attention right now."
        )
        self._empty.setObjectName("Muted")
        self._empty.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self._empty)

        # Scrollable stack of the two question sections.
        self._scroll = QtWidgets.QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setFrameShape(QtWidgets.QFrame.Shape.NoFrame)
        self._body = QtWidgets.QWidget()
        self._body_layout = QtWidgets.QVBoxLayout(self._body)
        self._body_layout.setContentsMargins(0, 8, 4, 0)
        self._body_layout.setSpacing(8)
        self._body_layout.addStretch(1)
        self._scroll.setWidget(self._body)
        layout.addWidget(self._scroll, 1)

        # Keyboard: Y / N answer the first open question (answers teach recognition).
        self._hint = QtWidgets.QLabel("Keyboard: Y yes · N no — answers teach recognition.")
        self._hint.setObjectName("Muted")
        layout.addWidget(self._hint)
        self.setFocusPolicy(QtCore.Qt.FocusPolicy.StrongFocus)

    # -- refresh --------------------------------------------------------------

    def _set_filter(self, key: str) -> None:
        self._filter = key
        for k, chip in self._chips.items():
            chip.setChecked(k == key)
        self.refresh()

    def refresh(self) -> None:
        merges = data.merge_suggestions()
        faces = data.all_suggestions()
        self._chips["all"].setText(f"All ({len(merges) + len(faces)})")
        self._chips["merges"].setText(f"Same person? ({len(merges)})")
        self._chips["faces"].setText(f"Is this…? ({len(faces)})")
        if self._filter == "merges":
            faces = []
        elif self._filter == "faces":
            merges = []
        self._first_question: Optional[tuple] = None
        if merges:
            p = merges[0]
            self._first_question = ("merge", p)
        elif faces:
            s = faces[0]
            self._first_question = ("face", s)
        self._rebuild(merges, faces)

    def keyPressEvent(self, event) -> None:  # noqa: N802
        key = event.key()
        if self._first_question and key in (QtCore.Qt.Key.Key_Y, QtCore.Qt.Key.Key_N):
            kind, item = self._first_question
            yes = key == QtCore.Qt.Key.Key_Y
            if kind == "face":
                fid, pid = int(item["face_id"]), int(item["person_id"])
                self._on_confirm_face(fid, pid) if yes else self._on_reject_face(fid, pid)
            else:
                a, b = int(item["person_a"]), int(item["person_b"])
                if yes:
                    # Same keep-the-named/larger rule the row's Merge button uses.
                    if item.get("name_a") and not item.get("name_b"):
                        self._on_merge(b, a)
                    elif item.get("name_b") and not item.get("name_a"):
                        self._on_merge(a, b)
                    else:
                        s, t = (a, b) if item["count_a"] <= item["count_b"] else (b, a)
                        self._on_merge(s, t)
                else:
                    self._on_reject_pair(a, b)
            return
        super().keyPressEvent(event)

    def _rebuild(self, merges: list[dict], faces: list[dict]) -> None:
        self._clear_body()
        total = len(merges) + len(faces)
        has_any = total > 0
        self._hint.setVisible(has_any)
        self._empty.setVisible(not has_any)
        self._scroll.setVisible(has_any)
        self._subtitle.setText(
            f"{total} question{'s' if total != 1 else ''} waiting" if has_any
            else "The app only asks when it isn't sure."
        )

        if merges:
            self._add_heading(f"Same person?  ({len(merges)})")
            for pair in merges:
                card = _MergeRow(pair)
                card.merge_requested.connect(self._on_merge)
                card.reject_requested.connect(self._on_reject_pair)
                self._insert(card)
        if faces:
            self._add_heading(f"Is this the right person?  ({len(faces)})")
            for sug in faces:
                card = _FaceRow(sug)
                card.confirmed.connect(self._on_confirm_face)
                card.rejected.connect(self._on_reject_face)
                self._insert(card)

    def _clear_body(self) -> None:
        while self._body_layout.count() > 1:  # keep the trailing stretch
            w = self._body_layout.takeAt(0).widget()
            if w is not None:
                w.setParent(None)
                w.deleteLater()

    def _add_heading(self, text: str) -> None:
        heading = QtWidgets.QLabel(text)
        heading.setObjectName("H2")
        self._insert(heading)

    def _insert(self, widget: QtWidgets.QWidget) -> None:
        self._body_layout.insertWidget(self._body_layout.count() - 1, widget)

    # -- actions (off the UI thread) ------------------------------------------

    def _run(self, sender: QtWidgets.QWidget, fn) -> None:
        if hasattr(sender, "freeze"):
            sender.freeze()
        started = self._runner.run(fn, on_done=self._after, on_error=self._failed)
        if not started and hasattr(sender, "_buttons"):
            for btn in sender._buttons:  # another action in flight; re-enable
                btn.setEnabled(True)

    def _after(self, _result: object) -> None:
        self.refresh()
        self.changed.emit()

    def _failed(self, message: str) -> None:
        QtWidgets.QMessageBox.warning(self, "Could not apply", message)
        self.refresh()

    def _on_merge(self, source: int, target: int) -> None:
        self._run(self.sender(), lambda: data.merge_person_into(source, target))

    def _on_reject_pair(self, a: int, b: int) -> None:
        self._run(self.sender(), lambda: data.reject_merge_suggestion(a, b))

    def _on_confirm_face(self, face_id: int, person_id: int) -> None:
        self._run(self.sender(), lambda: data.confirm_suggestion(face_id, person_id))

    def _on_reject_face(self, face_id: int, person_id: int) -> None:
        self._run(self.sender(), lambda: data.reject_suggestion(face_id, person_id))
