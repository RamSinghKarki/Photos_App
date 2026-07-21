"""Unit tests for context fusion scoring (pure — no database)."""

from __future__ import annotations

import datetime as _dt

from clustering.context import (
    PersonContext,
    PhotoContext,
    build_person_contexts,
    context_score,
)

_DAY = _dt.datetime(2021, 7, 4, 12, 0, 0)
_LAT, _LON = 37.775, -122.419


def _person(rows):
    return build_person_contexts(rows)[1]


def test_photo_context_build() -> None:
    pc = PhotoContext.build(_DAY, _LAT, _LON)
    assert pc.day == _dt.date(2021, 7, 4)
    assert pc.cell is not None
    # No metadata -> nothing to compare on.
    empty = PhotoContext.build(None, None, None)
    assert empty.day is None and empty.cell is None


def test_same_day_and_place_scores_full() -> None:
    person = _person([(1, _DAY, _LAT, _LON)])
    same = PhotoContext.build(_dt.datetime(2021, 7, 4, 19, 0), _LAT, _LON)
    assert context_score(same, person) == 1.0


def test_day_only_when_photo_has_no_gps() -> None:
    person = _person([(1, _DAY, _LAT, _LON)])
    day_only = PhotoContext.build(_DAY, None, None)
    assert context_score(day_only, person) == 1.0  # judged on the day alone


def test_different_day_and_place_scores_zero() -> None:
    person = _person([(1, _DAY, _LAT, _LON)])
    far = PhotoContext.build(_dt.datetime(2019, 1, 1), 51.5, -0.12)  # other day + city
    assert context_score(far, person) == 0.0


def test_partial_match_day_yes_place_no() -> None:
    person = _person([(1, _DAY, _LAT, _LON)])
    mixed = PhotoContext.build(_DAY, 51.5, -0.12)  # same day, different place
    # day weight 0.6 of (0.6 + 0.4) available -> 0.6.
    assert abs(context_score(mixed, person) - 0.6) < 1e-6


def test_neighbouring_gps_cell_counts_as_same_place() -> None:
    person = _person([(1, _DAY, _LAT, _LON)])
    nudged = PhotoContext.build(_DAY, _LAT + 0.0005, _LON - 0.0005)  # ~50 m away
    assert context_score(nudged, person) == 1.0


def test_nan_gps_is_treated_as_unlocated() -> None:
    """Regression: NaN GPS (from a 0/0 EXIF rational) must not crash the People
    stage. round(nan) raises 'cannot convert float NaN to integer'."""
    nan = float("nan")
    pc = PhotoContext.build(_DAY, nan, nan)
    assert pc.cell is None and pc.day == _dt.date(2021, 7, 4)  # day still usable
    # Building a footprint over a NaN-GPS row must not raise.
    person = build_person_contexts([(1, _DAY, nan, nan)])[1]
    assert person.days and not person.cells


def test_no_comparable_signal_is_zero() -> None:
    person = PersonContext()  # empty footprint
    photo = PhotoContext.build(_DAY, _LAT, _LON)
    assert context_score(photo, person) == 0.0
