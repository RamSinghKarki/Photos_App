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
