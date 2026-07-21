"""Context inspector — the third pane of the shell (PDD §3.1).

One persistent right-hand panel whose content follows what the user is looking
at (the current page now; per-selection detail as pages grow), Lightroom/VS Code
style. Killing most dialogs by keeping "about the current thing" always visible.

Content is pushed in as simple (label, html) sections, so this widget stays
decoupled from the pages — a page or the main window decides *what* to show; the
inspector only decides *how*.
"""

from __future__ import annotations

from typing import Optional

from PySide6 import QtCore, QtWidgets

from viewer import theme


class Inspector(QtWidgets.QFrame):
    """Scrollable stack of labelled sections; shows an empty state when idle."""

    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("Inspector")
        self.setMinimumWidth(240)
        self.setMaximumWidth(340)

        outer = QtWidgets.QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)

        scroll = QtWidgets.QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QtWidgets.QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        outer.addWidget(scroll)

        self._body = QtWidgets.QWidget()
        self._col = QtWidgets.QVBoxLayout(self._body)
        self._col.setContentsMargins(16, 8, 16, 16)
        self._col.setSpacing(2)
        self._col.setAlignment(QtCore.Qt.AlignmentFlag.AlignTop)
        scroll.setWidget(self._body)

        self._empty = QtWidgets.QLabel("Select a photo or person to see details here.")
        self._empty.setObjectName("InspectorEmpty")
        self._empty.setWordWrap(True)
        self._col.addWidget(self._empty)

    def clear(self) -> None:
        self._render([])

    def show_sections(self, sections: list[tuple[str, str]]) -> None:
        """Render ``[(LABEL, html_body), …]``; empty list shows the idle state."""
        self._render(sections)

    def _render(self, sections: list[tuple[str, str]]) -> None:
        while self._col.count():
            item = self._col.takeAt(0)
            w = item.widget()
            if w is not None and w is not self._empty:
                w.setParent(None)  # remove from view NOW; deleteLater is async
                w.deleteLater()
        if not sections:
            self._col.addWidget(self._empty)
            self._empty.setVisible(True)
            return
        self._empty.setVisible(False)
        for label, body in sections:
            head = QtWidgets.QLabel(label.upper())
            head.setObjectName("InspectorLabel")
            self._col.addWidget(head)
            value = QtWidgets.QLabel(body)
            value.setObjectName("Muted")
            value.setWordWrap(True)
            value.setTextFormat(QtCore.Qt.TextFormat.RichText)
            self._col.addWidget(value)
