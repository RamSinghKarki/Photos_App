"""Unit tests for the user-preference store (config.user_config)."""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from config.user_config import DEFAULTS, ConfigManager


def _mgr(tmp_path: Path) -> ConfigManager:
    return ConfigManager(path=tmp_path / "config.json")


def test_defaults_when_no_file(tmp_path: Path) -> None:
    cfg = _mgr(tmp_path)
    assert cfg.get("appearance", "reduced_motion") is False
    assert cfg.get("search", "result_limit") == 200
    assert cfg.get("ai", "face_match_threshold") is None


def test_set_persists_and_reloads(tmp_path: Path) -> None:
    cfg = _mgr(tmp_path)
    cfg.set("appearance", "reduced_motion", True)
    cfg.set("search", "result_limit", 50)

    again = _mgr(tmp_path)  # fresh instance reads the file
    assert again.get("appearance", "reduced_motion") is True
    assert again.get("search", "result_limit") == 50
    # Atomic write: no leftover temp file.
    assert not (tmp_path / "config.json.tmp").exists()


def test_corrupt_file_degrades_to_defaults(tmp_path: Path) -> None:
    (tmp_path / "config.json").write_text("{not valid json", "utf-8")
    cfg = _mgr(tmp_path)
    assert cfg.get("search", "result_limit") == 200

    # Bad values inside valid JSON are dropped per-key, not wholesale.
    (tmp_path / "config.json").write_text(json.dumps({
        "search": {"result_limit": "banana"},
        "appearance": {"reduced_motion": True},
        "unknown_section": {"x": 1},
    }), "utf-8")
    cfg = _mgr(tmp_path)
    assert cfg.get("search", "result_limit") == 200        # invalid -> default
    assert cfg.get("appearance", "reduced_motion") is True  # valid survives


def test_validation_rejects_out_of_range(tmp_path: Path) -> None:
    cfg = _mgr(tmp_path)
    with pytest.raises(ValueError):
        cfg.set("search", "result_limit", 5)
    with pytest.raises(ValueError):
        cfg.set("ai", "face_match_threshold", 2.0)
    with pytest.raises(ValueError):
        cfg.set("general", "startup_page", "nonexistent")
    with pytest.raises(KeyError):
        cfg.set("nope", "nope", 1)


def test_reset_restores_defaults_and_notifies(tmp_path: Path) -> None:
    cfg = _mgr(tmp_path)
    events: list[int] = []
    cfg.subscribe(lambda: events.append(1))
    cfg.set("search", "result_limit", 99)
    cfg.reset()
    assert cfg.get("search", "result_limit") == DEFAULTS["search"]["result_limit"]
    assert len(events) == 2  # one per change; unchanged sets don't notify
    cfg.set("search", "result_limit", 200)  # already the default -> no event
    assert len(events) == 2


def test_env_export_wins_and_undoes_cleanly(tmp_path: Path) -> None:
    from config.settings import get_settings

    saved = os.environ.get("PHOTOSPHERE_FACE_MATCH_THRESHOLD")
    try:
        cfg = _mgr(tmp_path)
        cfg.set("ai", "face_match_threshold", 0.7)
        cfg.apply_env_exports()
        assert os.environ["PHOTOSPHERE_FACE_MATCH_THRESHOLD"] == "0.7"
        assert get_settings().face_match_threshold == 0.7

        # Clearing the preference removes only OUR export.
        cfg.set("ai", "face_match_threshold", None)
        assert "PHOTOSPHERE_FACE_MATCH_THRESHOLD" not in os.environ
    finally:
        if saved is None:
            os.environ.pop("PHOTOSPHERE_FACE_MATCH_THRESHOLD", None)
        else:
            os.environ["PHOTOSPHERE_FACE_MATCH_THRESHOLD"] = saved
        get_settings.cache_clear()


def test_ui_scale_validation_and_apply(tmp_path, monkeypatch) -> None:
    import os
    from config.user_config import ConfigManager

    cfg = ConfigManager(path=tmp_path / "config.json")
    assert cfg.get("appearance", "ui_scale") == 1.0
    cfg.set("appearance", "ui_scale", 0.8)
    assert cfg.get("appearance", "ui_scale") == 0.8
    import pytest
    with pytest.raises(ValueError):
        cfg.set("appearance", "ui_scale", 3.0)     # out of range

    # _apply_ui_scale exports QT_SCALE_FACTOR from the stored preference.
    monkeypatch.setenv("PHOTOSPHERE_CONFIG_DIR", str(tmp_path))
    monkeypatch.delenv("QT_SCALE_FACTOR", raising=False)
    from config.user_config import get_config
    get_config.cache_clear()
    from viewer.app import _apply_ui_scale
    _apply_ui_scale()
    assert os.environ.get("QT_SCALE_FACTOR") == "0.8"
    monkeypatch.delenv("QT_SCALE_FACTOR", raising=False)
    get_config.cache_clear()
