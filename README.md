# PhotoSphere AI

A fully **offline**, AI-powered photo management application for Windows. All
data and all inference stay on the local machine — no cloud, no APIs.

Face recognition is Version 1; the foundation is built so Timeline, Albums,
Search, OCR, and more can be added without redesigning the schema.

## Documentation

| Doc | What's in it |
|-----|--------------|
| [docs/INSTALL.md](docs/INSTALL.md) | Install & first run (Docker or native, GPU setup) |
| [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) | How it all fits together — layers, data flow, threading, scale |
| [docs/DATABASE.md](docs/DATABASE.md) | Schema reference (tables, indexes, helpers, queries) |
| [docs/AI_PIPELINE.md](docs/AI_PIPELINE.md) | Face + CLIP search pipeline; the modular embedding architecture |
| [docs/LEARNING.md](docs/LEARNING.md) | Self-improving recognition — person profiles, incremental learning |
| [docs/DEVELOPMENT.md](docs/DEVELOPMENT.md) | Contributor guide — layout, tests, conventions, adding a module |
| [docs/PERFORMANCE.md](docs/PERFORMANCE.md) | How to profile (PHOTOSPHERE_PERF) + the measured optimizations |
| [docs/ROADMAP.md](docs/ROADMAP.md) | Path to v1.0 — milestones, targets, decisions |
| [docs/PhotoSphere_AI_System_Prompt.md](docs/PhotoSphere_AI_System_Prompt.md) | Project vision, architecture rules, per-module Definition of Done |

## Module status

| # | Module              | Status         |
|---|---------------------|----------------|
| — | Foundation (config, logging, database) | ✅ Done |
| 1 | **Scanner**         | ✅ Done         |
| 2 | **Faces (InsightFace)** | ✅ Done     |
| 3 | **Clustering**      | ✅ Done         |
| 4 | **Viewer (PySide6/Qt)** | ✅ Done     |

## Tech stack

Python 3.12 · PostgreSQL + pgvector · InsightFace (later) · FastAPI (later) ·
PySide6 / Qt native desktop UI (later). See the system prompt for the full,
fixed stack.

## Project layout

```
config/       application settings (env-overridable)
database/     schema.sql (single source of truth) + named DB helpers (db.py)
scanner/      Module 1: directory scan + EXIF/metadata extraction
faces/        Module 2 (empty until built)
clustering/   Module 3 (empty until built)
viewer/       Module 4 (empty until built)
utils/        cross-cutting helpers (logging)
scripts/      command-line entry points
data/         generated artifacts (thumbnails, face_crops) — never originals
logs/         photosphere.log (rotating)
tests/        pytest suite
docs/         system prompt + module docs
```

## Setup

See **[docs/INSTALL.md](docs/INSTALL.md)** for full, step-by-step instructions
(Docker or native, Windows/Linux). Quick version:

1. **Start PostgreSQL + pgvector.** Easiest is Docker (runs only the database):

   ```bash
   docker compose up -d      # PostgreSQL 18 + pgvector on localhost:5432
   ```

   This creates the `photosphere` database with the extension enabled and uses
   the app's default credentials, so no further DB config is needed. (Prefer a
   native install? See docs/INSTALL.md.)

2. **Install Python dependencies** (Python 3.12):

   ```bash
   pip install -r requirements.txt
   ```

3. **Configure connection** — only if you are *not* using the bundled Docker
   defaults. Override via environment variables:

   ```
   PHOTOSPHERE_DB_HOST=localhost
   PHOTOSPHERE_DB_PORT=5432
   PHOTOSPHERE_DB_NAME=photosphere
   PHOTOSPHERE_DB_USER=postgres
   PHOTOSPHERE_DB_PASSWORD=postgres
   ```

The schema is applied automatically (idempotently) the first time you scan.

## Usage — Module 1: Scanner

Scan a folder of photos into the database:

```bash
python -m scripts.scan "C:\Users\me\Pictures"
```

Options: `--batch-size N` (rows committed per transaction), `--log-level DEBUG`.

### Expected output

A processing summary is always printed:

```
Processed:   2405
Skipped:       13
Duplicates:    52
Errors:         4
```

- **Processed** — new photos stored this run.
- **Skipped** — paths already in the database (safe re-scan).
- **Duplicates** — stored photos whose bytes match another photo (same SHA-256).
- **Errors** — files that could not be read at all (still logged, never fatal).

Logs are written to both the console and `logs/photosphere.log`.

### How to verify correctness

```bash
pytest -q
```

Or inspect the database directly:

```sql
SELECT count(*) FROM photos;
SELECT file_path, taken_at, camera_model, gps_latitude FROM photos LIMIT 5;
SELECT * FROM scan_runs ORDER BY id DESC LIMIT 1;   -- the run summary
```

### Common errors

- `psycopg2.OperationalError: connection refused` — PostgreSQL isn't running or
  the `PHOTOSPHERE_DB_*` settings are wrong.
- `extension "vector" is not available` — pgvector isn't installed for your
  PostgreSQL server.
- `Scan root is not a directory` — the path passed to the scanner doesn't exist.

### How to undo a scan

Scanning only inserts rows; it never deletes files. To clear scanned data:

```sql
TRUNCATE faces, photos, scan_runs RESTART IDENTITY CASCADE;
```

The `data/` and `logs/` directories hold only generated artifacts and can be
deleted safely; they are recreated on the next run.

## Usage — Module 2: Faces

After scanning, detect faces and store their embeddings. Detection runs
**locally** via InsightFace on the GPU (automatic CPU fallback):

```bash
python -m scripts.detect_faces                 # process newly scanned photos
python -m scripts.detect_faces --limit 5000    # bounded batch
python -m scripts.detect_faces --reprocess     # re-examine every photo
```

Face-related settings (all env-overridable): `PHOTOSPHERE_FACE_MODEL`
(default `buffalo_l`), `PHOTOSPHERE_FACE_CTX_ID` (GPU id; `-1` forces CPU),
`PHOTOSPHERE_FACE_DET_SIZE` (default `640`), `PHOTOSPHERE_FACE_MIN_SCORE`
(default `0.50`).

On first run InsightFace downloads its model pack (a one-time local download);
after that it is fully offline.

### Expected output

```
Photos processed: 2380
Faces found:      5127
No faces:         241
Unreadable:       12
Errors:           0
```

- **Photos processed** — images opened and run through the detector.
- **Faces found** — face rows stored (a photo may contribute several).
- **No faces** — processed images where the detector found nobody.
- **Unreadable** — files that could not be opened (corrupt/missing); marked
  processed so they are not retried every run (`--reprocess` forces a retry).
- **Errors** — unexpected failures (e.g. database); should be `0`.

Each face is stored with its bounding box, detector score, **raw** embedding
(`vector(512)`), and a cached crop under `data/face_crops/`. Embeddings are
stored exactly as the model produces them; normalization for similarity happens
at query time via the cosine (`<=>`) index.

### How to verify correctness

```bash
pytest -q          # includes stub-detector tests for the whole face pipeline
```

```sql
SELECT count(*) FROM faces;
SELECT photo_id, det_score FROM faces ORDER BY id LIMIT 5;
-- faces most similar to a given face (cosine distance):
SELECT id FROM faces ORDER BY embedding <=> (SELECT embedding FROM faces WHERE id = 1) LIMIT 5;
```

### How to undo face processing

```sql
TRUNCATE faces RESTART IDENTITY;
UPDATE photos SET faces_processed = FALSE;
```

Then delete cached crops if desired: everything under `data/face_crops/` is
regenerable and safe to remove.

## Usage — Module 3: Clustering

Group detected faces into people. This reads every stored embedding, clusters
them, and fills each face's `person_id` (creating `persons` rows):

```bash
python -m scripts.cluster_faces
python -m scripts.cluster_faces --eps 0.30 --min-samples 4
python -m scripts.cluster_faces --algorithm hdbscan   # if hdbscan is installed
```

Clustering runs over **cosine distance** on unit-normalized embeddings. The
engine is chosen by `--algorithm` / `PHOTOSPHERE_CLUSTER_ALGORITHM`:
`auto` (default — **HDBSCAN** if the optional `hdbscan` package is installed,
otherwise **DBSCAN**), `hdbscan`, or `dbscan`. HDBSCAN handles clusters of
varying density and needs no `eps`. Tuning (env-overridable):
`PHOTOSPHERE_CLUSTER_EPS` (DBSCAN radius, default `0.35`; lower = stricter) and
`PHOTOSPHERE_CLUSTER_MIN_SAMPLES` (min cluster size, default `3`). Ambiguous
faces are left **ungrouped** (`person_id = NULL`) instead of being misfiled.

### Expected output

```
Faces:      5127
People:     214
Grouped:    4903
Ungrouped:  224
```

### How to verify correctness

```bash
pytest -q
```

```sql
SELECT count(*) FROM persons;
SELECT p.id, p.face_count, p.cover_face_id
  FROM persons p ORDER BY p.face_count DESC LIMIT 10;   -- biggest people
SELECT count(*) FROM faces WHERE person_id IS NULL;      -- ungrouped faces
```

### How to undo clustering

```sql
DELETE FROM persons;   -- the ON DELETE SET NULL FK clears faces.person_id too
```

Re-running `cluster_faces` is a full re-cluster: it rebuilds `persons` from
scratch each time, so it is safe to run repeatedly while tuning `--eps`.

## Usage — Module 4: Viewer (desktop app)

Just launch the app — the whole pipeline runs from inside it:

```bash
python -m scripts.app
```

Then click **Import Folder** (`Ctrl+O`) and pick a folder. Everything runs in
the background with a live progress bar in the status bar:

> **scan → thumbnails → face detection (GPU) → clustering**

The window stays responsive throughout, and the gallery/People/Dashboard refresh
automatically when it finishes. **Re-index** (`Ctrl+R`) re-runs thumbnails + AI
over the photos you already imported. You never need the command line.

*(The individual `scripts.scan` / `detect_faces` / `cluster_faces` /
`generate_thumbnails` commands still exist for automation/headless use, but the
app does all of it for you.)*

What works today:
- **Fluent dark UI** — soft surfaces, drawn line-art icons (no emoji), pill
  search, accent-highlighted navigation.
- **Background pipeline** — Import / Re-index run off the UI thread with a
  progress bar, **percent, elapsed timer and ETA**, and per-stage status; the
  **GPU badge** shows whether face detection will use CUDA or CPU.
- **Stop / Continue** — **Stop** cancels a running pipeline cleanly (at the next
  progress tick); because every stage is idempotent, **Continue** resumes from
  exactly where it stopped — no work is repeated beyond the last partial batch.
- **Dashboard** — stat tiles (photos, faces, people, storage) and recent scans.
- **Photos** — a virtualized grid with **incremental paging** (loads a page at a
  time as you scroll) and **off-thread thumbnail decoding**, so it stays smooth
  on 100k+ libraries. `+` / `-` zoom; double-click or Enter opens the viewer.
- **People** — virtualized person cards with circular cover faces; click to see
  that person's photos. On a person you can **Rename**, **Merge…** into another
  person (their faces move over), or **Delete** the group (photos/faces are
  kept — only the grouping is removed).
- **Self-improving recognition** — naming a person **teaches** the app: on the
  next Import/Re-index, new faces of that person are recognized automatically
  and folded into their profile. Updates are **incremental and name-preserving**
  (existing people/names are never wiped; only new faces are matched or grouped).
  A full destructive rebuild is opt-in: `python -m scripts.cluster_faces --rebuild`.
  See [docs/LEARNING.md](docs/LEARNING.md).
- **Manual face detection** — select one or more photos in the grid
  (click, `Ctrl`/`Shift`-click, or `Ctrl+A`), **right-click → "Detect faces on
  N selected"**, and it runs detection on just those photos and regroups people.
  Re-running on a photo replaces its old faces. Works in the Photos grid and on
  a person's photos.
- **Photo viewer** — full-resolution image with a collapsible metadata panel
  (camera, date, dimensions, GPS, …); `←`/`→` navigate, `I` toggles the panel,
  `F11` full screen, `Esc` closes.
- **Search (semantic)** — the **Search** tab does natural-language search over
  your photos with CLIP ("dog on a beach", "sunset", "passport"). Import /
  Re-index build the index (the "Indexing search" stage); queries run on a
  background thread. Needs `open_clip_torch` + PyTorch — the tab explains how to
  enable it if absent. The modular embedding architecture (backend interface,
  versioned embeddings, text cache) is documented in
  [docs/AI_PIPELINE.md](docs/AI_PIPELINE.md). The top bar still does a quick
  filename/camera filter as you type.
- **Resumes where you left off** — window size/position, the last page you were
  on, and the gallery zoom are remembered between launches (via native
  per-user settings), and the Import dialog reopens at your last folder.

Keyboard: `Ctrl+O` import · `Ctrl+R` re-index · `Ctrl+F` search · `Ctrl+Q` quit
· `+`/`-` zoom grid · `F11` full screen · `←`/`→` prev/next in viewer · `Esc`
close.

### GPU

Face detection runs on the GPU via `onnxruntime-gpu` (with automatic CPU
fallback). The status bar's **GPU** badge reports the detected device — it uses
PyTorch if present, otherwise the onnxruntime CUDA provider. If it shows
"CPU only" but you have an NVIDIA GPU, install `onnxruntime-gpu` (not the CPU
`onnxruntime`).

Sidebar sections tied to not-yet-built backend modules (Timeline, Videos,
Search, Objects, Similar, Albums, Favorites, Archive, Trash, Settings) show an
honest "planned" page rather than faking functionality.

### How to verify correctness

```bash
pytest -q     # includes headless (offscreen) Qt + pipeline-worker tests
```

Face detection needs the InsightFace model (and ideally a GPU), but everything
else — scan, thumbnails, clustering, the background pipeline worker, and the
whole UI — runs and is tested headlessly.

## Design notes / known limitations

**Module 1 (Scanner)**
- Duplicate detection is **exact** (byte-for-byte SHA-256). Near-duplicate and
  perceptual matching is a separate, later module.
- Moved/renamed files are treated as new photos on the next scan (the old path
  simply stops being found); a reconciliation pass can be added later.
- Only still images are scanned. Video support is a future module.
- The face and clustering columns/tables already exist in the schema so later
  modules need no migration; they are simply unused until built.

**Module 2 (Faces)**
- Unreadable images are marked processed to avoid infinite retries; use
  `--reprocess` after fixing/replacing a file to re-examine it.
- The detector is injected behind the `FaceDetector` interface, so the whole
  pipeline is tested with a stub. The real InsightFace model requires its
  one-time model download and is best exercised on the target GPU machine.

**Module 3 (Clustering)**
- Clustering is a full **re-cluster** each run: simple and deterministic, but
  it loads all embeddings into memory. Incremental assignment of only-new
  faces to their nearest existing person (using the pgvector index) is a future
  optimization the schema already supports.
- DBSCAN groups by single-linkage density; very lookalike people can merge and
  very sparse faces stay ungrouped. Tune `--eps` / `--min-samples` per library.

**Module 4 (Viewer)**
- The gallery uses incremental paging + off-thread thumbnail decoding, so it
  stays responsive on large libraries. Clustering during Import still loads all
  embeddings into memory (see Module 3) — incremental clustering is future work.
- Import / Re-index run the full pipeline (scan → thumbnails → faces →
  clustering) in the background. If the InsightFace model isn't installed, the
  face/cluster stages are skipped and the rest still completes.
- Person renaming/merge, favorites, albums, trash, and semantic search are
  shown as planned sections — their backend modules are not built yet.

## Performance notes

Design choices that keep the pipeline scalable to 100k–500k photos:
- **Scanner** streams the filesystem with a generator (flat memory) and, for
  typical-sized images, reads each new file **once** for both hashing and
  decoding instead of twice.
- **Faces** stream pending photos through a server-side cursor (memory stays
  flat regardless of library size) and commit in configurable batches, with a
  per-photo savepoint so one bad file never rolls back a whole batch.
- All frequently-queried columns are indexed, and face similarity uses the
  pgvector cosine index.
