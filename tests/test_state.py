"""Tests for persistent UI state (resume where you left off)."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

os.environ["QT_QPA_PLATFORM"] = "offscreen"
pytest.importorskip("PySide6")

from PySide6 import QtCore  # noqa: E402

from viewer.state import AppState  # noqa: E402


def _settings(path: Path) -> QtCore.QSettings:
    return QtCore.QSettings(str(path), QtCore.QSettings.Format.IniFormat)


def test_state_roundtrips_across_instances(tmp_path: Path) -> None:
    ini = tmp_path / "state.ini"
    first = AppState(_settings(ini))
    first.save_page("people")
    first.save_tile(224)
    first.save_import_dir("/photos/2026")
    first.sync()

    # A fresh AppState reading the same store sees the persisted values —
    # this is exactly what happens on the next app launch.
    second = AppState(_settings(ini))
    assert second.page() == "people"
    assert second.tile(168) == 224
    assert second.import_dir() == "/photos/2026"


def test_state_defaults_when_empty(tmp_path: Path) -> None:
    state = AppState(_settings(tmp_path / "empty.ini"))
    assert state.page() == "dashboard"
    assert state.tile(168) == 168
    assert state.import_dir() == ""
    assert state.geometry() is None
