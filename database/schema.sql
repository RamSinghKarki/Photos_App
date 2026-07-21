-- PhotoSphere AI — database schema
--
-- The PostgreSQL database is the single source of truth. This file is
-- idempotent: every object uses IF NOT EXISTS, so it can be applied to a fresh
-- database (acts as the installer) or an existing one (acts as a no-op). It
-- NEVER drops a table, so applying it can never destroy user data.
--
-- Design notes:
--   * One photo can contain many faces  -> faces.photo_id references photos.id.
--   * Future modules (OCR, CLIP search, object detection, captions, GPS) attach
--     to a photo WITHOUT altering this schema: they use the nullable columns
--     already present on `photos`, or add their own side tables keyed by
--     photo_id. Nothing here needs a destructive migration to grow.

CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS pg_trgm;   -- fast substring search over OCR text

-- ---------------------------------------------------------------------------
-- photos: one row per unique image file discovered by the scanner.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS photos (
    id              BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,

    -- Identity / dedup
    file_path       TEXT        NOT NULL UNIQUE,   -- absolute path on disk
    file_hash       TEXT        NOT NULL,          -- sha256 of file bytes
    file_size       BIGINT      NOT NULL,
    file_mtime      TIMESTAMPTZ NOT NULL,          -- filesystem modified time

    -- Core image metadata (from EXIF / decoder)
    width           INTEGER,
    height          INTEGER,
    format          TEXT,                          -- e.g. 'JPEG', 'PNG'
    taken_at        TIMESTAMPTZ,                   -- EXIF DateTimeOriginal
    camera_make     TEXT,
    camera_model    TEXT,
    orientation     SMALLINT,                      -- EXIF orientation tag

    -- GPS (present now so Timeline/Map need no migration later)
    gps_latitude    DOUBLE PRECISION,
    gps_longitude   DOUBLE PRECISION,

    -- Future-compatibility columns. Left NULL until the owning module fills
    -- them in; declaring them now means later modules never ALTER this table.
    ocr_text        TEXT,                          -- Module: OCR
    caption         TEXT,                          -- Module: AI captions
    clip_embedding  vector(768),                   -- Module: semantic search

    -- Housekeeping / user-facing state
    is_favorite     BOOLEAN     NOT NULL DEFAULT FALSE,
    thumbnail_path  TEXT,                          -- cached thumbnail (data/)
    faces_processed BOOLEAN     NOT NULL DEFAULT FALSE,  -- has face module run?

    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Indexes for columns queried frequently.
CREATE INDEX IF NOT EXISTS idx_photos_file_hash      ON photos (file_hash);
CREATE INDEX IF NOT EXISTS idx_photos_taken_at       ON photos (taken_at);
CREATE INDEX IF NOT EXISTS idx_photos_is_favorite    ON photos (is_favorite);
CREATE INDEX IF NOT EXISTS idx_photos_faces_pending  ON photos (faces_processed)
    WHERE faces_processed = FALSE;
-- Trigram index for fast substring search over extracted OCR text.
CREATE INDEX IF NOT EXISTS idx_photos_ocr_trgm
    ON photos USING gin (ocr_text gin_trgm_ops);

-- ---------------------------------------------------------------------------
-- faces: one row per detected face. Many faces may point at one photo.
-- The `embedding` dimension matches Settings.embedding_dim (InsightFace = 512).
-- `person_id` is filled by the clustering module; NULL means "not yet grouped".
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS faces (
    id              BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    photo_id        BIGINT      NOT NULL REFERENCES photos (id) ON DELETE CASCADE,

    -- Bounding box within the source image (pixels).
    bbox_x          INTEGER     NOT NULL,
    bbox_y          INTEGER     NOT NULL,
    bbox_w          INTEGER     NOT NULL,
    bbox_h          INTEGER     NOT NULL,

    det_score       REAL,                          -- detector confidence
    embedding       vector(512) NOT NULL,          -- raw InsightFace embedding
    crop_path       TEXT,                          -- cached face crop (data/)

    person_id       BIGINT,                        -- set by clustering module
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_faces_photo_id  ON faces (photo_id);
CREATE INDEX IF NOT EXISTS idx_faces_person_id ON faces (person_id);
-- Approximate-nearest-neighbour index for embedding similarity (cosine).
-- ivfflat needs ANALYZE + data to be effective; harmless when empty.
CREATE INDEX IF NOT EXISTS idx_faces_embedding
    ON faces USING ivfflat (embedding vector_cosine_ops) WITH (lists = 100);

-- ---------------------------------------------------------------------------
-- persons: a group of faces believed to be the same individual (Module 3).
-- Added additively — the faces table already carries person_id, so introducing
-- people needs no destructive change. display_name is user-assignable later.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS persons (
    id              BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    display_name    TEXT,                          -- user-assigned name (later)
    face_count      INTEGER     NOT NULL DEFAULT 0,
    cover_face_id   BIGINT REFERENCES faces (id) ON DELETE SET NULL,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Tie faces.person_id to persons.id. Guarded so the schema stays idempotent
-- (PostgreSQL has no ADD CONSTRAINT IF NOT EXISTS).
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'fk_faces_person'
    ) THEN
        ALTER TABLE faces
            ADD CONSTRAINT fk_faces_person
            FOREIGN KEY (person_id) REFERENCES persons (id) ON DELETE SET NULL;
    END IF;
END$$;

-- Person profile: the running-average embedding of a person's faces. Powers
-- incremental recognition — a new face is matched against these centroids and
-- auto-assigned to a known person, so naming a cluster teaches the app without
-- reclustering everything. Added additively (ADD COLUMN IF NOT EXISTS).
ALTER TABLE persons ADD COLUMN IF NOT EXISTS centroid vector(512);

-- Per-person recognition threshold, derived from how *consistent* that person's
-- representative embeddings are (see clustering/gallery.py). NULL means "use the
-- global default" — a person needs a few representatives before it adapts.
ALTER TABLE persons ADD COLUMN IF NOT EXISTS adaptive_threshold REAL;

-- Perceptual hash (dHash, 64-bit) for visual duplicate detection. Added
-- additively so existing libraries migrate with no data loss; NULL means the
-- duplicates module has not processed the photo yet.
ALTER TABLE photos ADD COLUMN IF NOT EXISTS phash BIGINT;
CREATE INDEX IF NOT EXISTS idx_photos_phash ON photos (phash) WHERE phash IS NOT NULL;

-- Duplicate review outcomes. A photo the user chose NOT to keep points at the
-- photo kept in its place — hidden from the Photos grid, never deleted, and
-- restorable at any time from the Duplicates page. ON DELETE SET NULL keeps
-- hidden photos visible again if their keeper is ever removed.
ALTER TABLE photos ADD COLUMN IF NOT EXISTS duplicate_of BIGINT REFERENCES photos(id) ON DELETE SET NULL;
CREATE INDEX IF NOT EXISTS idx_photos_duplicate_of ON photos (duplicate_of) WHERE duplicate_of IS NOT NULL;

-- Groups the user reviewed and said "these are different photos" — keyed by
-- the sorted member ids so the same set is never asked about again.
CREATE TABLE IF NOT EXISTS duplicate_dismissals (
    group_key   TEXT PRIMARY KEY,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ---------------------------------------------------------------------------
-- person_embeddings: a person's *representative gallery* — a diverse, quality-
-- gated set of face embeddings, not a single average. Recognizing a person
-- across viewpoint / facial hair / glasses / lighting / age works far better by
-- matching a new face against this set (taking the best match) than against one
-- centroid. The centroid on `persons` is kept as a fast secondary signal.
--
-- One row per contributing face (UNIQUE face_id). `quality` (0..1) gates whether
-- a detection is trusted enough to teach; `is_representative` marks the diverse
-- subset actually used for matching. Rows cascade away with their person or face.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS person_embeddings (
    id                BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    person_id         BIGINT      NOT NULL REFERENCES persons (id) ON DELETE CASCADE,
    face_id           BIGINT      NOT NULL REFERENCES faces (id) ON DELETE CASCADE,
    embedding         vector(512) NOT NULL,       -- L2-normalized face embedding
    quality           REAL        NOT NULL DEFAULT 0,  -- 0..1 quality score
    is_representative BOOLEAN     NOT NULL DEFAULT FALSE,
    created_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (face_id)
);
CREATE INDEX IF NOT EXISTS idx_person_embeddings_person
    ON person_embeddings (person_id);
-- Partial index over just the active matching set (small, hot).
CREATE INDEX IF NOT EXISTS idx_person_embeddings_repr
    ON person_embeddings (person_id) WHERE is_representative;

-- ---------------------------------------------------------------------------
-- recognition_feedback: durable memory of the user's corrections so an
-- automatic assignment they already rejected is never repeated. One row per
-- (face, person): verdict 'reject' means "this face is NOT this person" (the
-- recognition engine will never auto-assign it there again); 'confirm' is
-- reserved for an explicit "yes, this is them" signal. Rows cascade away with
-- their face or person.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS recognition_feedback (
    id          BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    face_id     BIGINT      NOT NULL REFERENCES faces (id)   ON DELETE CASCADE,
    person_id   BIGINT      NOT NULL REFERENCES persons (id) ON DELETE CASCADE,
    verdict     TEXT        NOT NULL,          -- 'reject' | 'confirm'
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (face_id, person_id)
);
CREATE INDEX IF NOT EXISTS idx_recognition_feedback_person
    ON recognition_feedback (person_id);

-- ---------------------------------------------------------------------------
-- recognition_suggestions: active learning. A face whose best match to a person
-- lands just *below* that person's acceptance threshold is not auto-assigned,
-- but instead of being silently dropped it is recorded here as a pending
-- question ("Is this <name>?") for the user to confirm or reject. One row per
-- face (its single best borderline candidate). Rows cascade away with the face
-- or person, and are cleared once the face is assigned or the user answers.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS recognition_suggestions (
    id          BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    face_id     BIGINT      NOT NULL REFERENCES faces (id)   ON DELETE CASCADE,
    person_id   BIGINT      NOT NULL REFERENCES persons (id) ON DELETE CASCADE,
    score       REAL        NOT NULL,          -- best cosine to the person
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (face_id)
);
CREATE INDEX IF NOT EXISTS idx_recognition_suggestions_person
    ON recognition_suggestions (person_id);

-- ---------------------------------------------------------------------------
-- person_merge_suggestions: anti-fragmentation. Two persons whose galleries are
-- highly similar are probably the same individual photographed differently
-- (angle / beard / hairstyle). The merge scan refreshes this table after each
-- recognition run; the UI asks "Same person?". Pairs are stored ordered
-- (person_a < person_b) and cascade away with either person.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS person_merge_suggestions (
    id          BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    person_a    BIGINT      NOT NULL REFERENCES persons (id) ON DELETE CASCADE,
    person_b    BIGINT      NOT NULL REFERENCES persons (id) ON DELETE CASCADE,
    score       REAL        NOT NULL,          -- best cross-gallery cosine
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (person_a, person_b),
    CHECK (person_a < person_b)
);

-- The user's "not the same person" answers — a suggested pair rejected once is
-- never suggested (or auto-merged) again.
CREATE TABLE IF NOT EXISTS person_merge_rejections (
    id          BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    person_a    BIGINT      NOT NULL REFERENCES persons (id) ON DELETE CASCADE,
    person_b    BIGINT      NOT NULL REFERENCES persons (id) ON DELETE CASCADE,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (person_a, person_b),
    CHECK (person_a < person_b)
);

-- ---------------------------------------------------------------------------
-- clip_embeddings: per-photo CLIP image embedding for semantic search.
-- Versioned by model so a future model upgrade can tell which embeddings are
-- stale (re-embedding upserts the row). One active model per photo.
-- The vector size MUST match Settings.clip_embedding_dim (512 for ViT-B-32);
-- switching to a different-dimension model requires recreating this table.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS clip_embeddings (
    photo_id    BIGINT PRIMARY KEY REFERENCES photos (id) ON DELETE CASCADE,
    embedding   vector(512) NOT NULL,          -- L2-normalized CLIP image vector
    model       TEXT        NOT NULL,          -- e.g. 'ViT-B-32/openai'
    version     INTEGER     NOT NULL DEFAULT 1,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_clip_model ON clip_embeddings (model, version);
CREATE INDEX IF NOT EXISTS idx_clip_embedding
    ON clip_embeddings USING ivfflat (embedding vector_cosine_ops) WITH (lists = 100);

-- ---------------------------------------------------------------------------
-- scan_runs: an audit log of each scan, powering the processing summary.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS scan_runs (
    id              BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    root_path       TEXT        NOT NULL,
    started_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    finished_at     TIMESTAMPTZ,
    processed       INTEGER     NOT NULL DEFAULT 0,
    skipped         INTEGER     NOT NULL DEFAULT 0,
    duplicates      INTEGER     NOT NULL DEFAULT 0,
    errors          INTEGER     NOT NULL DEFAULT 0
);
