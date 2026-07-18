# PhotoSphere AI — Installation & First Run

PhotoSphere AI runs **100% locally**. Nothing here contacts the cloud. Target
platform is Windows with an NVIDIA GPU, but it also runs CPU-only (slower face
detection) and on Linux/macOS.

---

## 1. Prerequisites

| Component   | Version            | Notes                                              |
|-------------|--------------------|----------------------------------------------------|
| Python      | 3.12               | `python --version`                                 |
| PostgreSQL  | 16 (14+ works)     | with the **pgvector** extension                    |
| GPU (opt.)  | NVIDIA + CUDA      | for fast face detection; CPU fallback works        |
| Git         | any                | to clone the repo                                  |

---

## 2. Install PostgreSQL + pgvector

1. Install **PostgreSQL 16** from https://www.postgresql.org/download/windows/
   and remember the password you set for the `postgres` user.

2. Install the **pgvector** extension:
   - Easiest on Windows: grab a prebuilt `vector` build matching your
     PostgreSQL version from the pgvector releases
     (https://github.com/pgvector/pgvector/releases) and copy its files into
     your PostgreSQL `lib\` and `share\extension\` folders, **or** build it with
     MSVC per the pgvector README.
   - On Linux: `sudo apt install postgresql-16-pgvector`.

3. Create the database (from a terminal / psql shell):

   ```bash
   createdb -U postgres photosphere
   ```

   The `vector` extension itself is enabled automatically by the app the first
   time it applies the schema (`CREATE EXTENSION IF NOT EXISTS vector`).

---

## 3. Get the code and a virtual environment

```bash
git clone <your-repo-url> PhotoSphere_AI
cd PhotoSphere_AI

python -m venv .venv
# Windows:
.venv\Scripts\activate
# Linux/macOS:
# source .venv/bin/activate
```

---

## 4. Install Python dependencies

```bash
pip install -r requirements.txt
```

**GPU vs CPU for face detection:** `requirements.txt` lists `onnxruntime-gpu`.
If you do **not** have an NVIDIA GPU, install the CPU runtime instead:

```bash
pip uninstall -y onnxruntime-gpu
pip install onnxruntime
```

The face detector falls back to CPU automatically either way.

---

## 5. Configure the database connection

Defaults are `localhost:5432`, database `photosphere`, user/password
`postgres`/`postgres`. Override any of them with environment variables so
credentials never live in the code.

**Windows (PowerShell):**
```powershell
$env:PHOTOSPHERE_DB_HOST     = "localhost"
$env:PHOTOSPHERE_DB_PORT     = "5432"
$env:PHOTOSPHERE_DB_NAME     = "photosphere"
$env:PHOTOSPHERE_DB_USER     = "postgres"
$env:PHOTOSPHERE_DB_PASSWORD = "your-postgres-password"
```

**Linux/macOS (bash):**
```bash
export PHOTOSPHERE_DB_PASSWORD="your-postgres-password"
```

(To make these permanent on Windows, set them in *System → Environment
Variables* or a `.env` you load before launching.)

---

## 6. Run the pipeline

Each step is safe to re-run; they only add new work.

```bash
# 1. Index a folder of photos (metadata + dedup into PostgreSQL)
python -m scripts.scan "C:\Users\me\Pictures"

# 2. Detect faces + store embeddings (downloads the InsightFace model once)
python -m scripts.detect_faces

# 3. Group faces into people
python -m scripts.cluster_faces

# 4. Generate gallery thumbnails
python -m scripts.generate_thumbnails

# 5. Launch the desktop app
python -m scripts.app
```

Inside the app you can also use **Import Folder** (`Ctrl+O`), which runs the
scan + thumbnailing in the background; run steps 2–3 afterward to refresh
faces/people.

---

## 7. Verify the install

```bash
pip install pytest
pytest -q
```

The suite runs against a throwaway `photosphere_test` database (override with
`PHOTOSPHERE_DB_NAME`). Database and Qt tests **skip cleanly** if PostgreSQL or
PySide6 are unavailable, so a green run confirms whatever is installed works.

---

## Troubleshooting

| Symptom | Fix |
|---------|-----|
| `connection refused` | PostgreSQL isn't running, or `PHOTOSPHERE_DB_*` is wrong. |
| `extension "vector" is not available` | pgvector isn't installed for your PostgreSQL server (step 2). |
| `password authentication failed` | Set `PHOTOSPHERE_DB_PASSWORD` to your `postgres` password. |
| Face step is very slow / no GPU | Install `onnxruntime` (CPU) or set `PHOTOSPHERE_FACE_CTX_ID=-1`. |
| Qt app won't start on a headless server | Set `QT_QPA_PLATFORM=offscreen` (for tests/CI only; the real app needs a desktop). |

See `README.md` for per-module usage, tuning flags, and how to undo each step.
