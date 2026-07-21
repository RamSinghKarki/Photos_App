"""Tests for small UI helpers that carry logic worth pinning down."""

from __future__ import annotations

import os

import pytest

os.environ["QT_QPA_PLATFORM"] = "offscreen"
pytest.importorskip("PySide6")

from viewer.components import format_duration  # noqa: E402


def test_format_duration() -> None:
    assert format_duration(0) == "0:00"
    assert format_duration(5) == "0:05"
    assert format_duration(65) == "1:05"
    assert format_duration(600) == "10:00"
    assert format_duration(3661) == "1:01:01"
    assert format_duration(-3) == "0:00"  # never negative
