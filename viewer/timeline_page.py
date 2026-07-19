"""Timeline view — browse photos chronologically by year and month.

A Year → Month tree on the left (with per-month counts) gives fast jumps; the
right side shows that month's photos in the same virtualized, async grid the
Photos tab uses. Defaults to the most recent month.
"""

from __future__ import annotations

import calendar
from typing import Optional

from PySide6 import QtCore, QtWidgets

from viewer import data
from viewer.gallery import PhotoGrid, PhotoGridModel

_MONTHS = calendar.month_name  # 1..12 -> "January".."December"


class TimelinePage(QtWidgets.QWidget):
    """Chronological browser. Emits :attr:`photo_activated` with a photo id."""

    photo_activated = QtCore.Signal(int)

    def __init__(self) -> None:
        super().__init__()
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(16, 12, 16, 0)
        layout.setSpacing(10)

        header = QtWidgets.QHBoxLayout()
        title = QtWidgets.QLabel("Timeline")
        title.setObjectName("H1")
        self._subtitle = QtWidgets.QLabel("")
        self._subtitle.setObjectName("Muted")
        header.addWidget(title)
        header.addSpacing(12)
        header.addWidget(self._subtitle)
        header.addStretch(1)
        layout.addLayout(header)

        split = QtWidgets.QHBoxLayout()
        split.setSpacing(12)

        self._tree = QtWidgets.QTreeWidget()
        self._tree.setHeaderHidden(True)
        self._tree.setFixedWidth(220)
        self._tree.setStyleSheet("QTreeWidget { border: none; }")
        self._tree.itemClicked.connect(self._on_item_clicked)

        self._model = PhotoGridModel()
        self._grid = PhotoGrid(self._model)
        self._grid.photo_activated.connect(self.photo_activated.emit)

        split.addWidget(self._tree)
        split.addWidget(self._grid, 1)
        layout.addLayout(split, 1)

        self._empty = QtWidgets.QLabel("No dated photos yet — import photos with EXIF dates.")
        self._empty.setObjectName("Muted")
        layout.addWidget(self._empty)

    def refresh(self) -> None:
        buckets = data.timeline_buckets()
        self._tree.clear()
        self._empty.setVisible(not buckets)
        if not buckets:
            self._model.set_fetcher(lambda offset, limit: [])
            self._subtitle.setText("")
            return

        # Build Year -> Month tree.
        year_items: dict[int, QtWidgets.QTreeWidgetItem] = {}
        first_month: Optional[tuple[int, int]] = None
        for year, month, count in buckets:
            if year not in year_items:
                yi = QtWidgets.QTreeWidgetItem([str(year)])
                self._tree.addTopLevelItem(yi)
                yi.setExpanded(True)
                year_items[year] = yi
            child = QtWidgets.QTreeWidgetItem([f"{_MONTHS[month]}  ({count})"])
            child.setData(0, QtCore.Qt.ItemDataRole.UserRole, (year, month))
            year_items[year].addChild(child)
            if first_month is None:
                first_month = (year, month)

        if first_month is not None:
            self._show_month(*first_month)

    def _on_item_clicked(self, item: QtWidgets.QTreeWidgetItem, _column: int) -> None:
        payload = item.data(0, QtCore.Qt.ItemDataRole.UserRole)
        if payload is not None:
            self._show_month(*payload)

    def _show_month(self, year: int, month: int) -> None:
        self._subtitle.setText(f"{_MONTHS[month]} {year}")
        self._model.set_fetcher(
            lambda offset, limit: data.photos_by_month(year, month, limit, offset)
        )

    def current_photo_ids(self) -> list[int]:
        return self._model.photo_ids()
