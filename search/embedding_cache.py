"""Text-embedding cache.

Encoding a text query is cheap but not free, and users repeat searches
("dog", "dog"). This caches recent text vectors in memory (LRU) and on disk, so
a repeated query skips the model entirely. Keyed by model + version + the
normalized query, so switching models never returns stale vectors.

A small built-in LRU (OrderedDict) is used rather than an extra dependency.
"""

from __future__ import annotations

import hashlib
from collections import OrderedDict
from pathlib import Path
from typing import Optional

import numpy as np


class TextEmbeddingCache:
    """LRU + disk cache mapping (model, version, query) -> embedding vector."""

    def __init__(self, capacity: int = 256, disk_dir: Optional[Path] = None) -> None:
        self._mem: "OrderedDict[str, np.ndarray]" = OrderedDict()
        self._capacity = capacity
        self._disk_dir = disk_dir
        if self._disk_dir is not None:
            self._disk_dir.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def _key(model_id: str, version: int, text: str) -> str:
        return f"{model_id}|{version}|{text.strip().lower()}"

    def _disk_path(self, key: str) -> Optional[Path]:
        if self._disk_dir is None:
            return None
        digest = hashlib.sha1(key.encode("utf-8")).hexdigest()
        return self._disk_dir / f"{digest}.npy"

    def get(self, model_id: str, version: int, text: str) -> Optional[np.ndarray]:
        key = self._key(model_id, version, text)
        if key in self._mem:
            self._mem.move_to_end(key)
            return self._mem[key]
        path = self._disk_path(key)
        if path is not None and path.exists():
            try:
                vec = np.load(path)
                self._mem[key] = vec
                self._mem.move_to_end(key)
                return vec
            except Exception:  # noqa: BLE001 - corrupt cache file, ignore
                return None
        return None

    def put(self, model_id: str, version: int, text: str, vector: np.ndarray) -> None:
        key = self._key(model_id, version, text)
        self._mem[key] = vector
        self._mem.move_to_end(key)
        while len(self._mem) > self._capacity:
            self._mem.popitem(last=False)
        path = self._disk_path(key)
        if path is not None:
            try:
                np.save(path, vector)
            except OSError:
                pass  # a cache write failure must never break search
