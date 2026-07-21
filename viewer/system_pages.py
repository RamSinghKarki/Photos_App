"""Insights and About — the trust surfaces (PDD rev 2).

Two read-only pages that answer "what does this app actually know, and can I
trust it?" without any AI vocabulary or configuration:

* :class:`InsightsPage` — a dashboard of what PhotoSphere has learned from the
  library (photos, people, faces, searchable/located/text-bearing photos, the
  date span, bytes on disk), each a plain number with a plain caption.
* :class:`AboutPage` — the offline/privacy promise, the local compute device,
  and the on-device technologies, so the "fully offline, originals never
  touched" positioning is stated where a cautious user goes looking for it.

Neither page writes anything; Settings (which would) is a separate, still-
planned module.
"""

from __future__ import annotations

from typing import Any, Optional

from PySide6 import QtCore, QtWidgets

from viewer import data, theme
from viewer.components import _human_bytes, elevate
from viewer.gpuinfo import detect_gpu
from utils.version import __version__ as APP_VERSION


def _year(value: Any) -> Optional[str]:
    """Year label for a datetime, or None when there's no date."""
    try:
        return str(value.year)
    except AttributeError:
        return None


class _StatCard(QtWidgets.QFrame):
    """A single number over a caption over an optional detail line."""

    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("Card")
        v = QtWidgets.QVBoxLayout(self)
        v.setContentsMargins(18, 16, 18, 16)
        v.setSpacing(2)
        self._value = QtWidgets.QLabel("—")
        self._value.setObjectName("StatValue")
        self._label = QtWidgets.QLabel("")
        self._label.setObjectName("StatLabel")
        self._detail = QtWidgets.QLabel("")
        self._detail.setObjectName("Muted")
        self._detail.setWordWrap(True)
        v.addWidget(self._value)
        v.addWidget(self._label)
        v.addWidget(self._detail)
        elevate(self)

    def set(self, value: str, label: str, detail: str = "") -> None:
        self._value.setText(value)
        self._label.setText(label)
        self._detail.setText(detail)
        self._detail.setVisible(bool(detail))


class InsightsPage(QtWidgets.QWidget):
    """What PhotoSphere has learned about the library — read-only."""

    def __init__(self) -> None:
        super().__init__()
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(24, 20, 24, 16)
        layout.setSpacing(6)

        title = QtWidgets.QLabel("Insights")
        title.setObjectName("H1")
        layout.addWidget(title)
        self._subtitle = QtWidgets.QLabel("What PhotoSphere has learned about your library")
        self._subtitle.setObjectName("Muted")
        layout.addWidget(self._subtitle)
        layout.addSpacing(8)

        # A responsive grid of stat cards (three across).
        grid_host = QtWidgets.QWidget()
        self._grid = QtWidgets.QGridLayout(grid_host)
        self._grid.setHorizontalSpacing(14)
        self._grid.setVerticalSpacing(14)
        self._cards: list[_StatCard] = []
        for i in range(6):
            card = _StatCard()
            self._cards.append(card)
            self._grid.addWidget(card, i // 3, i % 3)
        for col in range(3):
            self._grid.setColumnStretch(col, 1)
        layout.addWidget(grid_host)

        self._empty = QtWidgets.QLabel(
            "Nothing learned yet — import photos and PhotoSphere will start "
            "understanding your library."
        )
        self._empty.setObjectName("Muted")
        self._empty.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self._empty)

        layout.addStretch(1)
        self._trust = QtWidgets.QLabel(
            "Everything above was computed on this device. Nothing left your computer."
        )
        self._trust.setObjectName("Muted")
        layout.addWidget(self._trust)

    def refresh(self) -> None:
        s = data.knowledge_stats()
        has_photos = s["photos"] > 0
        self._empty.setVisible(not has_photos)
        for card in self._cards:
            card.setVisible(has_photos)
        self._trust.setVisible(has_photos)
        if not has_photos:
            return

        first, last = _year(s["first_date"]), _year(s["last_date"])
        span = (f"{first}–{last}" if first and last and first != last
                else first or "no capture dates")
        unnamed = s["persons"] - s["named_persons"]

        self._cards[0].set(f"{s['photos']:,}", "Photos", f"spanning {span}")
        self._cards[1].set(
            f"{s['persons']:,}", "People",
            f"{s['named_persons']} named · {unnamed} to review"
            if s["persons"] else "no faces grouped yet")
        self._cards[2].set(f"{s['faces']:,}", "Faces found",
                           f"{s['faces_ungrouped']} still ungrouped")
        self._cards[3].set(f"{s['searchable']:,}", "Searchable",
                           "photos findable by description")
        self._cards[4].set(f"{s['with_text']:,}", "With text",
                           "photos contain readable text")
        self._cards[5].set(_human_bytes(s["storage_bytes"]), "On disk",
                           f"{s['located']:,} photos have a location")


class AboutPage(QtWidgets.QWidget):
    """The offline/privacy promise and the on-device technologies."""

    def __init__(self) -> None:
        super().__init__()
        outer = QtWidgets.QVBoxLayout(self)
        outer.setContentsMargins(24, 20, 24, 16)
        outer.setSpacing(4)

        wordmark = QtWidgets.QLabel("PhotoSphere AI")
        wordmark.setObjectName("H1")
        outer.addWidget(wordmark)
        tagline = QtWidgets.QLabel(
            f"Version {APP_VERSION} · a fully offline, private AI photo library")
        tagline.setObjectName("Muted")
        outer.addWidget(tagline)
        outer.addSpacing(14)

        gpu = detect_gpu()
        compute = gpu.device_name if gpu.available else "your CPU"
        for title, body in (
            ("100% offline",
             "No account, no cloud, no telemetry. PhotoSphere never sends your "
             "photos or what it learns anywhere."),
            ("Your originals are never modified",
             "The app only ever reads your image files. Names, groupings and "
             "edits live in a local database — your files on disk stay untouched."),
            ("AI runs on your hardware",
             f"Face recognition, search and text extraction all run locally on "
             f"{compute}."),
            ("Your library stays on this machine",
             "Everything PhotoSphere knows is stored in a local PostgreSQL "
             "database on this computer, under your control."),
        ):
            outer.addWidget(self._promise(title, body))
            outer.addSpacing(10)

        outer.addStretch(1)
        credits = QtWidgets.QLabel(
            "On-device technologies: InsightFace (faces) · CLIP (visual search) · "
            "RapidOCR (text) · PostgreSQL + pgvector (storage) · Qt / PySide6 (interface)."
        )
        credits.setObjectName("Muted")
        credits.setWordWrap(True)
        outer.addWidget(credits)

    def _promise(self, title: str, body: str) -> QtWidgets.QFrame:
        card = QtWidgets.QFrame()
        card.setObjectName("Card")
        v = QtWidgets.QVBoxLayout(card)
        v.setContentsMargins(18, 14, 18, 14)
        v.setSpacing(3)
        heading = QtWidgets.QLabel(f"✓  {title}")
        heading.setObjectName("H2")
        text = QtWidgets.QLabel(body)
        text.setObjectName("Muted")
        text.setWordWrap(True)
        v.addWidget(heading)
        v.addWidget(text)
        elevate(card)
        return card

    def refresh(self) -> None:  # static content; nothing to reload
        pass
