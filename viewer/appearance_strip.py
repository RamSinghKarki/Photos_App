"""The per-person *appearance strip* — what PhotoSphere has learned about a face.

Shows a person's **representative gallery** (the diverse, quality-gated crops the
recognition engine matches new faces against) as a horizontal row of face crops,
each labelled with its quality. Right-click a crop to drop that appearance: the
face is detached and remembered as a rejection, so a bad representative can be
corrected directly. This makes the learning visible and steerable.

Crops are few (capped at ~12) and small, so they decode synchronously; a missing
or not-yet-generated crop falls back to a neutral placeholder.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any, Optional

from PySide6 import QtCore, QtGui, QtWidgets

from viewer import theme

_THUMB = 72


def _rounded_square(path: Optional[str], size: int) -> QtGui.QPixmap:
    """A center-cropped, rounded square crop; a placeholder when unavailable."""
    image = QtGui.QImage(path) if path and Path(path).exists() else QtGui.QImage()
    out = QtGui.QPixmap(size, size)
    out.fill(QtCore.Qt.GlobalColor.transparent)
    painter = QtGui.QPainter(out)
    painter.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing, True)
    clip = QtGui.QPainterPath()
    clip.addRoundedRect(0, 0, size, size, 8, 8)
    painter.setClipPath(clip)
    if image.isNull():
        painter.fillRect(0, 0, size, size, QtGui.QColor(theme.SURFACE_ALT))
        painter.setPen(QtGui.QColor(theme.TEXT_MUTED))
        painter.drawText(out.rect(), QtCore.Qt.AlignmentFlag.AlignCenter, "☺")
    else:
        scaled = image.scaled(
            size, size,
            QtCore.Qt.AspectRatioMode.KeepAspectRatioByExpanding,
            QtCore.Qt.TransformationMode.SmoothTransformation,
        )
        x = (scaled.width() - size) // 2
        y = (scaled.height() - size) // 2
        painter.drawImage(-x, -y, scaled)
    painter.end()
    return out


class _RepThumb(QtWidgets.QFrame):
    """One representative crop with a quality label; right-click to remove it."""

    rejected = QtCore.Signal(int)  # face_id

    def __init__(self, rep: dict[str, Any]) -> None:
        super().__init__()
        self._face_id = int(rep["face_id"])
        self.setToolTip(self._tooltip(rep))

        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(2, 2, 2, 2)
        layout.setSpacing(2)

        image = QtWidgets.QLabel()
        image.setPixmap(_rounded_square(rep.get("crop_path"), _THUMB))
        image.setFixedSize(_THUMB, _THUMB)
        layout.addWidget(image, 0, QtCore.Qt.AlignmentFlag.AlignHCenter)

        quality = QtWidgets.QLabel(f"{rep['quality']:.2f}")
        quality.setObjectName("Muted")
        quality.setAlignment(QtCore.Qt.AlignmentFlag.AlignHCenter)
        layout.addWidget(quality)

    @staticmethod
    def _tooltip(rep: dict[str, Any]) -> str:
        taken = rep.get("taken_at")
        when = taken.strftime("%Y-%m-%d") if isinstance(taken, datetime) else "date unknown"
        return f"Quality {rep['quality']:.2f} · {when}\nRight-click to remove this appearance"

    def contextMenuEvent(self, event: QtGui.QContextMenuEvent) -> None:  # noqa: N802
        menu = QtWidgets.QMenu(self)
        remove = menu.addAction("Not this person (remove appearance)")
        remove.triggered.connect(lambda: self.rejected.emit(self._face_id))
        menu.exec(event.globalPos())


class AppearanceStrip(QtWidgets.QWidget):
    """Horizontal strip of a person's learned appearances."""

    representative_rejected = QtCore.Signal(int)  # face_id

    def __init__(self) -> None:
        super().__init__()
        outer = QtWidgets.QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(4)

        self._heading = QtWidgets.QLabel("Learned appearances")
        self._heading.setObjectName("H2")
        outer.addWidget(self._heading)

        self._scroll = QtWidgets.QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setFrameShape(QtWidgets.QFrame.Shape.NoFrame)
        self._scroll.setHorizontalScrollBarPolicy(
            QtCore.Qt.ScrollBarPolicy.ScrollBarAsNeeded
        )
        self._scroll.setVerticalScrollBarPolicy(
            QtCore.Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        self._scroll.setFixedHeight(_THUMB + 34)

        self._row = QtWidgets.QWidget()
        self._row_layout = QtWidgets.QHBoxLayout(self._row)
        self._row_layout.setContentsMargins(0, 0, 0, 0)
        self._row_layout.setSpacing(8)
        self._row_layout.addStretch(1)
        self._scroll.setWidget(self._row)
        outer.addWidget(self._scroll)

    def set_representatives(self, reps: list[dict[str, Any]]) -> None:
        # Clear existing thumbs (keep the trailing stretch).
        while self._row_layout.count() > 1:
            item = self._row_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

        self.setVisible(bool(reps))
        self._heading.setText(f"Learned appearances  ({len(reps)})")
        for rep in reps:
            thumb = _RepThumb(rep)
            thumb.rejected.connect(self.representative_rejected.emit)
            self._row_layout.insertWidget(self._row_layout.count() - 1, thumb)


class _SuggestThumb(QtWidgets.QFrame):
    """A suggested face with Yes / No buttons ('Is this <name>?')."""

    confirmed = QtCore.Signal(int)  # face_id
    rejected = QtCore.Signal(int)   # face_id

    def __init__(self, suggestion: dict[str, Any]) -> None:
        super().__init__()
        self._face_id = int(suggestion["face_id"])
        self.setToolTip(f"Best match {suggestion['score']:.2f}")

        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(2, 2, 2, 2)
        layout.setSpacing(2)

        image = QtWidgets.QLabel()
        image.setPixmap(_rounded_square(suggestion.get("crop_path"), _THUMB))
        image.setFixedSize(_THUMB, _THUMB)
        layout.addWidget(image, 0, QtCore.Qt.AlignmentFlag.AlignHCenter)

        buttons = QtWidgets.QHBoxLayout()
        buttons.setSpacing(4)
        yes = QtWidgets.QPushButton("✓")
        yes.setFixedWidth(_THUMB // 2 - 2)
        yes.setToolTip("Yes — this is them")
        yes.clicked.connect(lambda: self.confirmed.emit(self._face_id))
        no = QtWidgets.QPushButton("✗")
        no.setFixedWidth(_THUMB // 2 - 2)
        no.setToolTip("No — not them")
        no.clicked.connect(lambda: self.rejected.emit(self._face_id))
        buttons.addWidget(yes)
        buttons.addWidget(no)
        layout.addLayout(buttons)


class SuggestionStrip(QtWidgets.QWidget):
    """Active learning: borderline faces to confirm or reject for one person."""

    confirmed = QtCore.Signal(int)  # face_id
    rejected = QtCore.Signal(int)   # face_id

    def __init__(self) -> None:
        super().__init__()
        outer = QtWidgets.QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(4)

        self._heading = QtWidgets.QLabel("Suggested")
        self._heading.setObjectName("H2")
        outer.addWidget(self._heading)

        self._scroll = QtWidgets.QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setFrameShape(QtWidgets.QFrame.Shape.NoFrame)
        self._scroll.setVerticalScrollBarPolicy(QtCore.Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._scroll.setFixedHeight(_THUMB + 46)

        self._row = QtWidgets.QWidget()
        self._row_layout = QtWidgets.QHBoxLayout(self._row)
        self._row_layout.setContentsMargins(0, 0, 0, 0)
        self._row_layout.setSpacing(8)
        self._row_layout.addStretch(1)
        self._scroll.setWidget(self._row)
        outer.addWidget(self._scroll)

    def set_suggestions(self, suggestions: list[dict[str, Any]], name: str) -> None:
        while self._row_layout.count() > 1:
            item = self._row_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

        self.setVisible(bool(suggestions))
        who = name or "this person"
        self._heading.setText(f"Suggested — is this {who}?  ({len(suggestions)})")
        for suggestion in suggestions:
            thumb = _SuggestThumb(suggestion)
            thumb.confirmed.connect(self.confirmed.emit)
            thumb.rejected.connect(self.rejected.emit)
            self._row_layout.insertWidget(self._row_layout.count() - 1, thumb)
