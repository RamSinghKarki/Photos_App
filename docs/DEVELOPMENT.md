# PhotoSphere AI — Developer Guide

How the codebase is organized, how to run and test it, and the conventions to
follow when extending it. For the big picture see
[ARCHITECTURE.md](ARCHITECTURE.md); for the schema see [DATABASE.md](DATABASE.md).

---

## Project layout

```
config/        settings.py — env-overridable configuration
utils/         logging_setup.py — dual file+console logging
database/      schema.sql (source of truth) + db.py (named helpers)
scanner/       Module 1 — metadata.py, scanner.py
thumbnails/    generator.py — cached grid thumbnails
faces/         Module 2 — detector.py (InsightFace behind a protocol), processor.py
clustering/    Module 3 — clusterer.py (DBSCAN), processor.py
viewer/        Module 4 — the PySide6/Qt app
  ├─ app.py            bootstrap (QApplication + theme + schema)
  ├─ main_window.py    shell: top bar + sidebar + pages + status bar
  ├─ pages.py          Dashboard / Gallery / People / Person detail
  ├─ gallery.py        virtualized, paged grid + async thumbnails
  ├─ photo_viewer.py   full-res viewer + metadata panel
  ├─ components.py     Sidebar, TopBar, StatusBar, cards, PersonCard …
  ├─ tasks.py          PipelineWorker (background scan→…→cluster)
  ├─ data.py           read-only DB access for the UI
  ├─ state.py          persistent UI state (QSettings)
  ├─ gpuinfo.py        GPU/CUDA detection
  ├─ theme.py          Fluent dark stylesheet + palette
  ├─ icons.py          drawn line-art icons
  └─ flow_layout.py    wrapping layout for the People grid
scripts/       CLIs + the app entry point + setup_check
tests/         pytest suite (unit + DB integration + headless Qt)
data/          generated caches: thumbnails/, face_crops/ (git-ignored)
logs/          photosphere.log (git-ignored)
docs/          this documentation
```

Dependency direction is strictly downward: `viewer` → `viewer.data` →
`database.db`; pipeline stages depend on `database.db` + `config` only. Nothing
outside `viewer/` imports Qt.

---

## Environment

- **Python 3.12**, PostgreSQL 14–18 with pgvector.
- Install: `pip install -r requirements.txt` (+ `pytest` for tests).
- Fastest database for development is the bundled container:
  `docker compose up -d` (see [INSTALL.md](INSTALL.md)).
- Connection is configured via `PHOTOSPHERE_DB_*` env vars (defaults match the
  Docker compose file). Run `python -m scripts.setup_check` to verify DB + GPU.

---

## Running

```bash
# The app does everything (Import Folder runs the whole pipeline):
python -m scripts.app

# Or drive stages individually (useful for automation/headless):
python -m scripts.scan "/path/to/photos"
python -m scripts.generate_thumbnails
python -m scripts.detect_faces
python -m scripts.cluster_faces
```

---

## Testing

```bash
pytest -q
```

The suite (10 modules) mixes three kinds of tests:

- **Pure unit** — no DB/Qt (e.g. `test_metadata.py`, `test_clustering.py`'s
  pure-function tests, `test_components.py`).
- **DB integration** — run against a throwaway `photosphere_test` database
  (override with `PHOTOSPHERE_DB_NAME`). They **skip cleanly** if PostgreSQL is
  unreachable, via the `clean_db` fixture in `tests/conftest.py`, which also
  truncates tables between tests.
- **Headless Qt** — set `QT_QPA_PLATFORM=offscreen` (the test modules do this at
  import) and build real widgets/workers with no display. A stub `FaceDetector`
  stands in for InsightFace, so the whole pipeline is exercised without a GPU.

Conventions:
- New DB-touching tests use the `clean_db` and `photo_tree` fixtures.
- Face/pipeline tests inject a stub detector via `detector_factory` — never the
  real model.
- Prefer asserting observable behavior (row counts, emitted signals, summary
  counters) over internals.

---

## Verifying the GUI without a display

There is no monitor in CI, so the UI is verified by rendering it **offscreen**:
build the window under `QT_QPA_PLATFORM=offscreen` and `grab()` it to a PNG.
Because thumbnails decode asynchronously, a two-pass grab is used (first pass
enqueues decodes, wait for the `QThreadPool`, second pass paints). See the
smoke tests in `tests/test_viewer_smoke.py` for the construction/navigation
checks.

---

## Coding conventions

- Python 3.12, PEP 8, type hints and docstrings on public functions.
- Functions stay small; comment **why**, not what.
- **No inline SQL** outside `database/db.py` — add a named helper instead.
- **No cloud/API calls** — all inference is local. Do not add cloud SDKs.
- Long work goes on a `QThread`/`QThreadPool`; touch widgets only on the GUI
  thread; return results via signals.
- Keep the schema idempotent and additive (see below). Never drop a table.
- Every user-facing operation should be cancel-safe and resumable where it
  makes sense (idempotent stages + batched commits).

---

## Adding a new pipeline module (pattern)

New AI stages are added as **plugins** — see [PLUGINS.md](PLUGINS.md) for the
plugin contract and a worked object-detection example. The per-module shape
below still applies to the processor a plugin wraps — e.g. adding OCR:

1. **Schema:** the `photos.ocr_text` column already exists. If you need a side
   table, add it to `schema.sql` with `IF NOT EXISTS` (additive, never destructive).
2. **DB helpers:** add named functions to `database/db.py` (a streaming
   `stream_photos_pending_ocr`, a `set_ocr_text`, a `count_*`).
3. **Processor:** create `ocr/processor.py` that streams pending photos on a read
   connection, writes on a separate connection in batches, isolates per-photo
   failures, accepts an optional `on_progress(done, total)` callback, and returns
   a summary dataclass. Model it on `thumbnails/generator.py`.
4. **Hide heavy deps** behind an interface/lazy import so tests can stub them.
5. **Wire the UI:** add a stage to `viewer/tasks.PipelineWorker`, or a manual
   action, and (if it has a page) unhide the sidebar key in `viewer/theme.py`'s
   `IMPLEMENTED_PAGES` and add a page in `viewer/pages.py`.
6. **CLI:** add `scripts/<name>.py` mirroring the others.
7. **Tests:** a pure test for the algorithm + a DB-integration test using the
   `clean_db`/`photo_tree` fixtures and a stub for the heavy dependency.
8. **Docs:** update this file, [DATABASE.md](DATABASE.md), and the README.

---

## Git

Development happens on a feature branch. Commits are descriptive and scoped
(`feat(viewer): …`, `feat: Module N …`). Run `pytest -q` before committing;
keep generated artifacts (`data/`, `logs/`, `__pycache__`) out of commits (they
are git-ignored).
