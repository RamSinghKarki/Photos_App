"""Command palette — Ctrl+K, keyboard-first access to everything (PDD §6.5).

A single overlay that fuzzily filters a registered list of commands (navigate,
import, search, actions) and runs the chosen one. Raycast/VS Code style: the app
becomes operable without the mouse, which is a large part of the "premium
desktop" feel. Commands are supplied by the main window, so the palette knows
nothing about the app's internals.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from PySide6 import QtCore, QtGui, QtWidgets


@dataclass(frozen=True)
class Command:
    """One palette entry: what it's called, how it's found, what it does."""

    title: str                 # shown, and matched against
    run: Callable[[], None]     # invoked on Enter/click
    hint: str = ""             # right-aligned shortcut/context (optional)
    keywords: str = ""         # extra match text, never shown


def _matches(query: str, cmd: Command) -> bool:
    """Subsequence fuzzy match over title + keywords (order-preserving)."""
    hay = f"{cmd.title} {cmd.keywords}".lower()
    it = iter(hay)
    return all(ch in it for ch in query.lower().replace(" ", ""))


class CommandPalette(QtWidgets.QDialog):
    """Frameless centered overlay listing filtered commands."""

    def __init__(self, parent: QtWidgets.QWidget) -> None:
        super().__init__(parent)
        self.setWindowFlags(QtCore.Qt.WindowType.Popup | QtCore.Qt.WindowType.FramelessWindowHint)
        self.setModal(True)
        self.setObjectName("PaletteHost")
        self.setAttribute(QtCore.Qt.WidgetAttribute.WA_TranslucentBackground)
        self._commands: list[Command] = []
        self._filtered: list[Command] = []

        outer = QtWidgets.QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)

        frame = QtWidgets.QFrame()
        frame.setObjectName("Palette")
        frame.setFixedWidth(560)
        col = QtWidgets.QVBoxLayout(frame)
        col.setContentsMargins(0, 0, 0, 0)
        col.setSpacing(0)

        self._input = QtWidgets.QLineEdit()
        self._input.setObjectName("PaletteInput")
        self._input.setPlaceholderText("Type a command or search your memories…")
        self._input.textChanged.connect(self._refilter)
        self._input.installEventFilter(self)  # route ↑/↓/Enter to the list

        self._list = QtWidgets.QListWidget()
        self._list.setObjectName("PaletteList")
        self._list.setMaximumHeight(320)
        self._list.itemActivated.connect(lambda _i: self._run_current())
        self._list.itemClicked.connect(lambda _i: self._run_current())

        col.addWidget(self._input)
        col.addWidget(self._list)
        outer.addWidget(frame, 0, QtCore.Qt.AlignmentFlag.AlignHCenter)
        outer.setContentsMargins(0, 96, 0, 0)  # sit below the top bar

    def set_commands(self, commands: list[Command]) -> None:
        self._commands = commands

    def open(self) -> None:
        """Show the palette centered over the parent, fresh and focused."""
        parent = self.parentWidget()
        if parent is not None:
            geo = parent.geometry()
            self.setFixedWidth(geo.width())
            self.move(parent.mapToGlobal(QtCore.QPoint(0, 0)))
            self.setFixedHeight(geo.height())
        self._input.clear()
        self._refilter("")
        self.show()
        self._input.setFocus()

    def _refilter(self, text: str) -> None:
        query = text.strip()
        self._filtered = [c for c in self._commands if not query or _matches(query, c)]
        self._list.clear()
        for cmd in self._filtered:
            item = QtWidgets.QListWidgetItem(cmd.title + ("     " + cmd.hint if cmd.hint else ""))
            self._list.addItem(item)
        if self._filtered:
            self._list.setCurrentRow(0)

    def _run_current(self) -> None:
        row = self._list.currentRow()
        if 0 <= row < len(self._filtered):
            cmd = self._filtered[row]
            self.accept()
            cmd.run()

    def eventFilter(self, obj: QtCore.QObject, event: QtCore.QEvent) -> bool:  # noqa: N802
        if event.type() == QtCore.QEvent.Type.KeyPress:
            key = event.key()
            if key in (QtCore.Qt.Key.Key_Down, QtCore.Qt.Key.Key_Up):
                row = self._list.currentRow()
                row += 1 if key == QtCore.Qt.Key.Key_Down else -1
                self._list.setCurrentRow(max(0, min(row, self._list.count() - 1)))
                return True
            if key in (QtCore.Qt.Key.Key_Return, QtCore.Qt.Key.Key_Enter):
                self._run_current()
                return True
            if key == QtCore.Qt.Key.Key_Escape:
                self.reject()
                return True
        return super().eventFilter(obj, event)
