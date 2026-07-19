"""Tests for the AI search subsystem, using a stub embedding backend.

The real CLIP model needs a GPU/download, so a deterministic stub stands in
(exactly like the face detector). This exercises everything the subsystem owns:
incremental + batched embedding, storage, the pgvector top-K query, and the
text-embedding cache — without the model.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import List

import numpy as np

from database import db
from scanner.scanner import scan_directory
from search.embedding_backend import l2_normalize
from search.embedding_cache import TextEmbeddingCache
from search.embedding_engine import embed_images
from search.search_engine import SearchEngine

READABLE = 4  # openable images in the fixture tree (broken.jpg excluded)


class StubBackend:
    """Deterministic 512-d embeddings; records batch sizes and text calls."""

    model_id = "stub/test"
    version = 1
    dim = 512

    def __init__(self) -> None:
        self.image_batches: List[int] = []
        self.text_calls = 0

    @staticmethod
    def _seed(data: bytes) -> int:
        return int.from_bytes(hashlib.sha256(data).digest()[:4], "big")

    def encode_images(self, images) -> np.ndarray:
        self.image_batches.append(len(images))
        rows = []
        for im in images:
            rng = np.random.default_rng(self._seed(im.tobytes()))
            rows.append(rng.standard_normal(self.dim).astype("float32"))
        return l2_normalize(np.asarray(rows, dtype="float32"))

    def encode_text(self, text: str) -> np.ndarray:
        self.text_calls += 1
        rng = np.random.default_rng(self._seed(text.encode("utf-8")))
        return l2_normalize(rng.standard_normal(self.dim).astype("float32"))


def test_embed_incremental_and_batched(clean_db, photo_tree: Path) -> None:
    scan_directory(photo_tree)
    backend = StubBackend()
    summary = embed_images(backend, batch_size=2)

    assert summary.embedded == READABLE   # 4 real images
    assert summary.unreadable == 1        # broken.jpg
    assert summary.errors == 0
    assert sum(backend.image_batches) == READABLE      # every image encoded
    assert max(backend.image_batches) <= 2             # batching respected

    with db.connection() as conn, conn.cursor() as cur:
        assert db.count_clip_embeddings(cur, backend.model_id) == READABLE


def test_embedding_is_incremental(clean_db, photo_tree: Path) -> None:
    scan_directory(photo_tree)
    embed_images(StubBackend())
    second = embed_images(StubBackend())   # nothing new to embed
    assert second.embedded == 0


def test_search_ranks_by_similarity(clean_db, photo_tree: Path) -> None:
    scan_directory(photo_tree)
    embed_images(StubBackend())

    with db.connection() as conn, conn.cursor() as cur:
        # Query with a stored embedding -> that photo must rank first (score ~1).
        cur.execute("SELECT photo_id, embedding FROM clip_embeddings ORDER BY photo_id LIMIT 1")
        photo_id, embedding = cur.fetchone()
        vec = embedding.to_numpy() if hasattr(embedding, "to_numpy") else np.asarray(embedding)
        results = db.search_photos_by_clip(cur, vec.tolist(), "stub/test", limit=10)

    assert results[0][0] == photo_id
    assert results[0][4] > 0.99            # near-perfect self-similarity
    assert len(results) == READABLE


def test_search_engine_and_text_cache(clean_db, photo_tree: Path) -> None:
    scan_directory(photo_tree)
    backend = StubBackend()
    embed_images(backend)

    engine = SearchEngine(backend, text_cache=TextEmbeddingCache(disk_dir=None))
    results = engine.search("a dog on a beach", limit=100)
    assert len(results) == READABLE        # all embedded photos, ranked
    assert results[0].score >= results[-1].score  # descending by similarity

    # The same query is served from cache — the backend encodes text only once.
    calls_after_first = backend.text_calls
    engine.search("a dog on a beach")
    assert backend.text_calls == calls_after_first
