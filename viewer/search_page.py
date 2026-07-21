"""Semantic Search page — the signature surface (PDD §6.5).

One box searches everything: intent is inferred, never chosen. A person's name
narrows to that person, words found in a photo's text boost it, and the rest is
matched semantically over CLIP image embeddings. The query runs on a background
thread (encoding text can load the model on first use) and results render in the
same virtualized grid the Photos tab uses, above a row of "why matched" chips —
the one place AI evidence surfaces outside Review.

Idle (no query yet), the page offers example searches as clickable chips so the
capability is discoverable without anyone having to guess what to type. If the
CLIP runtime is not installed, the page explains how to enable it.
"""

from __future__ import annotations

from typing import Optional

from PySide6 import QtCore, QtWidgets

from utils.logging_setup import get_logger
from viewer.gallery import PhotoGrid, PhotoGridModel

logger = get_logger("viewer.search")

# Discoverable example searches (plain language, no AI vocabulary).
_SUGGESTIONS = [
    "Sunsets", "At the beach", "Food", "Mountains",
    "In the snow", "Birthdays", "Documents", "Pets",
]


class _SearchWorker(QtCore.QThread):
    """Runs one semantic search off the UI thread."""

    done = QtCore.Signal(list)     # list[SearchResult]
    failed = QtCore.Signal(str)

    def __init__(self, engine, query: str, filters: dict) -> None:
        super().__init__()
        self._engine = engine
        self._query = query
        self._filters = filters

    def run(self) -> None:
        try:
            self.done.emit(self._engine.search(self._query, filters=self._filters))
        except Exception as exc:  # noqa: BLE001
            logger.exception("Search failed")
            self.failed.emit(str(exc))


class SearchPage(QtWidgets.QWidget):
    """Text-to-image semantic search results."""

    photo_activated = QtCore.Signal(int)

    def __init__(self) -> None:
        super().__init__()
        self._engine = None          # lazily created SearchEngine
        self._engine_ready = False
        self._worker: Optional[_SearchWorker] = None

        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(24, 20, 24, 12)
        layout.setSpacing(12)

        title = QtWidgets.QLabel("Search")
        title.setObjectName("H1")
        layout.addWidget(title)

        bar = QtWidgets.QHBoxLayout()
        self._input = QtWidgets.QLineEdit()
        self._input.setObjectName("Search")
        self._input.setPlaceholderText("Search your memories…")
        self._input.returnPressed.connect(self._run)
        button = QtWidgets.QPushButton("Search")
        button.setObjectName("Primary")
        button.clicked.connect(self._run)
        self._favorites_only = QtWidgets.QCheckBox("Favorites only")
        self._favorites_only.toggled.connect(self._on_favorites_toggled)
        bar.addWidget(self._input, 1)
        bar.addWidget(self._favorites_only)
        bar.addWidget(button)
        layout.addLayout(bar)

        # "Why matched" evidence chips + a status line, side by side.
        why_row = QtWidgets.QHBoxLayout()
        why_row.setSpacing(6)
        self._status = QtWidgets.QLabel("")
        self._status.setObjectName("Muted")
        self._why = QtWidgets.QHBoxLayout()
        self._why.setSpacing(6)
        why_row.addWidget(self._status)
        why_row.addSpacing(8)
        why_row.addLayout(self._why)
        why_row.addStretch(1)
        layout.addLayout(why_row)

        # Idle state: a centred hint over a wrap of example-search chips.
        self._suggest = self._build_suggestions()
        layout.addWidget(self._suggest, 1)

        self._model = PhotoGridModel()
        self._grid = PhotoGrid(self._model)
        self._grid.photo_activated.connect(self.photo_activated.emit)
        layout.addWidget(self._grid, 1)

        self._show_idle()

    # -- construction helpers -------------------------------------------------

    def _build_suggestions(self) -> QtWidgets.QWidget:
        panel = QtWidgets.QWidget()
        v = QtWidgets.QVBoxLayout(panel)
        v.setContentsMargins(0, 24, 0, 0)
        v.setSpacing(14)
        v.addStretch(1)

        hint = QtWidgets.QLabel("Find any photo by describing it")
        hint.setObjectName("SearchHint")
        hint.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        v.addWidget(hint)

        sub = QtWidgets.QLabel("Try one of these — or type your own")
        sub.setObjectName("SearchHintSmall")
        sub.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        v.addWidget(sub)

        # Chips in a centred grid (4 per row), each runs its query on click.
        grid_host = QtWidgets.QWidget()
        grid = QtWidgets.QGridLayout(grid_host)
        grid.setHorizontalSpacing(10)
        grid.setVerticalSpacing(10)
        for i, text in enumerate(_SUGGESTIONS):
            chip = QtWidgets.QPushButton(text)
            chip.setObjectName("SearchSuggest")
            chip.setCursor(QtCore.Qt.CursorShape.PointingHandCursor)
            chip.clicked.connect(lambda _=False, q=text: self._run_query(q))
            grid.addWidget(chip, i // 4, i % 4)
        centre = QtWidgets.QHBoxLayout()
        centre.addStretch(1)
        centre.addWidget(grid_host)
        centre.addStretch(1)
        v.addLayout(centre)
        v.addStretch(2)
        return panel

    # -- public API -----------------------------------------------------------

    def focus_input(self) -> None:
        self._input.setFocus()
        self._input.selectAll()

    def current_photo_ids(self) -> list[int]:
        return self._model.photo_ids()

    def show_rows(self, rows: list, status: str) -> None:
        """Display an arbitrary result set (e.g. 'Find similar') in the grid."""
        self._input.clear()
        self._clear_why()
        self._model.set_fetcher(lambda offset, limit: rows[offset:offset + limit])
        self._status.setText(status)
        self._show_results()

    # -- state toggles --------------------------------------------------------

    def _show_idle(self) -> None:
        self._suggest.setVisible(True)
        self._grid.setVisible(False)
        self._clear_why()
        self._status.setText("")

    def _show_results(self) -> None:
        self._suggest.setVisible(False)
        self._grid.setVisible(True)

    def _clear_why(self) -> None:
        while self._why.count():
            w = self._why.takeAt(0).widget()
            if w is not None:
                w.setParent(None)
                w.deleteLater()

    def _add_why(self, text: str) -> None:
        chip = QtWidgets.QLabel(text)
        chip.setObjectName("WhyChip")
        self._why.addWidget(chip)

    # -- search flow ----------------------------------------------------------

    def _on_favorites_toggled(self) -> None:
        # Only re-run if there's an active query; toggling in the idle state
        # shouldn't force a search over nothing.
        if self._input.text().strip():
            self._run()

    def _run_query(self, query: str) -> None:
        self._input.setText(query)
        self._run()

    def _run(self) -> None:
        query = self._input.text().strip()
        if not query:
            self._show_idle()
            return
        if self._worker is not None and self._worker.isRunning():
            return
        if not self._ensure_engine():
            self._show_results()
            self._clear_why()
            self._status.setText(
                "Semantic search needs the CLIP runtime. Install it "
                "(pip install open_clip_torch torch) and run Re-index to build the index."
            )
            return

        self._status.setText(f"Searching for “{query}”…")
        self._clear_why()
        self._show_results()
        filters = {"favorite": self._favorites_only.isChecked()}
        self._worker = _SearchWorker(self._engine, query, filters)
        self._worker.done.connect(self._on_results)
        self._worker.failed.connect(self._on_failed)
        self._worker.start()

    def _ensure_engine(self) -> bool:
        """Create the search engine on first use; return False if unavailable."""
        if self._engine_ready:
            return self._engine is not None
        self._engine_ready = True
        from search.clip_backend import default_backend
        from search.search_engine import SearchEngine

        backend = default_backend()
        self._engine = SearchEngine(backend) if backend is not None else None
        return self._engine is not None

    def _on_results(self, results: list) -> None:
        rows = [r.as_grid_row() for r in results]
        self._model.set_fetcher(lambda offset, limit: rows[offset:offset + limit])
        self._clear_why()
        if rows:
            self._status.setText(f"{len(rows)} result{'s' if len(rows) != 1 else ''}")
            for text in self._why_chips(results):
                self._add_why(text)
        else:
            self._status.setText(
                "No results — build the search index with Re-index first."
            )

    @staticmethod
    def _why_chips(results: list) -> list[str]:
        """Aggregate evidence across the result set into a few "why" chips."""
        chips: list[str] = []
        person = next((r.matched_person for r in results if r.matched_person), None)
        if person:
            chips.append(f"☺ {person}")
        if any(r.similarity > 0 for r in results):
            chips.append("Visual match")
        if any(r.matched_text for r in results):
            chips.append("Text in photo")
        return chips

    def _on_failed(self, message: str) -> None:
        self._clear_why()
        self._status.setText(f"Search error: {message}")
