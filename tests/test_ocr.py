"""Tests for OCR (stub backend) and its contribution to unified search."""

from __future__ import annotations

from pathlib import Path
from typing import List

import numpy as np

from database import db
from ocr.processor import run_ocr
from scanner.scanner import scan_directory
from search.embedding_backend import l2_normalize
from search.embedding_cache import TextEmbeddingCache
from search.embedding_engine import embed_images
from search.search_engine import SearchEngine


class StubOcr:
    """Deterministic OCR: red images -> 'passport', blue -> 'invoice', else ''."""

    name = "stub/ocr"

    def extract_text(self, image) -> str:
        r, g, b = np.asarray(image.convert("RGB")).reshape(-1, 3).mean(0)
        if r > g and r > b:
            return "PASSPORT No 12345"
        if b > r and b > g:
            return "INVOICE total due"
        return ""


class MiniClip:
    """Minimal deterministic CLIP-like backend (512-d)."""

    model_id = "mini/clip"
    version = 1
    dim = 512

    def encode_images(self, images) -> np.ndarray:
        return l2_normalize(np.asarray(
            [np.random.default_rng(i).standard_normal(512) for i in range(len(images))],
            dtype="float32",
        ))

    def encode_text(self, text: str) -> np.ndarray:
        return l2_normalize(np.random.default_rng(7).standard_normal(512).astype("float32"))


# Fixture tree: a.jpg (red), sub/a_copy.jpg (red), sub/b.png (blue),
# with_exif.jpg (green), broken.jpg (unreadable).
def test_ocr_incremental(clean_db, photo_tree: Path) -> None:
    scan_directory(photo_tree)
    summary = run_ocr(StubOcr())

    assert summary.processed == 4        # 4 readable images
    assert summary.unreadable == 1       # broken.jpg
    assert summary.with_text == 3        # 2 red (passport) + 1 blue (invoice)

    with db.connection() as conn, conn.cursor() as cur:
        assert db.count_ocr_texts(cur) == 3

    # Second run does nothing (incremental).
    assert run_ocr(StubOcr()).processed == 0


def test_ocr_db_search(clean_db, photo_tree: Path) -> None:
    scan_directory(photo_tree)
    run_ocr(StubOcr())
    with db.connection() as conn, conn.cursor() as cur:
        hits = db.search_photos_by_ocr(cur, ["passport"], limit=10)
        paths = {Path(h[1]).name for h in hits}
    assert paths == {"a.jpg", "a_copy.jpg"}   # the two red 'passport' images


def test_ocr_contributes_to_unified_search(clean_db, photo_tree: Path) -> None:
    scan_directory(photo_tree)
    embed_images(MiniClip())     # CLIP vectors (random)
    run_ocr(StubOcr())           # OCR text

    engine = SearchEngine(MiniClip(), text_cache=TextEmbeddingCache(disk_dir=None))
    results = engine.search("passport", limit=100)

    # The OCR-matching (red) photos are boosted to the top.
    top_names = {Path(r.file_path).name for r in results[:2]}
    assert top_names == {"a.jpg", "a_copy.jpg"}
