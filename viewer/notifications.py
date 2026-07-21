"""Notification center — a panel + transient toasts, not modal popups (PDD §4.4).

Premium desktop software rarely interrupts with modal dialogs. Background events
(import finished, duplicates found, backup complete) flow into a dismissible
**panel** (a bell in the top bar with an unread badge) and a brief **toast**;
only destructive confirmations keep a modal. Both are driven by the app's real
signals — nothing polls.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

from PySide6 import QtCore, QtGui, QtWidgets

from viewer import theme


@dataclass
class Notification:
    title: str
    detail: str = ""
    when: datetime = field(default_factory=datetime.now)


class Toast(QtWidgets.QLabel):
    """A brief self-dismissing message anchored to the bottom of its parent."""

    def __init__(self, parent: QtWidgets.QWidget) -> None:
        super().__init__(parent)
        self.setObjectName("Toast")
        self.setVisible(False)
        self.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        self._timer = QtCore.QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self.hide)

    def show_message(self, text: str, msec: int = 2600) -> None:
        self.setText(text)
        self.adjustSize()
        self._reposition()
        self.setVisible(True)
        self.raise_()
        self._timer.start(msec)

    def _reposition(self) -> None:
        parent = self.parentWidget()
        if parent is None:
            return
        x = (parent.width() - self.width()) // 2
        y = parent.height() - self.height() - 24
        self.move(max(0, x), max(0, y))


class NotificationPanel(QtWidgets.QFrame):
    """A floating list of recent notifications, toggled by the bell."""

    def __init__(self, parent: QtWidgets.QWidget) -> None:
        super().__init__(parent)
        self.setObjectName("NotifPanel")
        self.setWindowFlags(QtCore.Qt.WindowType.Popup)
        self.setFixedWidth(320)
        self._col = QtWidgets.QVBoxLayout(self)
        self._col.setContentsMargins(0, 0, 0, 0)
        self._col.setSpacing(0)

        title = QtWidgets.QLabel("Notifications")
        title.setObjectName("NotifTitle")
        title.setContentsMargins(16, 12, 16, 12)
        self._col.addWidget(title)

        self._list = QtWidgets.QVBoxLayout()
        self._list.setContentsMargins(0, 0, 0, 8)
        self._list.setSpacing(0)
        self._col.addLayout(self._list)

        self._empty = QtWidgets.QLabel("No notifications yet")
        self._empty.setObjectName("Muted")
        self._empty.setContentsMargins(16, 4, 16, 16)
        self._col.addWidget(self._empty)

    def render(self, items: list[Notification]) -> None:
        while self._list.count():
            w = self._list.takeAt(0).widget()
            if w is not None:
                w.deleteLater()
        self._empty.setVisible(not items)
        for note in items[:12]:
            row = QtWidgets.QLabel(
                f"<b>{note.title}</b><br><span style='color:{theme.TEXT_MUTED}'>{note.detail}</span>"
            )
            row.setContentsMargins(16, 8, 16, 8)
            row.setWordWrap(True)
            self._list.addWidget(row)


class NotificationCenter(QtCore.QObject):
    """Owns the notification history, the bell button, panel and toast host."""

    changed = QtCore.Signal(int)  # unread count

    def __init__(self, host: QtWidgets.QWidget) -> None:
        super().__init__(host)
        self._items: list[Notification] = []
        self._unread = 0
        self._toast = Toast(host)
        self._panel = NotificationPanel(host)

        self.bell = QtWidgets.QToolButton(host)
        self.bell.setObjectName("Bell")
        self.bell.setText("🔔")
        self.bell.setCursor(QtCore.Qt.CursorShape.PointingHandCursor)
        self.bell.setToolTip("Notifications")
        self.bell.clicked.connect(self._toggle_panel)
        self._badge = QtWidgets.QLabel("", self.bell)
        self._badge.setObjectName("Pill")
        self._badge.move(20, 2)
        self._badge.setVisible(False)

    # -- public API ----------------------------------------------------------
    def notify(self, title: str, detail: str = "", toast: bool = True) -> None:
        """Record a notification; optionally flash a toast."""
        self._items.insert(0, Notification(title, detail))
        self._unread += 1
        self._render_badge()
        if toast:
            self._toast.show_message(title)

    def toast(self, text: str) -> None:
        """Show only a transient toast (no history entry)."""
        self._toast.show_message(text)

    def reposition_toast(self) -> None:
        self._toast._reposition()

    # -- internals -----------------------------------------------------------
    def _render_badge(self) -> None:
        if self._unread:
            self._badge.setText(str(self._unread))
            self._badge.adjustSize()
            self._badge.setVisible(True)
        else:
            self._badge.setVisible(False)
        self.changed.emit(self._unread)

    def _toggle_panel(self) -> None:
        if self._panel.isVisible():
            self._panel.hide()
            return
        self._unread = 0
        self._render_badge()
        self._panel.render(self._items)
        below = self.bell.mapToGlobal(QtCore.QPoint(self.bell.width() - 320, self.bell.height() + 6))
        self._panel.move(below)
        self._panel.adjustSize()
        self._panel.show()
