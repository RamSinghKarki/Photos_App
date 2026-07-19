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

# The project root is two levels up from this file (config/settings.py).
PROJECT_ROOT: Path = Path(__file__).resolve().parent.parent


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

    data_dir: Path = field(default_factory=lambda: PROJECT_ROOT / "data")
    thumbnails_dir: Path = field(default_factory=lambda: PROJECT_ROOT / "data" / "thumbnails")
    face_crops_dir: Path = field(default_factory=lambda: PROJECT_ROOT / "data" / "face_crops")
    logs_dir: Path = field(default_factory=lambda: PROJECT_ROOT / "logs")

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
        for directory in (self.data_dir, self.thumbnails_dir, self.face_crops_dir, self.logs_dir):
            directory.mkdir(parents=True, exist_ok=True)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return the cached application settings singleton."""
    return Settings()
