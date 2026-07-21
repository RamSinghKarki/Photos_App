"""Command-line entry point for thumbnail generation (Module 4 support).

Usage::

    python -m scripts.generate_thumbnails                # new photos only
    python -m scripts.generate_thumbnails --regenerate   # rebuild all
    python -m scripts.generate_thumbnails --limit 2000

Thumbnails are cached under ``data/thumbnails`` and referenced from
``photos.thumbnail_path``; the gallery shows them instead of originals.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from thumbnails.generator import generate_thumbnails  # noqa: E402
from utils.logging_setup import setup_logging  # noqa: E402


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(
        prog="photosphere-thumbnails",
        description="Generate cached gallery thumbnails for scanned photos.",
    )
    parser.add_argument("--regenerate", action="store_true", help="Rebuild every thumbnail.")
    parser.add_argument("--limit", type=int, default=None, help="Max photos this run.")
    parser.add_argument("--batch-size", type=int, default=None, help="Photos per commit.")
    parser.add_argument("--log-level", default=None, help="e.g. DEBUG or INFO.")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    """Run the thumbnail CLI and return a process exit code."""
    args = parse_args(argv)
    setup_logging(args.log_level)
    summary = generate_thumbnails(
        limit=args.limit, regenerate=args.regenerate, batch_size=args.batch_size
    )
    print(summary.render())
    return 1 if summary.errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
