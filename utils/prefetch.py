"""Bounded, ordered thread-pool prefetching — feed slow consumers ahead of time.

The AI pipeline's classic bottleneck: the GPU (or a batch writer) finishes in
milliseconds, then idles while single-threaded Python decodes the next JPEG from
disk. :func:`prefetch` overlaps that I/O + decode work with consumption: a small
thread pool runs ``fn`` on upcoming items while the caller is still handling the
current one, keeping the consumer (detector, embedder, thumbnail writer) busy
back-to-back.

Guarantees, chosen to preserve the pipeline's existing semantics exactly:

* **Order** — results are yielded in input order, so batching, progress counts
  and commits behave identically to the sequential loop.
* **Bounded memory** — at most ``depth`` results exist at once (a decoded 24 MP
  photo is ~72 MB of RGB; unbounded prefetch would eat RAM).
* **Per-item errors** — an exception in ``fn`` is captured and re-raised at the
  *consumer's* ``next()`` for that item, so callers keep their existing
  per-photo try/except (unreadable file handling, SAVEPOINT rollback).
* **Coordinator-only iteration** — the input iterable is only advanced on the
  caller's thread, so streaming DB cursors are never touched from a worker.
* **Cancel-safe** — closing the generator (e.g. a raised ``PipelineCancelled``
  unwinding a ``for`` loop) cancels not-yet-started work and stops promptly.

Workers must only run pure, thread-safe work (Pillow decode/resize releases the
GIL); database writes stay on the caller's thread.
"""

from __future__ import annotations

from collections import deque
from concurrent.futures import Future, ThreadPoolExecutor
from typing import Callable, Iterable, Iterator, TypeVar

Item = TypeVar("Item")
Result = TypeVar("Result")


def prefetch(
    items: Iterable[Item],
    fn: Callable[[Item], Result],
    workers: int,
    depth: int = 0,
) -> Iterator[tuple[Item, "Future[Result]"]]:
    """Yield ``(item, future)`` in input order, computing ``fn`` ahead on a pool.

    ``future.result()`` returns ``fn(item)`` or re-raises its exception. At most
    ``depth`` items (default ``2 * workers``) are in flight or waiting at once.
    """
    workers = max(1, workers)
    depth = depth if depth > 0 else workers * 2
    iterator = iter(items)

    with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="prefetch") as pool:
        pending: deque[tuple[Item, Future]] = deque()
        try:
            exhausted = False
            while True:
                # Top up the in-flight window (input advanced on this thread only).
                while not exhausted and len(pending) < depth:
                    try:
                        item = next(iterator)
                    except StopIteration:
                        exhausted = True
                        break
                    pending.append((item, pool.submit(fn, item)))

                if not pending:
                    return
                yield pending.popleft()  # blocks in future.result() at the caller
        finally:
            # Early exit (cancel / error in the consumer): drop queued work so
            # shutdown doesn't wait on decodes nobody will consume.
            for _item, future in pending:
                future.cancel()
