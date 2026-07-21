"""Frozen-aware path resolution (utils.paths) — the logic packaging depends on.

Simulates a PyInstaller bundle by setting sys.frozen / sys._MEIPASS, so the
behaviour that only occurs in a shipped build is covered without a real build.
"""

from __future__ import annotations

import importlib
from pathlib import Path


def _reload_paths(monkeypatch, *, frozen=False, meipass=None, platform=None, env=None):
    import sys
    if frozen:
        monkeypatch.setattr(sys, "frozen", True, raising=False)
        if meipass is not None:
            monkeypatch.setattr(sys, "_MEIPASS", str(meipass), raising=False)
    else:
        monkeypatch.delattr(sys, "frozen", raising=False)
        monkeypatch.delattr(sys, "_MEIPASS", raising=False)
    if platform is not None:
        monkeypatch.setattr(sys, "platform", platform)
    for key in ("PHOTOSPHERE_DATA_DIR", "LOCALAPPDATA", "XDG_DATA_HOME"):
        monkeypatch.delenv(key, raising=False)
    for key, value in (env or {}).items():
        monkeypatch.setenv(key, value)
    import utils.paths
    return importlib.reload(utils.paths)


def test_source_mode_uses_project_root(monkeypatch) -> None:
    paths = _reload_paths(monkeypatch, frozen=False)
    assert paths.is_frozen() is False
    assert paths.user_data_dir() == paths.PROJECT_ROOT
    assert paths.resource_path("database/schema.sql") == paths.PROJECT_ROOT / "database/schema.sql"


def test_frozen_resource_uses_meipass(monkeypatch, tmp_path: Path) -> None:
    paths = _reload_paths(monkeypatch, frozen=True, meipass=tmp_path)
    assert paths.is_frozen() is True
    assert paths.resource_path("database/schema.sql") == tmp_path / "database/schema.sql"


def test_frozen_user_dir_windows(monkeypatch, tmp_path: Path) -> None:
    paths = _reload_paths(
        monkeypatch, frozen=True, meipass=tmp_path, platform="win32",
        env={"LOCALAPPDATA": str(tmp_path / "AppData" / "Local")})
    assert paths.user_data_dir() == tmp_path / "AppData" / "Local" / "PhotoSphere"


def test_env_override_wins_even_when_frozen(monkeypatch, tmp_path: Path) -> None:
    paths = _reload_paths(
        monkeypatch, frozen=True, meipass=tmp_path, platform="win32",
        env={"PHOTOSPHERE_DATA_DIR": str(tmp_path / "custom")})
    assert paths.user_data_dir() == tmp_path / "custom"


def test_reload_restores_source_mode(monkeypatch) -> None:
    # Leave the module in its normal (source) state for the rest of the suite.
    paths = _reload_paths(monkeypatch, frozen=False)
    assert paths.user_data_dir() == paths.PROJECT_ROOT
