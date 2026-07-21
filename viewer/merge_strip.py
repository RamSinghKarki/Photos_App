"""The "Same person?" strip — heal duplicate profiles from the People page.

Shows the merge scan's pending pairs (two cover crops, names, photo counts and
the similarity score) with **Merge** / **Not the same** actions. Merging keeps
the named/larger person and re-curates its gallery; "Not the same" is remembered
permanently — that pair is never suggested (or auto-merged) again.
"""

from __future__ import annotations

from typing import Any

from PySide6 import QtCore, QtWidgets

from viewer.appearance_strip import _rounded_square

_THUMB = 56


class _PairCard(QtWidgets.QFrame):
    """One suggested pair: covers side by side + Merge / Not-the-same."""

    merge_requested = QtCore.Signal(int, int)   # (source, target)
    reject_requested = QtCore.Signal(int, int)  # (person_a, person_b)

    def __init__(self, pair: dict[str, Any]) -> None:
        super().__init__()
        self.setObjectName("Card")
        a, b = int(pair["person_a"]), int(pair["person_b"])

        layout = QtWidgets.QHBoxLayout(self)
        layout.setContentsMargins(10, 8, 10, 8)
        layout.setSpacing(8)

        for cover_key in ("cover_a", "cover_b"):
            face = QtWidgets.QLabel()
            face.setPixmap(_rounded_square(pair.get(cover_key), _THUMB))
            face.setFixedSize(_THUMB, _THUMB)
            layout.addWidget(face)

        name_a = pair.get("name_a") or "Unknown"
        name_b = pair.get("name_b") or "Unknown"
        text = QtWidgets.QLabel(
            f"{name_a} ({pair['count_a']}) · {name_b} ({pair['count_b']})\n"
            f"match {pair['score']:.2f}"
        )
        text.setObjectName("Muted")
        layout.addWidget(text)

        # Merge keeps the named person; if both/neither are named, the larger.
        if pair.get("name_a") and not pair.get("name_b"):
            source, target = b, a
        elif pair.get("name_b") and not pair.get("name_a"):
            source, target = a, b
        else:
            source, target = (a, b) if pair["count_a"] <= pair["count_b"] else (b, a)

        merge = QtWidgets.QPushButton("Merge")
        merge.setToolTip("These are the same person — combine the profiles")
        merge.clicked.connect(lambda: self.merge_requested.emit(source, target))
        keep = QtWidgets.QPushButton("Not the same")
        keep.setToolTip("Keep them separate and never ask about this pair again")
        keep.clicked.connect(lambda: self.reject_requested.emit(a, b))
        layout.addWidget(merge)
        layout.addWidget(keep)


class MergeSuggestionStrip(QtWidgets.QWidget):
    """Horizontal list of 'Same person?' pairs; hidden when there are none."""

    merge_requested = QtCore.Signal(int, int)
    reject_requested = QtCore.Signal(int, int)

    def __init__(self) -> None:
        super().__init__()
        outer = QtWidgets.QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(4)

        self._heading = QtWidgets.QLabel("Same person?")
        self._heading.setObjectName("H2")
        outer.addWidget(self._heading)

        self._scroll = QtWidgets.QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setFrameShape(QtWidgets.QFrame.Shape.NoFrame)
        self._scroll.setVerticalScrollBarPolicy(QtCore.Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._scroll.setFixedHeight(_THUMB + 40)

        self._row = QtWidgets.QWidget()
        self._row_layout = QtWidgets.QHBoxLayout(self._row)
        self._row_layout.setContentsMargins(0, 0, 0, 0)
        self._row_layout.setSpacing(8)
        self._row_layout.addStretch(1)
        self._scroll.setWidget(self._row)
        outer.addWidget(self._scroll)

    def set_pairs(self, pairs: list[dict[str, Any]]) -> None:
        while self._row_layout.count() > 1:
            item = self._row_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

        self.setVisible(bool(pairs))
        self._heading.setText(f"Same person?  ({len(pairs)})")
        for pair in pairs:
            card = _PairCard(pair)
            card.merge_requested.connect(self.merge_requested.emit)
            card.reject_requested.connect(self.reject_requested.emit)
            self._row_layout.insertWidget(self._row_layout.count() - 1, card)
