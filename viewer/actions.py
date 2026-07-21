"""Run short database actions off the UI thread (audit items U1/P2).

Person corrections (confirm/reject a suggestion, remove faces, merge) re-curate
representative galleries — up to seconds of DB + numpy work on a large person.
Running them in a Qt slot froze the window; this tiny runner executes the action
on the global thread pool and marshals the result (or error) back to the GUI
thread via queued signals.

Deliberately minimal — one action per runner at a time (single-flight): a second
request while one is running is ignored, which doubles as double-click
protection. Fast, bounded single-statement writes (rename, favorite) do not need
this and stay synchronous at their call sites.
"""

from __future__ import annotations

from typing import Callable, Optional

from PySide6 import QtCore

from utils.logging_setup import get_logger

logger = get_logger("viewer.actions")


class _Signals(QtCore.QObject):
    done = QtCore.Signal(object)   # the action's return value
    error = QtCore.Signal(str)


class _Task(QtCore.QRunnable):
    def __init__(self, fn: Callable[[], object], signals: _Signals) -> None:
        super().__init__()
        self._fn = fn
        self._signals = signals

    def run(self) -> None:
        try:
            self._signals.done.emit(self._fn())
        except Exception as exc:  # noqa: BLE001 - surfaced to the UI
            logger.exception("Background action failed")
            self._signals.error.emit(str(exc))


class ActionRunner(QtCore.QObject):
    """Executes one callable at a time on the thread pool, calling back on GUI."""

    def __init__(self, parent: Optional[QtCore.QObject] = None) -> None:
        super().__init__(parent)
        self._busy = False
        self._signals: Optional[_Signals] = None  # kept referenced until done

    def busy(self) -> bool:
        return self._busy

    def run(
        self,
        fn: Callable[[], object],
        on_done: Callable[[object], None],
        on_error: Callable[[str], None],
    ) -> bool:
        """Start ``fn`` on the pool; returns False if an action is in flight."""
        if self._busy:
            return False
        self._busy = True
        signals = _Signals()
        self._signals = signals

        def _finish(handler, payload) -> None:
            self._busy = False
            self._signals = None
            handler(payload)

        signals.done.connect(lambda result: _finish(on_done, result))
        signals.error.connect(lambda message: _finish(on_error, message))
        QtCore.QThreadPool.globalInstance().start(_Task(fn, signals))
        return True
