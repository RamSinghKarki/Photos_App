"""Duplicates review — visually-identical photos, resolved by the user.

Each group of look-alike photos is shown side by side (largest file first, the
natural keeper). The app only ever *recommends*: **Keep this** on a photo hides
the others (they are flagged ``duplicate_of``, never deleted, and restorable);
**Not duplicates** dismisses the group so it is never asked about again. A
footer summarises how many photos are currently hidden, with one-click restore.

Writes are quick but re-query the whole set, so they run off the UI thread via
:class:`~viewer.actions.ActionRunner`; the page refreshes and emits
:attr:`changed` so review badges elsewhere stay in step.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Optional

from PySide6 import QtCore, QtGui, QtWidgets

from viewer import data, theme
from viewer.actions import ActionRunner
from viewer.components import _human_bytes, elevate

_THUMB = 148


def _thumb_pixmap(photo_id: int, thumb_path: Optional[str]) -> QtGui.QPixmap:
    """The photo's thumbnail, or a coloured gradient placeholder keyed to it."""
    if thumb_path and Path(thumb_path).exists():
        pm = QtGui.QPixmap(thumb_path)
        if not pm.isNull():
            return pm.scaled(_THUMB, _THUMB, QtCore.Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                             QtCore.Qt.TransformationMode.SmoothTransformation)
    pm = QtGui.QPixmap(_THUMB, _THUMB)
    pm.fill(QtCore.Qt.GlobalColor.transparent)
    painter = QtGui.QPainter(pm)
    painter.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing, True)
    top, bottom = theme.tile_colors(photo_id)
    grad = QtGui.QLinearGradient(0, 0, _THUMB, _THUMB)
    grad.setColorAt(0, top)
    grad.setColorAt(1, bottom)
    path = QtGui.QPainterPath()
    path.addRoundedRect(0, 0, _THUMB, _THUMB, theme.RADIUS, theme.RADIUS)
    painter.fillPath(path, grad)
    painter.end()
    return pm


class _DuplicateGroup(QtWidgets.QFrame):
    """One group: each candidate photo with a 'Keep this' action, then dismiss."""

    keep_requested = QtCore.Signal(str, int)     # group_key, keep photo id
    dismiss_requested = QtCore.Signal(str)       # group_key

    def __init__(self, group: dict[str, Any]) -> None:
        super().__init__()
        self.setObjectName("Card")
        elevate(self, blur=16, y=3, alpha=55)
        key = group["key"]
        photos = group["photos"]

        outer = QtWidgets.QVBoxLayout(self)
        outer.setContentsMargins(14, 12, 14, 12)
        outer.setSpacing(10)

        header = QtWidgets.QLabel(
            f"{len(photos)} look-alike photos — keep the one you want")
        header.setObjectName("H2")
        outer.addWidget(header)

        row = QtWidgets.QHBoxLayout()
        row.setSpacing(12)
        best_size = photos[0][4] if photos else 0
        for pid, _fp, thumb, taken, size in photos:
            col = QtWidgets.QVBoxLayout()
            col.setSpacing(4)
            pic = QtWidgets.QLabel()
            pic.setFixedSize(_THUMB, _THUMB)
            pic.setPixmap(_thumb_pixmap(pid, thumb))
            pic.setScaledContents(False)
            col.addWidget(pic, 0, QtCore.Qt.AlignmentFlag.AlignHCenter)

            meta = _human_bytes(size)
            if size == best_size and len(photos) > 1:
                meta += "  ·  largest"
            caption = QtWidgets.QLabel(meta)
            caption.setObjectName("Muted")
            caption.setAlignment(QtCore.Qt.AlignmentFlag.AlignHCenter)
            col.addWidget(caption)

            keep = QtWidgets.QPushButton("Keep this")
            if size == best_size:
                keep.setObjectName("Primary")
            keep.clicked.connect(lambda _=False, i=pid: self.keep_requested.emit(key, i))
            col.addWidget(keep)
            row.addLayout(col)
        row.addStretch(1)
        outer.addLayout(row)

        actions = QtWidgets.QHBoxLayout()
        actions.addStretch(1)
        not_dup = QtWidgets.QPushButton("Not duplicates")
        not_dup.setToolTip("These are different photos — never ask about this set again")
        not_dup.clicked.connect(lambda: self.dismiss_requested.emit(key))
        actions.addWidget(not_dup)
        outer.addLayout(actions)


class DuplicatesPage(QtWidgets.QWidget):
    """Review and resolve visual-duplicate groups."""

    changed = QtCore.Signal()

    def __init__(self) -> None:
        super().__init__()
        self._runner = ActionRunner(self)
        self._groups: list[dict[str, Any]] = []

        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(24, 20, 24, 12)
        layout.setSpacing(8)

        title = QtWidgets.QLabel("Duplicates")
        title.setObjectName("H1")
        layout.addWidget(title)
        self._subtitle = QtWidgets.QLabel("")
        self._subtitle.setObjectName("Muted")
        layout.addWidget(self._subtitle)

        self._empty = QtWidgets.QLabel(
            "✓  No duplicates found. PhotoSphere only flags photos that look "
            "the same — it never deletes anything on its own.")
        self._empty.setObjectName("Muted")
        self._empty.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self._empty)

        self._scroll = QtWidgets.QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setFrameShape(QtWidgets.QFrame.Shape.NoFrame)
        self._body = QtWidgets.QWidget()
        self._body_layout = QtWidgets.QVBoxLayout(self._body)
        self._body_layout.setContentsMargins(0, 8, 4, 0)
        self._body_layout.setSpacing(10)
        self._body_layout.addStretch(1)
        self._scroll.setWidget(self._body)
        layout.addWidget(self._scroll, 1)

        self._footer = QtWidgets.QLabel("")
        self._footer.setObjectName("Muted")
        self._footer.setTextInteractionFlags(QtCore.Qt.TextInteractionFlag.LinksAccessibleByMouse)
        self._footer.linkActivated.connect(self._on_restore_all)
        layout.addWidget(self._footer)

    # -- refresh --------------------------------------------------------------

    def refresh(self) -> None:
        self._groups = data.duplicate_groups()
        self._rebuild()

    def _rebuild(self) -> None:
        while self._body_layout.count() > 1:
            w = self._body_layout.takeAt(0).widget()
            if w is not None:
                w.setParent(None)
                w.deleteLater()

        has_any = bool(self._groups)
        self._empty.setVisible(not has_any)
        self._scroll.setVisible(has_any)
        total = sum(len(g["photos"]) for g in self._groups)
        self._subtitle.setText(
            f"{len(self._groups)} group{'s' if len(self._groups) != 1 else ''} "
            f"· {total} photos" if has_any else "Nothing needs your attention.")

        for group in self._groups:
            card = _DuplicateGroup(group)
            card.keep_requested.connect(self._on_keep)
            card.dismiss_requested.connect(self._on_dismiss)
            self._body_layout.insertWidget(self._body_layout.count() - 1, card)

        hidden = data.hidden_duplicates(limit=1)
        n_hidden = len(data.hidden_duplicates(limit=10_000))
        if n_hidden:
            self._footer.setText(
                f"{n_hidden} photo{'s' if n_hidden != 1 else ''} hidden as duplicates. "
                f"<a href='restore'>Restore all</a>")
        else:
            self._footer.setText("")

    # -- actions (off the UI thread) ------------------------------------------

    def _run(self, fn) -> None:
        self._runner.run(fn, on_done=self._after, on_error=self._failed)

    def _after(self, _r: object) -> None:
        self.refresh()
        self.changed.emit()

    def _failed(self, message: str) -> None:
        QtWidgets.QMessageBox.warning(self, "Could not apply", message)
        self.refresh()

    def _group_ids(self, key: str) -> list[int]:
        for g in self._groups:
            if g["key"] == key:
                return [p[0] for p in g["photos"]]
        return []

    def _on_keep(self, key: str, keep_id: int) -> None:
        ids = self._group_ids(key)
        self._run(lambda: data.keep_duplicate(keep_id, ids))

    def _on_dismiss(self, key: str) -> None:
        ids = self._group_ids(key)
        self._run(lambda: data.dismiss_duplicate_group(ids))

    def _on_restore_all(self, _link: str) -> None:
        hidden = [row[0] for row in data.hidden_duplicates(limit=10_000)]

        def restore_all() -> None:
            for pid in hidden:
                data.restore_duplicate(pid)
        self._run(restore_all)
