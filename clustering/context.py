"""Context fusion — recognize a person by *where and when*, not just the face.

A face is rarely seen in isolation: it sits in a photo taken at some time and
place, often among a burst of other photos of the same people. When the face
signal alone is borderline, that capture context can tip the balance — a face
that only weakly matches Ram, but was taken the same day and at the same place as
many confirmed photos of Ram, is very likely Ram.

This module is the pure logic for it (no database): summarize a person's capture
footprint (the set of days and GPS cells their photos span) and score how well a
new photo's context matches it. :mod:`clustering.incremental` turns that score
into a small, bounded boost applied only to already-near-threshold faces, so
context can lift a near-miss but never manufacture a match.

Only strong, always-local signals are used — **capture day** and **GPS place**.
Weaker/degenerate ones (import folder, camera model) are deliberately excluded:
in a single-folder library "same folder" is true for everyone and would boost
indiscriminately.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Iterable, Optional

# GPS rounded to 3 decimals ~ 111 m cells; a match also accepts the 8 neighbours
# so points straddling a cell boundary still count as "same place".
_GPS_DECIMALS = 3
_GPS_STEP = 10 ** (-_GPS_DECIMALS)

_DAY_WEIGHT = 0.6
_PLACE_WEIGHT = 0.4


def _gps_cell(lat: Optional[float], lon: Optional[float]) -> Optional[tuple[int, int]]:
    """Integer grid cell for a coordinate, or None if unlocated."""
    if lat is None or lon is None:
        return None
    return (round(float(lat) / _GPS_STEP), round(float(lon) / _GPS_STEP))


def _neighbours(cell: tuple[int, int]) -> Iterable[tuple[int, int]]:
    cx, cy = cell
    for dx in (-1, 0, 1):
        for dy in (-1, 0, 1):
            yield (cx + dx, cy + dy)


@dataclass
class PhotoContext:
    """The capture context of a single photo."""

    day: Optional[date]
    cell: Optional[tuple[int, int]]

    @classmethod
    def build(
        cls, taken_at: Optional[datetime], lat: Optional[float], lon: Optional[float]
    ) -> "PhotoContext":
        day = taken_at.date() if isinstance(taken_at, datetime) else None
        return cls(day=day, cell=_gps_cell(lat, lon))


@dataclass
class PersonContext:
    """The set of days and places a person's photos span."""

    days: set[date] = field(default_factory=set)
    cells: set[tuple[int, int]] = field(default_factory=set)  # includes neighbours

    def add(self, ctx: PhotoContext) -> None:
        if ctx.day is not None:
            self.days.add(ctx.day)
        if ctx.cell is not None:
            self.cells.update(_neighbours(ctx.cell))


def build_person_contexts(
    rows: Iterable[tuple[int, Optional[datetime], Optional[float], Optional[float]]],
) -> dict[int, PersonContext]:
    """Aggregate (person_id, taken_at, lat, lon) rows into per-person footprints."""
    contexts: dict[int, PersonContext] = {}
    for person_id, taken_at, lat, lon in rows:
        contexts.setdefault(person_id, PersonContext()).add(
            PhotoContext.build(taken_at, lat, lon)
        )
    return contexts


def context_score(photo: PhotoContext, person: PersonContext) -> float:
    """How well a photo's context matches a person's footprint, in [0, 1].

    Averaged over only the signals that are *available* on both sides (a photo
    with no GPS is judged on its day alone), so a missing signal never penalizes.
    Returns 0 when nothing is comparable.
    """
    total = 0.0
    got = 0.0
    if photo.day is not None and person.days:
        total += _DAY_WEIGHT
        if photo.day in person.days:
            got += _DAY_WEIGHT
    if photo.cell is not None and person.cells:
        total += _PLACE_WEIGHT
        if photo.cell in person.cells:  # person.cells already holds neighbours
            got += _PLACE_WEIGHT
    return (got / total) if total else 0.0
