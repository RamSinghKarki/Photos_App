"""Semantic search engine.

Turns a natural-language query into ranked photo results:

    text -> (cached) CLIP text vector -> pgvector top-K -> results

The public API (`search`) already accepts a ``filters`` argument so future
metadata filtering (date, camera, favorite, person, …) and richer ranking can be
added without changing callers or the UI.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional

from config.settings import get_settings
from database import db
from search.embedding_backend import EmbeddingBackend
from search.embedding_cache import TextEmbeddingCache
from utils.logging_setup import get_logger
from utils.perf import timer

logger = get_logger("search")


@dataclass(frozen=True)
class SearchResult:
    """One ranked photo result."""

    photo_id: int
    file_path: str
    thumbnail_path: Optional[str]
    taken_at: Any
    score: float

    def as_grid_row(self) -> tuple[int, str, Optional[str], Any]:
        """Adapt to the (id, path, thumbnail, taken_at) row the gallery expects."""
        return (self.photo_id, self.file_path, self.thumbnail_path, self.taken_at)


class SearchEngine:
    """Runs text queries against stored CLIP image embeddings."""

    def __init__(
        self,
        backend: EmbeddingBackend,
        text_cache: Optional[TextEmbeddingCache] = None,
    ) -> None:
        self._backend = backend
        if text_cache is None:
            cache_dir = get_settings().cache_dir / "clip" / "text"
            text_cache = TextEmbeddingCache(disk_dir=cache_dir)
        self._cache = text_cache

    def encode_query(self, query: str):
        """Return the (cached) text embedding for a query."""
        model_id, version = self._backend.model_id, self._backend.version
        cached = self._cache.get(model_id, version, query)
        if cached is not None:
            return cached
        with timer("search.encode_text"):
            vector = self._backend.encode_text(query)
        self._cache.put(model_id, version, query, vector)
        return vector

    def search(
        self,
        query: str,
        limit: int = 200,
        filters: Optional[dict] = None,  # reserved for future metadata filtering
    ) -> list[SearchResult]:
        """Return up to ``limit`` photos most similar to ``query``."""
        text = (query or "").strip()
        if not text:
            return []

        vector = self.encode_query(text)
        with timer("search.vector_query"), db.connection() as conn, conn.cursor() as cur:
            rows = db.search_photos_by_clip(cur, vector.tolist(), self._backend.model_id, limit)

        # `filters` and richer ranking (date/favorite/recency blends) will be
        # applied here later; today results are pure cosine similarity.
        return [
            SearchResult(photo_id=r[0], file_path=r[1], thumbnail_path=r[2],
                         taken_at=r[3], score=r[4])
            for r in rows
        ]
