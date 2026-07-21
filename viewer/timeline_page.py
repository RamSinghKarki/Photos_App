"""Timeline view — browse photos chronologically by year and month.

A vertical **scrubber rail** on the left (years as bold headers, months as
selectable rows with per-month counts) gives fast jumps through the whole
library; the right side shows the selected month behind a large "hero" header,
in the same virtualized, async grid the Photos tab uses. Switching months does
a short cross-fade so the change reads as motion, not a hard cut.

Why not one continuous, infinitely-scrolling wall of every photo (PDD §6.6)?
The grid is virtualized a month at a time so it stays at 60 fps on a
100k-photo library; a single continuous QListView spanning every month would
have to know every row's geometry up front, which is exactly the cost
virtualization exists to avoid. The rail gives the same "jump anywhere"
affordance without that memory/scroll cost, so month-at-a-time is the
deliberate trade — see docs/AUDIT.md.
"""

from __future__ import annotations

import calendar
from typing import Optional

from PySide6 import QtCore, QtWidgets

from viewer import data, theme
from viewer.gallery import PhotoGrid, PhotoGridModel

_MONTHS = calendar.month_name  # 1..12 -> "January".."December"


class _MonthRow(QtWidgets.QFrame):
    """One selectable month in the rail: name on the left, count on the right."""

    clicked = QtCore.Signal(int, int)  # year, month

    def __init__(self, year: int, month: int, count: int) -> None:
        super().__init__()
        self._year, self._month = year, month
        self.setObjectName("TimelineMonth")
        self.setCursor(QtCore.Qt.CursorShape.PointingHandCursor)
        row = QtWidgets.QHBoxLayout(self)
        row.setContentsMargins(9, 6, 10, 6)
        row.setSpacing(8)
        name = QtWidgets.QLabel(_MONTHS[month])
        name.setObjectName("TimelineMonthName")
        count_label = QtWidgets.QLabel(f"{count:,}")
        count_label.setObjectName("TimelineCount")
        row.addWidget(name)
        row.addStretch(1)
        row.addWidget(count_label)

    def set_selected(self, selected: bool) -> None:
        self.setProperty("selected", "true" if selected else "false")
        # Dynamic-property selectors only take effect after a style repolish.
        self.style().unpolish(self)
        self.style().polish(self)

    def mousePressEvent(self, event) -> None:  # noqa: N802
        if event.button() == QtCore.Qt.MouseButton.LeftButton:
            self.clicked.emit(self._year, self._month)


class TimelinePage(QtWidgets.QWidget):
    """Chronological browser. Emits :attr:`photo_activated` with a photo id."""

    photo_activated = QtCore.Signal(int)

    def __init__(self) -> None:
        super().__init__()
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        split = QtWidgets.QHBoxLayout()
        split.setContentsMargins(0, 0, 0, 0)
        split.setSpacing(0)

        # --- Scrubber rail (years + months) ---------------------------------
        self._rail = QtWidgets.QScrollArea()
        self._rail.setObjectName("TimelineRail")
        self._rail.setFixedWidth(212)
        self._rail.setWidgetResizable(True)
        self._rail.setFrameShape(QtWidgets.QFrame.Shape.NoFrame)
        self._rail.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._rail_body = QtWidgets.QWidget()
        self._rail_layout = QtWidgets.QVBoxLayout(self._rail_body)
        self._rail_layout.setContentsMargins(0, 4, 0, 12)
        self._rail_layout.setSpacing(0)
        self._rail_layout.addStretch(1)
        self._rail.setWidget(self._rail_body)
        self._rows: dict[tuple[int, int], _MonthRow] = {}
        self._counts: dict[tuple[int, int], int] = {}
        self._selected: Optional[tuple[int, int]] = None

        # --- Content: hero header over the month grid -----------------------
        content = QtWidgets.QWidget()
        content_layout = QtWidgets.QVBoxLayout(content)
        content_layout.setContentsMargins(20, 16, 16, 0)
        content_layout.setSpacing(4)

        self._hero = QtWidgets.QLabel("Timeline")
        self._hero.setObjectName("TimelineHero")
        self._subtitle = QtWidgets.QLabel("")
        self._subtitle.setObjectName("Muted")
        content_layout.addWidget(self._hero)
        content_layout.addWidget(self._subtitle)
        content_layout.addSpacing(8)

        self._model = PhotoGridModel()
        self._grid = PhotoGrid(self._model)
        self._grid.photo_activated.connect(self.photo_activated.emit)
        # A fade the month switch animates for a soft cross-cut.
        self._fade = QtWidgets.QGraphicsOpacityEffect(self._grid)
        self._fade.setOpacity(1.0)
        self._grid.setGraphicsEffect(self._fade)
        self._fade_anim = QtCore.QPropertyAnimation(self._fade, b"opacity", self)
        self._fade_anim.setDuration(theme.MOTION_MS["fade"])
        content_layout.addWidget(self._grid, 1)

        self._empty = QtWidgets.QLabel(
            "No dated photos yet — import photos with capture dates to see them here."
        )
        self._empty.setObjectName("Muted")
        self._empty.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        content_layout.addWidget(self._empty)

        split.addWidget(self._rail)
        split.addWidget(content, 1)
        layout.addLayout(split, 1)

    def refresh(self) -> None:
        buckets = data.timeline_buckets()
        self._clear_rail()
        has_photos = bool(buckets)
        self._empty.setVisible(not has_photos)
        self._grid.setVisible(has_photos)
        if not has_photos:
            self._model.set_fetcher(lambda offset, limit: [])
            self._hero.setText("Timeline")
            self._subtitle.setText("")
            self._selected = None
            return

        # Build the rail: a year header, then its months (buckets are newest
        # first, so years and months already descend).
        first_month: Optional[tuple[int, int]] = None
        current_year: Optional[int] = None
        for year, month, count in buckets:
            if year != current_year:
                header = QtWidgets.QLabel(str(year))
                header.setObjectName("TimelineYear")
                self._rail_layout.insertWidget(self._rail_layout.count() - 1, header)
                current_year = year
            row = _MonthRow(year, month, count)
            row.clicked.connect(self._show_month)
            self._rail_layout.insertWidget(self._rail_layout.count() - 1, row)
            self._rows[(year, month)] = row
            self._counts[(year, month)] = count
            if first_month is None:
                first_month = (year, month)

        if first_month is not None:
            self._show_month(*first_month, animate=False)

    def _clear_rail(self) -> None:
        while self._rail_layout.count() > 1:  # keep the trailing stretch
            item = self._rail_layout.takeAt(0)
            w = item.widget()
            if w is not None:
                w.setParent(None)
                w.deleteLater()
        self._rows = {}
        self._counts = {}

    def _show_month(self, year: int, month: int, animate: bool = True) -> None:
        if (year, month) == self._selected:
            return
        prev = self._rows.get(self._selected) if self._selected else None
        if prev is not None:
            prev.set_selected(False)
        row = self._rows.get((year, month))
        if row is not None:
            row.set_selected(True)
        self._selected = (year, month)

        self._hero.setText(f"{_MONTHS[month]} {year}")
        total = self._counts.get((year, month), 0)
        self._subtitle.setText(f"{total:,} photo{'s' if total != 1 else ''}")
        self._model.set_fetcher(
            lambda offset, limit: data.photos_by_month(year, month, limit, offset)
        )
        self._grid.scrollToTop()

        if animate:
            self._fade_anim.stop()
            self._fade_anim.setStartValue(0.25)
            self._fade_anim.setEndValue(1.0)
            self._fade_anim.start()

    def current_photo_ids(self) -> list[int]:
        return self._model.photo_ids()
