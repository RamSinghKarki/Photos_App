"""Central configuration for PhotoSphere AI.

All tunable settings live here so that no module has to hard-code paths,
credentials, or magic numbers. Every value can be overridden with an
environment variable, which keeps secrets (like the database password) out
of the source tree and makes the app portable across machines.

This module is import-safe: importing it never touches the disk or the
database. Call :func:`get_settings` to obtain a cached, validated instance.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

from utils.paths import PROJECT_ROOT, user_data_dir  # noqa: E402


def _env_str(name: str, default: str) -> str:
    """Return an environment override for ``name`` or ``default``."""
    value = os.environ.get(name)
    return value if value is not None and value != "" else default


def _env_int(name: str, default: int) -> int:
    """Return an integer environment override, falling back to ``default``.

    A malformed value is ignored rather than crashing startup — we would
    rather run with a safe default than refuse to boot over a typo.
    """
    raw = os.environ.get(name)
    if raw is None or raw == "":
        return default
    try:
        return int(raw)
    except ValueError:
        return default


@dataclass(frozen=True)
class DatabaseSettings:
    """PostgreSQL connection parameters.

    Defaults target a local development database. Override via environment
    variables (``PHOTOSPHERE_DB_*``) in real deployments so credentials never
    live in the repository.
    """

    host: str = field(default_factory=lambda: _env_str("PHOTOSPHERE_DB_HOST", "localhost"))
    port: int = field(default_factory=lambda: _env_int("PHOTOSPHERE_DB_PORT", 5432))
    name: str = field(default_factory=lambda: _env_str("PHOTOSPHERE_DB_NAME", "photosphere"))
    user: str = field(default_factory=lambda: _env_str("PHOTOSPHERE_DB_USER", "postgres"))
    password: str = field(default_factory=lambda: _env_str("PHOTOSPHERE_DB_PASSWORD", "postgres"))

    @property
    def dsn(self) -> str:
        """Return a libpq connection string for psycopg2."""
        return (
            f"host={self.host} port={self.port} dbname={self.name} "
            f"user={self.user} password={self.password}"
        )


@dataclass(frozen=True)
class Settings:
    """Top-level application settings.

    Attributes:
        database: PostgreSQL connection parameters.
        data_dir: Root for generated artifacts (never the user's originals).
        thumbnails_dir: Where browsing thumbnails are cached.
        face_crops_dir: Where cropped face images are cached.
        logs_dir: Where the rotating log file is written.
        log_level: Logging verbosity (e.g. ``"INFO"``, ``"DEBUG"``).
        scan_batch_size: How many photos to commit per database transaction.
        image_extensions: Lower-case file suffixes treated as photos.
        embedding_dim: InsightFace embedding length (fixed for the schema).
    """

    database: DatabaseSettings = field(default_factory=DatabaseSettings)

    # Generated artifacts live under a writable base: the project directory in
    # development, a per-user OS location when frozen (see utils.paths). This is
    # what makes an installed build write to %LOCALAPPDATA% instead of the
    # read-only Program Files install dir.
    data_dir: Path = field(default_factory=lambda: user_data_dir() / "data")
    thumbnails_dir: Path = field(default_factory=lambda: user_data_dir() / "data" / "thumbnails")
    face_crops_dir: Path = field(default_factory=lambda: user_data_dir() / "data" / "face_crops")
    logs_dir: Path = field(default_factory=lambda: user_data_dir() / "logs")
    # Regenerable caches (text-embedding cache, etc.) — never authoritative.
    cache_dir: Path = field(default_factory=lambda: user_data_dir() / "cache")

    log_level: str = field(default_factory=lambda: _env_str("PHOTOSPHERE_LOG_LEVEL", "INFO"))
    scan_batch_size: int = field(default_factory=lambda: _env_int("PHOTOSPHERE_SCAN_BATCH_SIZE", 200))

    # InsightFace's default recognition models produce 512-d embeddings. The
    # database vector column is sized from this value, so it must match the
    # model actually used in Module 2.
    embedding_dim: int = field(default_factory=lambda: _env_int("PHOTOSPHERE_EMBEDDING_DIM", 512))

    # --- Face module (Module 2) ---------------------------------------------
    # InsightFace model pack name. "buffalo_l" is the standard 512-d pack.
    face_model_name: str = field(default_factory=lambda: _env_str("PHOTOSPHERE_FACE_MODEL", "buffalo_l"))
    # ctx_id >= 0 selects that GPU device; -1 forces CPU. The detector still
    # falls back to CPU automatically if the GPU providers are unavailable.
    face_ctx_id: int = field(default_factory=lambda: _env_int("PHOTOSPHERE_FACE_CTX_ID", 0))
    # Square detection size fed to the model; larger finds smaller faces.
    face_det_size: int = field(default_factory=lambda: _env_int("PHOTOSPHERE_FACE_DET_SIZE", 640))
    # Detections below this confidence are discarded.
    face_min_score: float = field(
        default_factory=lambda: float(_env_str("PHOTOSPHERE_FACE_MIN_SCORE", "0.50"))
    )

    # --- Clustering module (Module 3) ---------------------------------------
    # DBSCAN neighbourhood radius as a *cosine distance* (1 - cosine similarity)
    # on unit-normalized embeddings. Smaller = stricter (fewer faces merged).
    cluster_eps: float = field(
        default_factory=lambda: float(_env_str("PHOTOSPHERE_CLUSTER_EPS", "0.35"))
    )
    # Minimum faces in a neighbourhood to form a person; others become noise
    # (left ungrouped rather than forced into a wrong person).
    cluster_min_samples: int = field(
        default_factory=lambda: _env_int("PHOTOSPHERE_CLUSTER_MIN_SAMPLES", 3)
    )
    # Clustering algorithm: "auto" (HDBSCAN if installed, else DBSCAN),
    # "hdbscan", or "dbscan". HDBSCAN handles varying densities and needs no eps.
    cluster_algorithm: str = field(
        default_factory=lambda: _env_str("PHOTOSPHERE_CLUSTER_ALGORITHM", "auto").lower()
    )
    # Cosine-similarity threshold above which a new face is auto-assigned to an
    # existing person's centroid (incremental recognition). Higher = stricter /
    # fewer false matches. Faces below it are left for clustering.
    face_match_threshold: float = field(
        default_factory=lambda: float(_env_str("PHOTOSPHERE_FACE_MATCH_THRESHOLD", "0.55"))
    )

    # Threads decoding images ahead of the consumer (thumbnailer, face detector,
    # CLIP). Decode is the pipeline's real bottleneck — the GPU finishes in
    # milliseconds and idles while Python opens the next JPEG; overlapping
    # decode keeps it fed. Bounded by prefetch depth so memory stays flat.
    decode_workers: int = field(
        default_factory=lambda: _env_int(
            "PHOTOSPHERE_DECODE_WORKERS", min(8, os.cpu_count() or 4)
        )
    )

    # --- Recognition engine v2 (representative gallery) ---------------------
    # Minimum face quality (0..1) to *store* an embedding in a person's gallery.
    # Below this a detection is ignored — a blurry/tiny/low-confidence face must
    # never teach a profile. See clustering/quality.py.
    face_quality_store_min: float = field(
        default_factory=lambda: float(_env_str("PHOTOSPHERE_FACE_QUALITY_STORE_MIN", "0.35"))
    )
    # Preferred minimum quality for a *representative* (the diverse matching set).
    # Relaxed automatically if a person has too few good faces.
    face_quality_learn_min: float = field(
        default_factory=lambda: float(_env_str("PHOTOSPHERE_FACE_QUALITY_LEARN_MIN", "0.55"))
    )
    # Cap on representatives kept per person (a diverse set of appearances).
    person_max_representatives: int = field(
        default_factory=lambda: _env_int("PHOTOSPHERE_PERSON_MAX_REPRESENTATIVES", 12)
    )
    # Two representatives more similar than this are near-duplicates; keep only
    # the higher-quality one so the gallery stays *diverse*, not redundant.
    representative_diversity_sim: float = field(
        default_factory=lambda: float(_env_str("PHOTOSPHERE_REPRESENTATIVE_DIVERSITY_SIM", "0.92"))
    )
    # Adaptive per-person threshold is clamped to this band around the global
    # default; a person needs at least this many representatives before it adapts.
    adaptive_threshold_min: float = field(
        default_factory=lambda: float(_env_str("PHOTOSPHERE_ADAPTIVE_THRESHOLD_MIN", "0.45"))
    )
    adaptive_threshold_max: float = field(
        default_factory=lambda: float(_env_str("PHOTOSPHERE_ADAPTIVE_THRESHOLD_MAX", "0.62"))
    )
    adaptive_threshold_min_reps: int = field(
        default_factory=lambda: _env_int("PHOTOSPHERE_ADAPTIVE_THRESHOLD_MIN_REPS", 3)
    )
    # A person may only demand a STRICTER-than-global match once their gallery is
    # genuinely diverse (this many representatives). A young, single-appearance
    # person otherwise looks "very consistent" and walls off its own other
    # appearances — the main cause of duplicate profiles for one identity.
    adaptive_strict_min_reps: int = field(
        default_factory=lambda: _env_int("PHOTOSPHERE_ADAPTIVE_STRICT_MIN_REPS", 6)
    )
    # Person-merge scan: cross-person similarity (best representative pair) at or
    # above `suggest` raises a "Same person?" question in the UI; at or above
    # `auto`, two UNNAMED persons are merged automatically (named people are
    # never auto-merged). Both compared after every recognition run.
    merge_suggest_threshold: float = field(
        default_factory=lambda: float(_env_str("PHOTOSPHERE_MERGE_SUGGEST", "0.50"))
    )
    merge_auto_threshold: float = field(
        default_factory=lambda: float(_env_str("PHOTOSPHERE_MERGE_AUTO", "0.70"))
    )
    # Active learning: a face whose best match falls within this margin *below* a
    # person's acceptance threshold becomes a "Is this <name>?" suggestion rather
    # than being dropped. Wider = more (but less certain) suggestions.
    suggestion_margin: float = field(
        default_factory=lambda: float(_env_str("PHOTOSPHERE_SUGGESTION_MARGIN", "0.07"))
    )
    # Context fusion: when a borderline face's photo shares capture context (same
    # day, same place) with a person's known photos, add up to this much to its
    # match score. Only faces already within `context_reach` below the threshold
    # are eligible, so context lifts near-misses but never invents a match.
    # Set the boost to 0 to disable context fusion.
    context_boost: float = field(
        default_factory=lambda: float(_env_str("PHOTOSPHERE_CONTEXT_BOOST", "0.06"))
    )
    context_reach: float = field(
        default_factory=lambda: float(_env_str("PHOTOSPHERE_CONTEXT_REACH", "0.10"))
    )

    # --- AI Search (CLIP) ---------------------------------------------------
    # open_clip model + pretrained tag. ViT-B-32/openai is a light 512-d model.
    clip_model: str = field(default_factory=lambda: _env_str("PHOTOSPHERE_CLIP_MODEL", "ViT-B-32"))
    clip_pretrained: str = field(
        default_factory=lambda: _env_str("PHOTOSPHERE_CLIP_PRETRAINED", "openai")
    )
    # Embedding dimension of the chosen model. MUST match the clip_embeddings
    # table's vector(...) size in schema.sql (512 for ViT-B-32). Changing the
    # model to a different dimension requires recreating that table.
    clip_embedding_dim: int = field(
        default_factory=lambda: _env_int("PHOTOSPHERE_CLIP_DIM", 512)
    )
    # Images per GPU batch — RTX cards are far more efficient batched.
    clip_batch_size: int = field(default_factory=lambda: _env_int("PHOTOSPHERE_CLIP_BATCH", 64))
    # Bump when re-embedding with the same model name should be forced.
    clip_model_version: int = field(default_factory=lambda: _env_int("PHOTOSPHERE_CLIP_VERSION", 1))
    # Unified-search ranking weights: final = similarity + w_fav*favorite +
    # w_recency*recency. Small so CLIP similarity dominates and these break ties.
    search_favorite_boost: float = field(
        default_factory=lambda: float(_env_str("PHOTOSPHERE_SEARCH_FAVORITE_BOOST", "0.15"))
    )
    search_recency_boost: float = field(
        default_factory=lambda: float(_env_str("PHOTOSPHERE_SEARCH_RECENCY_BOOST", "0.05"))
    )
    # Boost applied to results whose OCR text matches the query (strong signal).
    search_ocr_boost: float = field(
        default_factory=lambda: float(_env_str("PHOTOSPHERE_SEARCH_OCR_BOOST", "0.35"))
    )

    # --- Duplicates ----------------------------------------------------------
    # Maximum Hamming distance (of 64 dHash bits) for "visually the same".
    # 0 = identical fingerprints only; 5 tolerates re-encodes and resizes.
    phash_max_distance: int = field(
        default_factory=lambda: _env_int("PHOTOSPHERE_PHASH_MAX_DISTANCE", 5)
    )

    # --- OCR ----------------------------------------------------------------
    # RapidOCR language(s); comma-separated. Default English.
    ocr_languages: str = field(default_factory=lambda: _env_str("PHOTOSPHERE_OCR_LANGUAGES", "en"))

    # --- Thumbnails / Viewer (Module 4) -------------------------------------
    # Longest edge (px) of cached grid thumbnails. The gallery shows these, not
    # originals, so browsing stays fast on large libraries.
    thumbnail_size: int = field(default_factory=lambda: _env_int("PHOTOSPHERE_THUMBNAIL_SIZE", 320))
    thumbnail_quality: int = field(
        default_factory=lambda: _env_int("PHOTOSPHERE_THUMBNAIL_QUALITY", 85)
    )

    image_extensions: frozenset[str] = field(
        default_factory=lambda: frozenset(
            {".jpg", ".jpeg", ".png", ".bmp", ".gif", ".tif", ".tiff", ".webp", ".heic", ".heif"}
        )
    )

    def ensure_directories(self) -> None:
        """Create the generated-artifact directories if they do not exist.

        Called explicitly by entry points (not at import time) so that merely
        importing settings has no filesystem side effects.
        """
        for directory in (
            self.data_dir, self.thumbnails_dir, self.face_crops_dir, self.logs_dir,
            self.cache_dir / "clip" / "text",
        ):
            directory.mkdir(parents=True, exist_ok=True)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return the cached application settings singleton."""
    return Settings()
