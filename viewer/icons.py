"""Crisp, drawn line-art icons for the sidebar and toolbar.

No emoji and no image assets: each icon is painted with QPainter primitives at
2x and downscaled, so it stays sharp on any display and inherits a single
stroke colour that reads on both dark surfaces and the blue selection. Keeps the
UI looking like modern desktop software rather than a web page.
"""

from __future__ import annotations

from typing import Callable

from PySide6 import QtCore, QtGui

_RENDER = 44  # supersampled canvas size; icons are downscaled to the requested size


def _pen(painter: QtGui.QPainter, color: QtGui.QColor, width: float = 3.0) -> None:
    pen = QtGui.QPen(color, width)
    pen.setJoinStyle(QtCore.Qt.PenJoinStyle.RoundJoin)
    pen.setCapStyle(QtCore.Qt.PenCapStyle.RoundCap)
    painter.setPen(pen)
    painter.setBrush(QtCore.Qt.BrushStyle.NoBrush)


def _dashboard(p: QtGui.QPainter, c: QtGui.QColor) -> None:
    _pen(p, c)
    for x, y in ((9, 9), (25, 9), (9, 25), (25, 25)):
        p.drawRoundedRect(x, y, 10, 10, 2, 2)


def _photos(p: QtGui.QPainter, c: QtGui.QColor) -> None:
    _pen(p, c)
    p.drawRoundedRect(8, 10, 28, 24, 3, 3)
    p.drawEllipse(14, 16, 5, 5)
    path = QtGui.QPainterPath()
    path.moveTo(11, 32)
    path.lineTo(20, 22)
    path.lineTo(27, 29)
    path.lineTo(31, 25)
    path.lineTo(34, 32)
    p.drawPath(path)


def _timeline(p: QtGui.QPainter, c: QtGui.QColor) -> None:
    _pen(p, c)
    p.drawEllipse(9, 9, 26, 26)
    p.drawLine(22, 22, 22, 15)
    p.drawLine(22, 22, 28, 25)


def _videos(p: QtGui.QPainter, c: QtGui.QColor) -> None:
    _pen(p, c)
    p.drawRoundedRect(9, 12, 26, 20, 3, 3)
    tri = QtGui.QPainterPath()
    tri.moveTo(19, 18)
    tri.lineTo(28, 22)
    tri.lineTo(19, 26)
    tri.closeSubpath()
    p.drawPath(tri)


def _people(p: QtGui.QPainter, c: QtGui.QColor) -> None:
    _pen(p, c)
    p.drawEllipse(16, 10, 12, 12)
    arc = QtGui.QPainterPath()
    arc.moveTo(10, 34)
    arc.arcTo(10, 22, 24, 24, 30, 120)
    p.drawPath(arc)


def _search(p: QtGui.QPainter, c: QtGui.QColor) -> None:
    _pen(p, c)
    p.drawEllipse(11, 11, 16, 16)
    p.drawLine(25, 25, 33, 33)


def _objects(p: QtGui.QPainter, c: QtGui.QColor) -> None:
    _pen(p, c)
    path = QtGui.QPainterPath()
    path.moveTo(22, 8)
    path.lineTo(34, 15)
    path.lineTo(34, 29)
    path.lineTo(22, 36)
    path.lineTo(10, 29)
    path.lineTo(10, 15)
    path.closeSubpath()
    p.drawPath(path)


def _similar(p: QtGui.QPainter, c: QtGui.QColor) -> None:
    _pen(p, c)
    p.drawRoundedRect(9, 14, 18, 18, 3, 3)
    p.drawRoundedRect(18, 9, 18, 18, 3, 3)


def _albums(p: QtGui.QPainter, c: QtGui.QColor) -> None:
    _pen(p, c)
    p.drawRoundedRect(9, 12, 26, 20, 3, 3)
    p.drawLine(14, 8, 30, 8)


def _favorites(p: QtGui.QPainter, c: QtGui.QColor) -> None:
    _pen(p, c)
    star = QtGui.QPainterPath()
    cx, cy, outer, inner = 22.0, 22.0, 13.0, 5.5
    import math
    for i in range(10):
        angle = math.pi / 2 + i * math.pi / 5
        r = outer if i % 2 == 0 else inner
        x = cx + r * math.cos(angle)
        y = cy - r * math.sin(angle)
        star.lineTo(x, y) if i else star.moveTo(x, y)
    star.closeSubpath()
    p.drawPath(star)


def _archive(p: QtGui.QPainter, c: QtGui.QColor) -> None:
    _pen(p, c)
    p.drawRoundedRect(9, 11, 26, 7, 2, 2)
    p.drawRoundedRect(11, 18, 22, 15, 2, 2)
    p.drawLine(19, 24, 25, 24)


def _trash(p: QtGui.QPainter, c: QtGui.QColor) -> None:
    _pen(p, c)
    p.drawLine(12, 14, 32, 14)
    p.drawLine(18, 14, 18, 10)
    p.drawLine(26, 14, 26, 10)
    p.drawLine(18, 10, 26, 10)
    p.drawRoundedRect(14, 14, 16, 20, 2, 2)


def _settings(p: QtGui.QPainter, c: QtGui.QColor) -> None:
    _pen(p, c, 2.6)
    import math
    cx, cy = 22.0, 22.0
    for i in range(8):
        a = i * math.pi / 4
        p.drawLine(
            int(cx + 9 * math.cos(a)), int(cy + 9 * math.sin(a)),
            int(cx + 14 * math.cos(a)), int(cy + 14 * math.sin(a)),
        )
    p.drawEllipse(14, 14, 16, 16)


def _about(p: QtGui.QPainter, c: QtGui.QColor) -> None:
    _pen(p, c)
    p.drawEllipse(9, 9, 26, 26)
    p.drawLine(22, 20, 22, 29)
    p.drawPoint(22, 15)


_DRAWERS: dict[str, Callable[[QtGui.QPainter, QtGui.QColor], None]] = {
    "dashboard": _dashboard, "photos": _photos, "timeline": _timeline, "videos": _videos,
    "people": _people, "search": _search, "objects": _objects, "similar": _similar,
    "albums": _albums, "favorites": _favorites, "archive": _archive, "trash": _trash,
    "settings": _settings, "about": _about,
}


def nav_icon(key: str, color: str, size: int = 20) -> QtGui.QIcon:
    """Return a crisp line-art icon for a sidebar key in the given colour."""
    pixmap = QtGui.QPixmap(_RENDER, _RENDER)
    pixmap.fill(QtCore.Qt.GlobalColor.transparent)
    painter = QtGui.QPainter(pixmap)
    painter.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing, True)
    drawer = _DRAWERS.get(key)
    if drawer is not None:
        drawer(painter, QtGui.QColor(color))
    painter.end()
    scaled = pixmap.scaled(
        size, size,
        QtCore.Qt.AspectRatioMode.KeepAspectRatio,
        QtCore.Qt.TransformationMode.SmoothTransformation,
    )
    return QtGui.QIcon(scaled)
