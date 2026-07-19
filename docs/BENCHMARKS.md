# PhotoSphere AI — Benchmarks

Measured with the built-in harness (`python -m scripts.benchmark --photos N`)
against local PostgreSQL 18 + pgvector. These cover the **query / UI-load /
search / recognition** paths that drive responsiveness. Reproduce on your
machine with the same command; enable `PHOTOSPHERE_PERF=1` to see live per-tab
timings in the app.

> Model inference (InsightFace face detection, CLIP encoding) is GPU-bound and
> depends on your hardware — it is measured live via the profiler on your
> machine, not by this harness. See notes below.

## Results

Seeded with 5,000 faces + 5,000 CLIP embeddings + 500 people at every photo
scale (so search/recognition numbers are held constant while photo-count varies).

| Operation | 1,000 | 10,000 | 100,000 |
|-----------|------:|-------:|--------:|
| `library_stats` (dashboard/status bar) | 5 ms | 5 ms | 22 ms |
| Photos first page (300, virtualized) | 2 ms | 4 ms | 31 ms |
| People tab (list + covers query) | 3 ms | 4 ms | 4 ms |
| Semantic search top-200 (pgvector) | 11 ms | 37 ms | 40 ms |
| Basic text filter (`ILIKE`) page | 2 ms | 6 ms | 47 ms |

App launch (window construct + dashboard) was separately measured at **0.23 s**
with 100k photos — see [PERFORMANCE.md](PERFORMANCE.md).

## Reading it

- **Every interaction stays interactive** (< 50 ms) up to 100k photos — well
  inside the "instant" budget. Combined with virtualized grids + async
  thumbnails, tab switches and scrolling feel immediate.
- **People tab is flat** (~4 ms) regardless of photo count — it depends on the
  number of people, not photos, and the grid is virtualized.
- **Semantic search** is ~40 ms at 5k embeddings via the `ivfflat` cosine index;
  it scales sub-linearly with embedding count (approximate NN).
- **Basic text filter** uses `ILIKE` (a sequential scan) and is the fastest-
  growing line (47 ms at 100k). If it becomes a bottleneck at 500k, a `pg_trgm`
  GIN index on `file_path`/`camera_model` is the ready fix. Not needed today.

## Model inference (measured on your GPU)

These depend on the RTX-class GPU and are observed via `PHOTOSPHERE_PERF=1`:

- **Face detection** — batched on the GPU (InsightFace); CPU fallback is much
  slower. Runs once per photo, incrementally.
- **CLIP image embedding** — batched (`clip_batch_size`, default 64); RTX cards
  are far more efficient batched.
- **CLIP text query** — one text encode per unique query, then cached
  (`TextEmbeddingCache`), so repeats are free.
- **Recognition** (`update_people`) — matrix cosine of new faces vs. person
  centroids + clustering of the remainder; scales with *new* faces, not the
  whole library.

## How to reproduce

```bash
# throwaway DB is recommended (the harness truncates tables)
PHOTOSPHERE_DB_NAME=photosphere_bench python -m scripts.benchmark --photos 100000
```

Seeding 100k rows takes ~20 s (one-time); the measured operations run
afterwards.
