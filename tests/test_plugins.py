"""Tests for the pipeline plugin architecture (pure — no DB/models needed)."""

from __future__ import annotations

from pipeline.manager import PluginManager, default_manager


class _FakePlugin:
    def __init__(self, name: str, ai: bool = False, available: bool = True, summary: str = "") -> None:
        self.name = name
        self.title = name.title()
        self.ai = ai
        self._available = available
        self._summary = summary or f"{name} ok"
        self.ran = False

    def is_available(self) -> bool:
        return self._available

    def run(self, on_progress) -> str:
        self.ran = True
        return self._summary


def test_manager_runs_available_plugins_in_order() -> None:
    a = _FakePlugin("a", summary="A")
    b = _FakePlugin("b", summary="B")
    steps: list[str] = []
    parts = PluginManager([a, b]).run(on_step=steps.append)

    assert a.ran and b.ran
    assert parts == ["A", "B"]
    assert steps == ["A", "B"]         # titles emitted in order


def test_manager_skips_unavailable() -> None:
    a = _FakePlugin("a", available=False)
    b = _FakePlugin("b", summary="B")
    parts = PluginManager([a, b]).run()

    assert not a.ran and b.ran
    assert parts == ["a skipped", "B"]  # a is noted as skipped, not run


def test_manager_gates_ai_plugins() -> None:
    thumb = _FakePlugin("thumbnails", ai=False, summary="T")
    face = _FakePlugin("faces", ai=True, summary="F")
    parts = PluginManager([thumb, face]).run(run_ai=False)

    assert thumb.ran and not face.ran   # AI plugin skipped entirely
    assert parts == ["T"]


def test_a_new_plugin_slots_in_without_core_changes() -> None:
    # The extensibility promise: append a plugin, it runs — nothing else changes.
    extra = _FakePlugin("objects", ai=True, summary="+5 objects")
    manager = default_manager()
    manager._plugins.append(extra)  # what registering a real plugin would do

    names = [p.name for p in manager.plugins()]
    assert names == ["thumbnails", "phash", "faces", "people", "clip", "ocr", "objects"]


def test_default_manager_order() -> None:
    names = [p.name for p in default_manager().plugins()]
    assert names == ["thumbnails", "phash", "faces", "people", "clip", "ocr"]
