# PhotoSphere AI — Senior-Engineer Audit (2026-07)

A no-feature-development review of the whole project: architecture, performance,
database, UI, and test coverage, ending in a prioritized technical-debt register.
Method: full code review plus **measurement** (the standing test suite, targeted
micro-benchmarks of paths the existing harness predates). Findings reference
files/functions rather than line numbers.

**Baseline at audit time:** 89 Python files, ~10.4k lines; **102 tests passing**;
0 TODO/FIXME markers; branch `claude/photosphere-prompt-improvements-mv6t21`.

---

## 1. Architecture

**Sound overall.** Clear module boundaries (scanner → database → clustering /
search / ocr → pipeline → viewer), all SQL confined to `database/db.py`, the
ingestion pipeline is a plugin system, heavy work runs off the UI thread through
one worker, pure logic (quality/gallery/context) is separated from I/O and unit-
tested. The constraints hold: fully offline, incremental everywhere, additive
schema.

Findings, in decreasing severity:

- **A1 — `viewer/data.py` has outgrown its contract.** Its docstring says
  *"Read-only data access"*; it now contains 8 write functions, and three of them
  (`remove_faces_from_person`, `reject_representative`, `confirm_suggestion`,
  plus `merge_person_into`) orchestrate multi-step business logic and
  lazy-import `clustering.incremental` to dodge a layering inversion. Person
  *actions* are a domain concern: they belong in a service module (e.g.
  `clustering/actions.py`), with `viewer/data.py` back to thin wrappers.
- **A2 — Page registration is quadruple bookkeeping.** Adding a page touches
  `main_window._PLANNED_NOTES`, the `_page_keys` loop, `theme.IMPLEMENTED_PAGES`,
  and `theme.SIDEBAR_SECTIONS`. The Timeline work touched three of the four; a
  missed one silently shows a "planned" page for a built feature. One registry
  (key → title, widget-factory, implemented?) should drive all four consumers.
- **A3 — `viewer/tasks.py` duplicates the selected-photos flow.** The
  `photo_ids` branch hard-codes step titles ("Detecting faces", "Recognizing
  people") that duplicate plugin titles, and re-implements a two-stage pipeline
  beside the manager. Acceptable today; fold into the plugin path when touched.
- **A4 — Business logic in the storage layer.** `db.merge_persons` recomputes a
  centroid inline — the same code as `db.recompute_person_profile` (added later).
  `db.py` should stay storage-only; merge should reuse the helper.
- **A5 — Dead code / unused hooks.** `db.fetch_ungrouped_face_vectors` has no
  callers (superseded by `fetch_ungrouped_faces`). `data.suggestion_count` /
  `db.count_suggestions` were built for a review badge that was never wired into
  the UI — wire it or remove it.

## 2. Performance

Interactive reads were re-verified conceptually against BENCHMARKS.md (all
< 50 ms at 100k photos). Two paths added *after* that benchmark were measured
now (Postgres 16, this container, `photosphere_test`):

| Scenario (measured) | Result |
|---|---|
| `update_people` matching: 150 persons (8 reps each), 1 500 new faces, **context ON** | **1.99 s** |
| Same, context OFF (`PHOTOSPHERE_CONTEXT_BOOST=0`) | **0.76 s** |
| `rebuild_person_gallery` on a person with 1 000 faces | **1.92 s** |

- **P1 — Context/rejection scoring is O(persons × faces) in Python.**
  In `clustering/incremental._assign_to_existing`, the context boost computes
  `context_score` for **every** face per person (`for i in range(n)`), and the
  rejection mask builds a Python list per person. Measured: context fusion makes
  matching **2.6× slower** at 150×1 500; the cost grows multiplicatively (500
  persons × 10k faces ≈ 5M Python calls → tens of seconds in the pipeline).
  *Fix (small):* compute context only for `np.nonzero(eligible)` rows — the
  near-threshold band is narrow, so this is typically dozens of faces, not all N
  — and vectorize the rejected mask with `np.isin`.
- **P2 — Person-correction handlers freeze the UI on large persons.**
  `rebuild_person_gallery` on a 1 000-face person takes **~1.9 s**, and it runs
  synchronously in Qt slots (see U1). Root causes: (a) it re-inserts the whole
  gallery as 1 000 individual upserts — batch them into one statement; (b) it
  runs on the UI thread — move corrections to a small worker (same pattern as
  `_SearchWorker`). Fix (a) alone should cut it ~10×; (b) removes the freeze.
- **P3 — `scripts/benchmark.py` predates recognition v2.** It measures none of:
  timeline buckets/month page, representatives strip, suggestions, or
  `update_people` matching. Extend it so regressions in the new hot paths are
  visible.
- **P4 — Minor.** `data.similar_photos` (pgvector query) runs on the UI thread in
  `main_window._on_find_similar`; `AppearanceStrip` decodes crops synchronously
  (bounded ≤ ~12 small files — acceptable, but inconsistent with the async-
  everywhere rule); `fetch_person_context_rows` full-scans grouped faces every
  pipeline run (fine now; cache when libraries grow).

## 3. Database

**Good:** idempotent additive schema; every FK indexed or covered by a UNIQUE
prefix; partial indexes for hot subsets (`faces_pending`, representatives);
correct cascade behavior verified by tests; all vector reads handle both
pgvector and list payloads.

- **D1 — Duplicated decoding helpers.** Four identical nested `_to_array`
  functions plus `_embeddings_to_matrix` in `db.py`. Consolidate into one
  module-level helper.
- **D2 — Dead/misleading schema surface.** `photos.clip_embedding vector(768)`
  is unused (real store: `clip_embeddings` at 512-d) and its dimension is wrong
  for the shipped model — a trap for readers. Never drop (project rule), but
  mark it *reserved/unused* in schema comment + DATABASE.md.
- **D3 — ivfflat indexes are built on empty tables.** pgvector's ivfflat chooses
  cluster centers at build time; an index created before data exists gives poor
  recall/latency until rebuilt. There is no post-import `ANALYZE`/`REINDEX`
  step. Add an "optimize after large import" step (ANALYZE + optional REINDEX of
  the two vector indexes), or migrate to HNSW which doesn't have this caveat.
- **D4 — `persons.face_count` is denormalized** with recompute paths but no
  invariant check; drift would silently mis-sort People. Cheap guard: recompute
  in `update_people` backfill or assert equality in a test.
- **D5 — No schema versioning.** Fine while all changes are additive; before
  1.0, adopt a minimal migration convention (numbered SQL files) so a future
  breaking change (e.g. 768-d CLIP model) has a path.

## 4. UI

**Good:** virtualized grids with async decoding everywhere it matters; paged
fetching; pipeline fully off-thread with progress/stop/continue; state restore;
honest "planned" pages; keyboard shortcuts.

- **U1 — Nine synchronous DB writes run in Qt slots** (`pages.py`:
  confirm/reject suggestion, reject representative, remove-from-person, rename,
  delete, merge; `photo_viewer.py`: favorite; `main_window.py`: find-similar
  read). Most are ms-fast, but the four that trigger gallery rebuilds inherit
  P2's ~2 s worst case. One tiny `DbActionWorker` (thread + done-callback)
  covers all of them uniformly.
- **U2 — Inconsistent error strategy.** `_refresh_page` defends against DB
  failure; `_open_person` and the person-action slots do not — a DB hiccup there
  raises inside a Qt slot (window survives, action silently dies, nothing tells
  the user). Route user actions through one guarded path that surfaces a proper
  error dialog/toast.
- **U3 — Favorites inconsistency.** Favorites exist (♥ toggle, search ranking,
  filter) but the sidebar "Favorites" page still says *planned*. It is one
  `photo_grid(favorite=True)` away; either ship the page or hide the entry.
- **U4 — Suggestions are discoverable only per person.** Active-learning
  suggestions appear only when the user opens the right person. The
  `count_suggestions` hook exists for a global "Review (N)" badge — surface it
  (dashboard card or sidebar badge) so the feature actually gets exercised.
- **U5 — No undo.** Destructive actions confirm via dialog but cannot be
  undone. Rejections are stored, so an "undo last correction" is feasible later;
  at minimum keep the confirm dialogs (present) and add toasts.
- **U6 — Polish debt (accepted):** skeleton loading, transitions, i18n
  (hardcoded English), People-page search box. Tracked in ROADMAP Phase A.

## 5. Test coverage

**Good:** 102 tests, all green; pure logic (quality, gallery, context, hashing,
metadata) tested without I/O; DB integration tests skip cleanly when Postgres is
down; Qt tested headlessly with stub backends; determinism pinned (DBSCAN).

Gaps, most valuable first:

- **T1 — Person-correction flows are untested at the widget level.**
  `PersonDetailPage._on_confirm_suggestion` / `_on_reject_suggestion` /
  `_on_remove_from_person` / merge are exercised only through `viewer.data` in
  DB tests; the Qt wiring (signal → handler → reload/back-navigation) has no
  test. These are exactly the paths a threading refactor (U1) could break —
  write them *before* that refactor.
- **T2 — `dropEvent` end-to-end is untested** (only the `_dropped_dirs` filter
  is); `PipelineWorker.failed` path untested; destructive `recluster` after the
  new tables exist (galleries/feedback cascade) untested.
- **T3 — HDBSCAN is pinned out** by conftest for determinism — right call, but
  it means the HDBSCAN branch only runs in one unit test. Acceptable; note it.
- **T4 — No coverage measurement.** `pytest-cov` is not installed and the
  environment is offline; when network is available, add it with a floor (the
  "never reduce coverage" rule needs a number to enforce).
- **T5 — `scripts/` untested** (benchmark, setup_check). Low risk; low priority.

## 6. Prioritized technical-debt register

| # | Item | Refs | Impact | Effort | Priority |
|---|------|------|--------|--------|----------|
| 1 | Batch gallery-rebuild upserts + move person corrections off the UI thread | P2, U1 | UI freezes up to ~2 s on common actions | M | **P0** |
| 2 | Restrict context/rejection scoring to eligible rows (vectorize) | P1 | Pipeline slows 2.6×+, grows O(P×N) | S | **P0** |
| 3 | Widget-level tests for correction flows (before #1's refactor) | T1 | Guards the P0 refactor | S | **P0** |
| 4 | Extract person-action service from `viewer/data.py`; fix stale docstring | A1 | Layering, future features build on it | M | **P1** |
| 5 | `db.py` cleanup: delete dead helper, unify `_to_array`, merge→`recompute_person_profile` | A4, A5, D1 | Duplication, dead code | S | **P1** |
| 6 | Post-import ANALYZE + vector-index rebuild step (or HNSW) | D3 | Search/recognition quality at scale | S | **P1** |
| 7 | Single page-registry (notes/keys/implemented/sidebar) | A2 | Prevents silent page bugs | M | **P1** |
| 8 | Unified error path + guard `_open_person`/action slots | U2 | Silent failures today | S | **P1** |
| 9 | Surface suggestions globally (wire `count_suggestions`) | U4, A5 | Feature discoverability | S | **P2** |
| 10 | Favorites page (feature exists; page says planned) | U3 | UX inconsistency | S | **P2** |
| 11 | Extend benchmark to recognition-v2 paths + timeline | P3 | Regression visibility | S | **P2** |
| 12 | Docs refresh: ROADMAP stale ordering, DATABASE.md helper list, `clip_embedding` note | D2, docs | Accuracy | S | **P2** |
| 13 | `dropEvent`/failed-pipeline/recluster-cascade tests | T2 | Coverage | S | **P2** |
| 14 | face_count invariant check; migration convention pre-1.0; coverage tooling when online; undo/toasts; i18n | D4, D5, T4, U5/U6 | Long-term health | M+ | **P3** |

## Standing constraints (reaffirmed)

These hold everywhere and gate every future change: never reduce test coverage;
never block the UI thread; never introduce cloud dependencies; never bypass
`database/db.py`; maintain full offline functionality; preserve incremental
processing; keep backward compatibility with existing databases unless an
explicit migration is added.

**Recommendation:** execute items 1–3 (P0) as one "performance & safety"
session, then 4–8 (P1) as a refactoring session, then resume feature work
(duplicate detection is next in the queue) on the cleaned foundation.
