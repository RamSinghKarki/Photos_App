"""Semantic Search page.

A natural-language search box over CLIP image embeddings. The query runs on a
background thread (encoding text can load the model on first use), and results
render in the same virtualized grid the Photos tab uses. If the CLIP runtime is
not installed, the page explains how to enable it instead of failing.
"""

from __future__ import annotations

from typing import Optional

from PySide6 import QtCore, QtWidgets

from utils.logging_setup import get_logger
from viewer.gallery import PhotoGrid, PhotoGridModel

logger = get_logger("viewer.search")


class _SearchWorker(QtCore.QThread):
    """Runs one semantic search off the UI thread."""

    done = QtCore.Signal(list)     # list[SearchResult]
    failed = QtCore.Signal(str)

    def __init__(self, engine, query: str) -> None:
        super().__init__()
        self._engine = engine
        self._query = query

    def run(self) -> None:
        try:
            self.done.emit(self._engine.search(self._query))
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
        self._input.setPlaceholderText("Describe what you're looking for — e.g. \"dog on a beach\"")
        self._input.returnPressed.connect(self._run)
        button = QtWidgets.QPushButton("Search")
        button.setObjectName("Primary")
        button.clicked.connect(self._run)
        bar.addWidget(self._input, 1)
        bar.addWidget(button)
        layout.addLayout(bar)

        self._status = QtWidgets.QLabel("")
        self._status.setObjectName("Muted")
        layout.addWidget(self._status)

        self._model = PhotoGridModel()
        self._grid = PhotoGrid(self._model)
        self._grid.photo_activated.connect(self.photo_activated.emit)
        layout.addWidget(self._grid, 1)

    def focus_input(self) -> None:
        self._input.setFocus()
        self._input.selectAll()

    def current_photo_ids(self) -> list[int]:
        return self._model.photo_ids()

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

    def _run(self) -> None:
        query = self._input.text().strip()
        if not query:
            return
        if self._worker is not None and self._worker.isRunning():
            return
        if not self._ensure_engine():
            self._status.setText(
                "Semantic search needs the CLIP runtime. Install it "
                "(pip install open_clip_torch torch) and run Re-index to build the index."
            )
            return

        self._status.setText(f"Searching for “{query}”…")
        self._worker = _SearchWorker(self._engine, query)
        self._worker.done.connect(self._on_results)
        self._worker.failed.connect(self._on_failed)
        self._worker.start()

    def _on_results(self, results: list) -> None:
        rows = [r.as_grid_row() for r in results]
        self._model.set_fetcher(lambda offset, limit: rows[offset:offset + limit])
        self._status.setText(
            f"{len(rows)} result(s)" if rows
            else "No results — build the search index with Re-index first."
        )

    def _on_failed(self, message: str) -> None:
        self._status.setText(f"Search error: {message}")
