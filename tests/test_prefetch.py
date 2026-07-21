"""Unit tests for the bounded, ordered prefetch helper (pure, no database)."""

from __future__ import annotations

import threading
import time

import pytest

from utils.prefetch import prefetch


def test_results_arrive_in_input_order() -> None:
    # Later items finish first (reverse sleeps) — order must still hold.
    def slow_identity(x: int) -> int:
        time.sleep((5 - x) * 0.01)
        return x * 10

    out = [(i, f.result()) for i, f in prefetch(range(5), slow_identity, workers=4)]
    assert out == [(0, 0), (1, 10), (2, 20), (3, 30), (4, 40)]


def test_per_item_exception_is_raised_at_consumption() -> None:
    def maybe_boom(x: int) -> int:
        if x == 2:
            raise ValueError("bad item")
        return x

    seen: list[int] = []
    for item, future in prefetch(range(4), maybe_boom, workers=2):
        if item == 2:
            with pytest.raises(ValueError, match="bad item"):
                future.result()
        else:
            seen.append(future.result())
    assert seen == [0, 1, 3]  # one failure never stops the stream


def test_in_flight_window_is_bounded() -> None:
    active = 0
    peak = 0
    lock = threading.Lock()

    def tracked(x: int) -> int:
        nonlocal active, peak
        with lock:
            active += 1
            peak = max(peak, active)
        time.sleep(0.01)
        with lock:
            active -= 1
        return x

    results = [f.result() for _i, f in prefetch(range(30), tracked, workers=3, depth=4)]
    assert results == list(range(30))
    assert peak <= 4  # never more than `depth` items running at once


def test_early_close_stops_promptly() -> None:
    started: list[int] = []

    def record(x: int) -> int:
        started.append(x)
        time.sleep(0.005)
        return x

    gen = prefetch(range(1000), record, workers=2, depth=4)
    first_item, first_future = next(gen)
    assert first_future.result() == 0
    gen.close()  # simulates PipelineCancelled unwinding the consumer loop
    time.sleep(0.05)
    assert len(started) < 20  # queued work was cancelled, not drained


def test_input_iterated_on_caller_thread_only() -> None:
    caller = threading.current_thread().name
    threads: set[str] = set()

    def items():
        for i in range(10):
            threads.add(threading.current_thread().name)
            yield i

    for _i, f in prefetch(items(), lambda x: x, workers=4):
        f.result()
    assert threads == {caller}  # streaming DB cursors stay on one thread
