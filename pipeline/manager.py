"""Plugin manager — runs the registered ingestion plugins in order.

The pipeline no longer hard-codes its stages; it asks the manager to run the
plugins. Adding a capability (e.g. object detection) means appending a plugin to
:func:`default_manager` — nothing else in the app changes.
"""

from __future__ import annotations

from typing import Callable, Optional

from pipeline.plugins import (
    ClipPlugin,
    FacePlugin,
    OcrPlugin,
    PeoplePlugin,
    Plugin,
    ProgressCallback,
    ThumbnailPlugin,
)
from utils.logging_setup import get_logger

logger = get_logger("pipeline.manager")


class PluginManager:
    """Holds an ordered list of plugins and runs the enabled/available ones."""

    def __init__(self, plugins: list[Plugin]) -> None:
        self._plugins = list(plugins)

    def plugins(self) -> list[Plugin]:
        return list(self._plugins)

    def run(
        self,
        run_ai: bool = True,
        on_step: Optional[Callable[[str], None]] = None,
        on_progress: Optional[ProgressCallback] = None,
    ) -> list[str]:
        """Run each plugin in order; return the summary fragments.

        AI plugins are skipped when ``run_ai`` is False. Unavailable plugins
        (missing model/deps) are skipped with a note. ``on_step`` is called with
        each running plugin's title; ``on_progress`` is threaded into the plugin.
        """
        parts: list[str] = []
        for plugin in self._plugins:
            if plugin.ai and not run_ai:
                continue
            if not plugin.is_available():
                logger.info("Plugin '%s' unavailable; skipping", plugin.name)
                parts.append(f"{plugin.name} skipped")
                continue
            if on_step is not None:
                on_step(plugin.title)
            summary = plugin.run(on_progress)
            if summary:
                parts.append(summary)
        return parts


def default_manager(
    detector_factory=None, clip_factory=None, ocr_factory=None
) -> PluginManager:
    """The standard ingestion pipeline, in order.

    Register new plugins here — they slot into Import/Re-index automatically.
    """
    return PluginManager([
        ThumbnailPlugin(),
        FacePlugin(detector_factory),
        PeoplePlugin(),
        ClipPlugin(clip_factory),
        OcrPlugin(ocr_factory),
    ])
