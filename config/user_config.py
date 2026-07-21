"""User preferences — the Settings page's persistent store.

Distinct from :mod:`config.settings` (system configuration sourced from the
environment): this holds preferences a person changes in the Settings UI,
persisted as JSON under ``~/.photosphere/config.json`` so they survive
restarts.

Design rules:

* **Safe** — a missing/corrupt file degrades to defaults; unknown keys are
  ignored; every value validates on write.
* **Atomic** — writes go to a temp file renamed into place; a crash mid-write
  never leaves a half-written config.
* **Observable** — subscribers are notified after any change so settings apply
  live (no restart) wherever practical.
* **Env as fallback** — pipeline-level values (thresholds, workers, algorithm)
  are applied by exporting the matching PHOTOSPHERE_* variable before the
  cached system settings are (re)built: a value chosen in Settings wins, an
  environment variable remains the fallback, code defaults last.
"""

from __future__ import annotations

import copy
import json
import os
from functools import lru_cache
from pathlib import Path
from typing import Any, Callable

from utils.logging_setup import get_logger

logger = get_logger("config.user")

# Every key the app reads must exist here so a fresh install always resolves.
DEFAULTS: dict[str, dict[str, Any]] = {
    "general": {
        "startup_page": "dashboard",     # page shown when no session to restore
        "confirm_deletes": True,
    },
    "appearance": {
        "reduced_motion": False,
    },
    "ai": {
        "face_match_threshold": None,    # None -> keep system default
        "cluster_algorithm": None,       # None | "dbscan" | "hdbscan" | "auto"
        "auto_suggestions": True,
    },
    "performance": {
        "worker_threads": None,          # None -> auto
    },
    "search": {
        "result_limit": 200,
    },
}

# section.key -> the PHOTOSPHERE_* variable it exports (pipeline settings only).
_ENV_EXPORTS: dict[tuple[str, str], str] = {
    ("ai", "face_match_threshold"): "PHOTOSPHERE_FACE_MATCH_THRESHOLD",
    ("ai", "cluster_algorithm"): "PHOTOSPHERE_CLUSTER_ALGORITHM",
    ("performance", "worker_threads"): "PHOTOSPHERE_DECODE_WORKERS",
}

_PAGES = ("dashboard", "photos", "timeline", "people", "search")
_ALGOS = (None, "dbscan", "hdbscan", "auto")


def _config_dir() -> Path:
    override = os.environ.get("PHOTOSPHERE_CONFIG_DIR", "").strip()
    return Path(override) if override else Path.home() / ".photosphere"


def _validate(section: str, key: str, value: Any) -> Any:
    """Coerce/validate one setting; raise ValueError on an unusable value."""
    if (section, key) == ("general", "startup_page"):
        if value not in _PAGES:
            raise ValueError(f"startup_page must be one of {_PAGES}")
        return value
    if (section, key) in (("general", "confirm_deletes"),
                          ("appearance", "reduced_motion"),
                          ("ai", "auto_suggestions")):
        return bool(value)
    if (section, key) == ("ai", "face_match_threshold"):
        if value is None:
            return None
        v = float(value)
        if not (0.3 <= v <= 0.95):
            raise ValueError("face_match_threshold must be within 0.30–0.95")
        return v
    if (section, key) == ("ai", "cluster_algorithm"):
        if value not in _ALGOS:
            raise ValueError(f"cluster_algorithm must be one of {_ALGOS}")
        return value
    if (section, key) == ("performance", "worker_threads"):
        if value is None:
            return None
        v = int(value)
        if not (1 <= v <= 32):
            raise ValueError("worker_threads must be within 1–32")
        return v
    if (section, key) == ("search", "result_limit"):
        v = int(value)
        if not (10 <= v <= 1000):
            raise ValueError("result_limit must be within 10–1000")
        return v
    raise KeyError(f"unknown setting {section}.{key}")


class ConfigManager:
    """Load, validate, persist and broadcast user preferences."""

    def __init__(self, path: Path | None = None) -> None:
        self._path = path or (_config_dir() / "config.json")
        self._data = copy.deepcopy(DEFAULTS)
        self._observers: list[Callable[[], None]] = []
        self.load()

    # -- persistence ----------------------------------------------------------

    def load(self) -> None:
        """Read the file over the defaults; a bad/missing file keeps defaults."""
        self._data = copy.deepcopy(DEFAULTS)
        try:
            raw = json.loads(self._path.read_text("utf-8"))
        except FileNotFoundError:
            return
        except (json.JSONDecodeError, OSError) as exc:
            logger.warning("Ignoring unreadable config %s: %s", self._path, exc)
            return
        if not isinstance(raw, dict):
            return
        for section, defaults in DEFAULTS.items():
            incoming = raw.get(section)
            if not isinstance(incoming, dict):
                continue
            for key in defaults:
                if key in incoming:
                    try:
                        self._data[section][key] = _validate(section, key, incoming[key])
                    except (ValueError, KeyError, TypeError) as exc:
                        logger.warning("Ignoring bad config %s.%s: %s", section, key, exc)

    def _save(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self._path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(self._data, indent=2, sort_keys=True), "utf-8")
        os.replace(tmp, self._path)

    # -- reads / writes -------------------------------------------------------

    def get(self, section: str, key: str) -> Any:
        return self._data.get(section, {}).get(key, DEFAULTS[section][key])

    def set(self, section: str, key: str, value: Any) -> None:
        """Validate, persist and broadcast one change (no-op if unchanged)."""
        validated = _validate(section, key, value)
        if self._data.get(section, {}).get(key) == validated:
            return
        self._data.setdefault(section, {})[key] = validated
        self._save()
        self.apply_env_exports()
        self._notify()

    def reset(self) -> None:
        """Restore every setting to defaults, persist, and broadcast."""
        self._data = copy.deepcopy(DEFAULTS)
        self._save()
        self.apply_env_exports()
        self._notify()

    # -- integration ----------------------------------------------------------

    def apply_env_exports(self) -> None:
        """Export pipeline-level choices as PHOTOSPHERE_* and rebuild settings.

        A value set here wins; an unset (None) value falls back to whatever the
        environment/system default already says — the env var is only removed
        if this process set it earlier (tracked via a sentinel suffix var).
        """
        from config.settings import get_settings

        changed = False
        for (section, key), env in _ENV_EXPORTS.items():
            value = self.get(section, key)
            marker = env + "__FROM_CONFIG"
            if value is not None:
                os.environ[env] = str(value)
                os.environ[marker] = "1"
                changed = True
            elif os.environ.pop(marker, None):
                os.environ.pop(env, None)   # only undo our own export
                changed = True
        if changed:
            get_settings.cache_clear()

    # -- notifications --------------------------------------------------------

    def subscribe(self, callback: Callable[[], None]) -> None:
        if callback not in self._observers:
            self._observers.append(callback)

    def _notify(self) -> None:
        for callback in list(self._observers):
            try:
                callback()
            except Exception:  # noqa: BLE001 - one bad observer must not block saving
                logger.exception("Config observer failed")


@lru_cache(maxsize=1)
def get_config() -> ConfigManager:
    """Process-wide user configuration (created on first use)."""
    manager = ConfigManager()
    manager.apply_env_exports()
    return manager
