"""Command-line entry point for the scanner.

Usage::

    python -m scripts.scan /path/to/photos
    python scripts/scan.py /path/to/photos --batch-size 500

Configures logging, ensures the schema exists, runs the scan, and prints the
processing summary. Exit code is non-zero if any files errored, so the command
is usable in automation.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

# Allow running as a bare script (python scripts/scan.py ...) by making the
# project root importable, not just `python -m scripts.scan`.
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from scanner.scanner import scan_directory  # noqa: E402  (after sys.path setup)
from utils.logging_setup import setup_logging  # noqa: E402


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(
        prog="photosphere-scan",
        description="Scan a directory of photos into the PhotoSphere AI database.",
    )
    parser.add_argument("root", type=Path, help="Directory to scan recursively.")
    parser.add_argument(
        "--batch-size",
        type=int,
        default=None,
        help="Rows to commit per transaction (defaults to configured value).",
    )
    parser.add_argument(
        "--log-level",
        default=None,
        help="Logging level, e.g. DEBUG or INFO (defaults to configured value).",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    """Run the scanner CLI and return a process exit code."""
    args = parse_args(argv)
    logger = setup_logging(args.log_level)

    logger.info("Starting scan of %s", args.root)
    try:
        summary = scan_directory(args.root, batch_size=args.batch_size)
    except FileNotFoundError as exc:
        logger.error("%s", exc)
        return 2

    # The summary is a deliverable in its own right — always show it.
    print(summary.render())
    return 1 if summary.errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
