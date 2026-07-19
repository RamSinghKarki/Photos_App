# PhotoSphere AI — Performance

Principle: **measure before optimizing.** Every change here was driven by a
timing, not a guess.

## Measuring

A tiny, always-present timer (`utils/perf.py`) logs where time goes. It is off
by default and adds no overhead; enable it with an environment variable:

```bash
set PHOTOSPHERE_PERF=1        # Windows
export PHOTOSPHERE_PERF=1     # Linux/macOS
```

Timings are logged under `photosphere.perf` (console + `logs/photosphere.log`):

```
PERF tab.people.refresh: 0.011s
PERF query.persons: 0.010s
```

Instrumented today: each tab switch (`tab.<name>.refresh`, `tab.person_detail.open`)
and each read query (`query.*`). Add more with:

```python
from utils.perf import timer
with timer("my.operation"):
    ...
```

## Case study: the People tab freeze

**Symptom:** clicking the People tab froze the UI briefly.

**Measurement** (3,000 photos, 200 people):

| Tab | Total | DB query | Widget build |
|-----|------:|---------:|-------------:|
| Photos | 23 ms | 22 ms | ~1 ms |
| Person detail | 27 ms | 12 ms | ~15 ms |
| **People (before)** | **228 ms** | 14 ms | **~214 ms** |

The database was **not** the problem (14 ms). The freeze was ~214 ms of building
one widget per person **and decoding every cover image synchronously** on the UI
thread. Moving the query to a worker (a common first instinct) would have saved
~6%.

**Fix:** virtualize the People grid the same way the photo grid already works —
a `QListView` + `QAbstractListModel` (`viewer/people_view.py`) that renders only
visible items, with cover images decoded **off the UI thread** (`QThreadPool`:
`QImage` on a worker, circular `QPixmap` on the GUI thread, LRU-cached).

**Result:**

| People count | Before (eager) | After (virtualized) |
|-------------:|---------------:|--------------------:|
| 200 | 228 ms | **11 ms** |
| 2,000 | ~2 s (extrapolated) | **21 ms** |

The tab now switches instantly and stays flat as the library grows.

## What was already fast (and why)

- **Photos gallery** — already `QListView` + model with incremental paging
  (`canFetchMore`/`fetchMore`) and async thumbnail decoding; 23 ms regardless of
  library size. This is the pattern the People page now follows.
- **Background pipeline** — scan/thumbnail/face/cluster run on a `QThread`
  (`viewer/tasks.py`), never on the UI thread.
- **Persistent thread pool** — thumbnail/cover decoding uses the global
  `QThreadPool`, created once, not a new thread per action.
- **Indexes** — hot columns (`file_path`, `file_hash`, `taken_at`, `person_id`,
  `photos.faces_processed` partial) are indexed; face similarity uses the
  `ivfflat` cosine index.

## Targets (v1.0) and status

| Metric | Target | Status |
|--------|-------:|--------|
| Tab switch | instant (< ~50 ms) | ✅ People 11 ms, Photos 23 ms |
| Gallery scroll | ~60 FPS | ✅ virtualized + async |
| Thumbnail fetch (cached) | < 20 ms | ✅ async, LRU-cached |
| Structured DB search | < 100 ms | ✅ ~20 ms at 3k photos |
| Launch (100k photos) | < 3 s | ✅ **0.23 s** (measured at 100k) |

### Scale test (100,000 photos, 3k faces, 500 people)

| Operation | Time |
|-----------|-----:|
| App launch (window construct + dashboard) | 0.23 s |
| Photos tab (first page) | 38 ms |
| People tab | 22 ms |
| Dashboard tab | 59 ms |
| `library_stats` query | 41–48 ms |

Everything stays well inside target at 100k; no new bottleneck surfaced. (If a
500k library later makes the gallery's `ORDER BY taken_at DESC, id DESC` sort
slow, a composite `(taken_at DESC, id DESC)` index is the ready fix — not needed
at 100k.)

## Method (the order that worked)

1. Add timing logs. 2. Find the real bottleneck. 3. Fix *that* — here,
virtualize the offending view and move image I/O off-thread. Re-measure to prove
the win. Don't optimize anything a measurement hasn't implicated.
