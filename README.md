# PhotoSphere AI

A fully **offline**, AI-powered photo management application for Windows. All
data and all inference stay on the local machine — no cloud, no APIs.

The full project vision, architecture rules, and per-module Definition of Done
live in [`docs/PhotoSphere_AI_System_Prompt.md`](docs/PhotoSphere_AI_System_Prompt.md).
Face recognition is Version 1; the foundation is built so Timeline, Albums,
Search, OCR, and more can be added without redesigning the schema.

## Module status

| # | Module              | Status         |
|---|---------------------|----------------|
| — | Foundation (config, logging, database) | ✅ Done |
| 1 | **Scanner**         | ✅ Done         |
| 2 | **Faces (InsightFace)** | ✅ Done     |
| 3 | Clustering          | ⬜ Not started  |
| 4 | Viewer (PySide6/Qt) | ⬜ Not started  |

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

1. **PostgreSQL** with the `pgvector` extension must be installed and running.
   On Windows, install PostgreSQL 16 and the pgvector extension.

2. **Create the database** (one time):

   ```bash
   createdb photosphere
   ```

3. **Install Python dependencies** (Python 3.12):

   ```bash
   pip install -r requirements.txt
   ```

4. **Configure connection** (optional — defaults shown). Override with
   environment variables so credentials never live in the repo:

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
- Each `faces` row already has a nullable `person_id`; grouping faces into
  people is **Module 3 (Clustering)** and is not done here.
- Unreadable images are marked processed to avoid infinite retries; use
  `--reprocess` after fixing/replacing a file to re-examine it.
- The detector is injected behind the `FaceDetector` interface, so the whole
  pipeline is tested with a stub. The real InsightFace model requires its
  one-time model download and is best exercised on the target GPU machine.
