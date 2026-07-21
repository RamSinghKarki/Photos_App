"""Benchmark PhotoSphere AI's query, UI-load, search and recognition paths.

Seeds a synthetic library of a given size and times the operations that drive
responsiveness, then prints a table. Model inference (face detection, CLIP
encoding) is GPU-bound and measured live via the profiler (PHOTOSPHERE_PERF) on
your machine — this harness measures everything around it.

Usage::

    python -m scripts.benchmark --photos 10000
    python -m scripts.benchmark --photos 100000 --embeddings 5000

Uses the configured database; point it at a throwaway DB
(``PHOTOSPHERE_DB_NAME``) since it TRUNCATEs tables.
"""

from __future__ import annotations

import argparse
import sys
import time
from contextlib import contextmanager
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

import numpy as np  # noqa: E402

from config.settings import get_settings  # noqa: E402
from database import db  # noqa: E402

_RESULTS: list[tuple[str, float]] = []


@contextmanager
def measure(name: str):
    start = time.perf_counter()
    yield
    _RESULTS.append((name, (time.perf_counter() - start) * 1000.0))


def _seed(photos: int, embeddings: int, people: int) -> None:
    rng = np.random.default_rng(0)
    with db.connection() as conn, conn.cursor() as cur:
        db.apply_schema()
        cur.execute("DELETE FROM persons")
        cur.execute("TRUNCATE faces, photos, scan_runs, clip_embeddings RESTART IDENTITY CASCADE")

        cur.execute(
            """
            INSERT INTO photos (file_path, file_hash, file_size, file_mtime, thumbnail_path, taken_at)
            SELECT '/lib/p'||g, '0', 1000, now(), '/lib/t'||g||'.jpg',
                   now() - (g || ' minutes')::interval
            FROM generate_series(1, %s) g
            """,
            (photos,),
        )
        cur.execute("SELECT id FROM photos ORDER BY id LIMIT 1")
        photo_id = cur.fetchone()[0]

        # Distinct random CLIP vectors so the vector index is exercised.
        n_emb = min(embeddings, photos)
        cur.execute("SELECT id FROM photos ORDER BY id LIMIT %s", (n_emb,))
        emb_ids = [r[0] for r in cur.fetchall()]
        for pid in emb_ids:
            vec = rng.standard_normal(512).astype("float32")
            vec /= np.linalg.norm(vec)
            db.upsert_clip_embedding(cur, pid, vec.tolist(), "bench/model", 1)

        # Faces + people with centroids.
        n_faces = min(embeddings, photos)
        per_person = max(1, n_faces // max(1, people))
        person_id = None
        for i in range(n_faces):
            emb = rng.standard_normal(512).astype("float32")
            emb /= np.linalg.norm(emb)
            fid = db.insert_face(cur, photo_id, (0, 0, 10, 10), emb.tolist(), det_score=0.9)
            if i % per_person == 0:
                cur.execute(
                    "INSERT INTO persons (display_name, face_count, cover_face_id, centroid) "
                    "VALUES (%s, %s, %s, %s) RETURNING id",
                    (f"P{i}", per_person, fid, emb.tolist()),
                )
                person_id = cur.fetchone()[0]
            cur.execute("UPDATE faces SET person_id = %s WHERE id = %s", (person_id, fid))
        cur.execute("INSERT INTO scan_runs (root_path, processed) VALUES ('/lib', %s)", (photos,))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="photosphere-benchmark")
    parser.add_argument("--photos", type=int, default=10000)
    parser.add_argument("--embeddings", type=int, default=5000,
                        help="Number of faces + CLIP vectors to seed.")
    parser.add_argument("--people", type=int, default=500)
    args = parser.parse_args(argv)

    t0 = time.perf_counter()
    _seed(args.photos, args.embeddings, args.people)
    seed_s = time.perf_counter() - t0

    rng = np.random.default_rng(1)
    query_vec = rng.standard_normal(512).astype("float32")
    query_vec /= np.linalg.norm(query_vec)

    with db.connection() as conn, conn.cursor() as cur:
        with measure("library_stats (dashboard/status)"):
            db.library_stats(cur)
        with measure("photo_grid first page (300)"):
            db.list_photo_grid(cur, limit=300)
        with measure("people list (People tab)"):
            db.list_persons_with_cover(cur)
        with measure("semantic search top-200 (pgvector)"):
            db.search_photos_by_clip(cur, query_vec.tolist(), "bench/model", limit=200)
        with measure("basic text filter (ILIKE) page"):
            db.list_photo_grid(cur, limit=300, search="p1")

    print(f"\n# {args.photos:,} photos · {min(args.embeddings, args.photos):,} faces/embeddings "
          f"· {args.people} people   (seed {seed_s:.1f}s)\n")
    print(f"| {'Operation':38} | {'Time (ms)':>9} |")
    print(f"|{'-'*40}|{'-'*11}|")
    for name, ms in _RESULTS:
        print(f"| {name:38} | {ms:9.1f} |")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
