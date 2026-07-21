"""Reset PhotoSphere to a clean slate — start training from zero.

Wipes every indexed and learned thing (photos, faces, people, names,
corrections, embeddings, albums, duplicate decisions, search index) and the
regenerable caches (thumbnails, face crops, text-embedding cache). The next
Import re-processes everything from scratch.

Your **original photo files are never touched** — only PhotoSphere's own
database rows and generated caches under the app data directory are removed.

Usage:
    python reset_library.py            # asks for confirmation
    python reset_library.py --yes      # no prompt (for scripts)
    python reset_library.py --keep-thumbnails   # DB only, keep caches

Tip: to keep the people names/corrections you've taught, make a backup first
(Settings → Backup, or restore it afterwards).
"""

from __future__ import annotations

import argparse
import shutil
import sys
from dataclasses import dataclass

from config.settings import get_settings
from database import db
from utils.logging_setup import get_logger

logger = get_logger("reset")


@dataclass
class ResetReport:
    photos_before: int
    caches_cleared: list[str]


def reset_library(clear_caches: bool = True) -> ResetReport:
    """Truncate all library tables and (optionally) delete generated caches.

    Returns a small report; raises on a database error (nothing partial: the
    TRUNCATE is one transaction, committed by the connection context manager).
    """
    settings = get_settings()
    with db.connection() as conn, conn.cursor() as cur:
        cur.execute("SELECT count(*) FROM photos")
        photos_before = int(cur.fetchone()[0])
        db.reset_library(cur)

    cleared: list[str] = []
    if clear_caches:
        for directory in (settings.thumbnails_dir, settings.face_crops_dir,
                          settings.cache_dir):
            if directory.exists():
                shutil.rmtree(directory, ignore_errors=True)
                cleared.append(str(directory))
            directory.mkdir(parents=True, exist_ok=True)

    logger.info("Library reset: %d photos removed; caches cleared: %s",
                photos_before, ", ".join(cleared) or "none")
    return ResetReport(photos_before=photos_before, caches_cleared=cleared)


def _main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Reset PhotoSphere to zero.")
    parser.add_argument("--yes", action="store_true", help="skip confirmation")
    parser.add_argument("--keep-thumbnails", action="store_true",
                        help="wipe the database only; keep generated caches")
    args = parser.parse_args(argv)

    db.apply_schema()  # ensure tables exist before counting/truncating
    with db.connection() as conn, conn.cursor() as cur:
        cur.execute("SELECT count(*) FROM photos")
        n = int(cur.fetchone()[0])

    if not args.yes:
        print(f"This will permanently remove all {n:,} indexed photos and every "
              "person, name, correction, album and search index PhotoSphere has "
              "built.\nYour original photo files are NOT affected.")
        if input("Type 'reset' to confirm: ").strip().lower() != "reset":
            print("Cancelled.")
            return 1

    report = reset_library(clear_caches=not args.keep_thumbnails)
    print(f"Done. Removed {report.photos_before:,} photos; "
          f"cleared {len(report.caches_cleared)} cache folder(s).")
    print("Import your photos again to train from zero.")
    return 0


if __name__ == "__main__":
    raise SystemExit(_main(sys.argv[1:]))
