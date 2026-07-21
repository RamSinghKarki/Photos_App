"""Shared pytest fixtures for PhotoSphere AI tests."""

from __future__ import annotations

import os
import shutil
from pathlib import Path

import pytest
from PIL import Image

# Point every test at the dedicated test database *before* settings are first
# read. Overridable from the environment so CI can choose its own database.
os.environ.setdefault("PHOTOSPHERE_DB_NAME", "photosphere_test")
os.environ.setdefault("PHOTOSPHERE_DB_HOST", "127.0.0.1")
# Pin clustering to DBSCAN in tests so results are deterministic regardless of
# whether the optional `hdbscan` package is installed. (The clusterer's "auto"
# path is still covered directly in test_clustering.py.)
os.environ.setdefault("PHOTOSPHERE_CLUSTER_ALGORITHM", "dbscan")
# User preferences live under the home directory in production; tests get a
# throwaway location so they never read or write the developer's real config.
import tempfile as _tempfile  # noqa: E402

os.environ.setdefault("PHOTOSPHERE_CONFIG_DIR", _tempfile.mkdtemp(prefix="ps_cfg_"))


@pytest.fixture(autouse=True)
def _drain_qt_pool():
    """Flush background image-decode tasks after each test.

    The widget tests create pages/viewers that kick off async thumbnail decodes
    on the global ``QThreadPool``. If a widget is dropped while a task is still
    in flight, the task later emits into a freed C++ object — which, when a
    later test aggressively processes events, segfaults the whole run. Draining
    the pool and flushing deferred deletes between tests keeps that leak from
    crossing test boundaries. A no-op when Qt/QApplication isn't loaded.
    """
    yield
    try:
        from PySide6 import QtCore
    except Exception:  # noqa: BLE001 - Qt not installed for this test
        return
    app = QtCore.QCoreApplication.instance()
    if app is None:
        return
    QtCore.QThreadPool.globalInstance().waitForDone(3000)
    app.processEvents()
    app.sendPostedEvents(None, QtCore.QEvent.Type.DeferredDelete)
    app.processEvents()


def _make_exif_image(path: Path) -> None:
    """Write a small JPEG carrying camera, capture-time and GPS EXIF."""
    exif = Image.Exif()
    exif[0x010F] = "TestMake"       # Make
    exif[0x0110] = "TestModel"      # Model
    exif[0x0112] = 1                # Orientation
    exif[0x8769] = {0x9003: "2021:07:04 12:34:56"}  # Exif IFD: DateTimeOriginal
    exif[0x8825] = {               # GPS IFD: 37°46'30"N, 122°25'10"W
        1: "N", 2: (37.0, 46.0, 30.0),
        3: "W", 4: (122.0, 25.0, 10.0),
    }
    Image.new("RGB", (200, 150), "green").save(path, "JPEG", exif=exif)


@pytest.fixture
def photo_tree(tmp_path: Path) -> Path:
    """Create a directory tree of fixtures and return its root.

    Contents:
      * a.jpg              plain JPEG
      * sub/b.png          plain PNG
      * sub/a_copy.jpg     byte-identical duplicate of a.jpg
      * with_exif.jpg      JPEG with camera/time/GPS EXIF
      * broken.jpg         invalid bytes but .jpg extension (identity only)
      * notes.txt          non-image, must be ignored
    """
    root = tmp_path / "photos"
    (root / "sub").mkdir(parents=True)

    Image.new("RGB", (120, 80), "red").save(root / "a.jpg", "JPEG")
    Image.new("RGB", (64, 64), "blue").save(root / "sub" / "b.png", "PNG")
    shutil.copy(root / "a.jpg", root / "sub" / "a_copy.jpg")
    _make_exif_image(root / "with_exif.jpg")
    (root / "broken.jpg").write_bytes(b"not really a jpeg")
    (root / "notes.txt").write_text("ignore me")

    return root


@pytest.fixture
def clean_db():
    """Ensure a reachable, empty schema; skip the test if the DB is down.

    Shared by every integration test so production data is never touched.
    """
    import psycopg2

    from config.settings import get_settings
    from database import db

    get_settings.cache_clear()
    try:
        db.apply_schema()
    except psycopg2.OperationalError as exc:
        pytest.skip(f"PostgreSQL not reachable for integration test: {exc}")

    with db.connection() as conn, conn.cursor() as cur:
        cur.execute("TRUNCATE faces, photos, scan_runs RESTART IDENTITY CASCADE")
        # Reset id-keyed side tables too: TRUNCATE ... RESTART IDENTITY reuses
        # photo ids, so a stale dismissal keyed by "1-2" would wrongly hide a
        # freshly-seeded group in a later test.
        cur.execute("TRUNCATE duplicate_dismissals")
    yield
