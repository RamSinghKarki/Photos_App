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
    score: float                 # blended final score
    similarity: float = 0.0      # raw CLIP similarity
    is_favorite: bool = False

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
        filters: Optional[dict] = None,
    ) -> list[SearchResult]:
        """Return up to ``limit`` photos for ``query``, ranked across signals.

        ``filters`` may contain: ``favorite`` (bool), ``since`` / ``until``
        (datetimes), ``person_id`` (int). A person name typed in the query is
        auto-detected and added as a person filter — combining CLIP + faces.
        The final score blends CLIP similarity with a favorite boost and a
        recency boost (weights from settings).
        """
        text = (query or "").strip()
        if not text:
            return []
        filters = dict(filters or {})

        vector = self.encode_query(text)
        settings = get_settings()
        pool = max(limit * 4, 200)

        with timer("search.vector_query"), db.connection() as conn, conn.cursor() as cur:
            # Combine face signal: if a query word names a known person, restrict.
            if filters.get("person_id") is None:
                for token in text.split():
                    pid = db.find_person_id_by_exact_name(cur, token)
                    if pid is not None:
                        filters["person_id"] = pid
                        break
            fav = bool(filters.get("favorite", False))
            since, until, person_id = filters.get("since"), filters.get("until"), filters.get("person_id")

            clip_rows = db.search_candidates(
                cur, vector.tolist(), self._backend.model_id, pool,
                favorite=fav, since=since, until=until, person_id=person_id,
            )
            # OCR signal: photos whose extracted text matches the query.
            ocr_rows = db.search_photos_by_ocr(
                cur, text.split(), pool,
                favorite=fav, since=since, until=until, person_id=person_id,
            )

        # Merge the two candidate sources by photo id.
        merged: dict[int, list] = {}
        for pid, path, thumb, taken, is_fav, sim in clip_rows:
            merged[pid] = [path, thumb, taken, is_fav, sim, False]
        for pid, path, thumb, taken, is_fav in ocr_rows:
            if pid in merged:
                merged[pid][5] = True                 # also an OCR hit
            else:
                merged[pid] = [path, thumb, taken, is_fav, 0.0, True]

        rows = [(pid, *vals) for pid, vals in merged.items()]
        ranked = self._rank(
            rows, settings.search_favorite_boost, settings.search_recency_boost,
            settings.search_ocr_boost,
        )
        return ranked[:limit]

    @staticmethod
    def _rank(rows, favorite_boost: float, recency_boost: float, ocr_boost: float) -> list[SearchResult]:
        """Blend CLIP similarity with OCR, favorite and recency into a score."""
        # Recency normalized across the candidate pool (newest -> 1.0).
        times = [r[3].timestamp() for r in rows if r[3] is not None]
        t_min, t_max = (min(times), max(times)) if times else (0.0, 0.0)
        span = (t_max - t_min) or 1.0

        results = []
        for photo_id, path, thumb, taken_at, is_fav, sim, ocr_hit in rows:
            recency = ((taken_at.timestamp() - t_min) / span) if taken_at is not None else 0.0
            score = (
                sim
                + (ocr_boost if ocr_hit else 0.0)
                + (favorite_boost if is_fav else 0.0)
                + recency_boost * recency
            )
            results.append(
                SearchResult(
                    photo_id=photo_id, file_path=path, thumbnail_path=thumb,
                    taken_at=taken_at, score=score, similarity=sim, is_favorite=is_fav,
                )
            )
        results.sort(key=lambda r: r.score, reverse=True)
        return results
