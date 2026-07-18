"""Command-line entry point for Module 2 — face detection.

Usage::

    python -m scripts.detect_faces                 # process new photos
    python -m scripts.detect_faces --limit 1000    # bounded batch
    python -m scripts.detect_faces --reprocess     # re-examine everything

Runs InsightFace locally over photos the scanner stored, saving face crops and
embeddings to the database. Prints a processing summary. Exit code is non-zero
if any photo errored.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

# Allow running as a bare script as well as `python -m scripts.detect_faces`.
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from faces.processor import process_faces  # noqa: E402
from utils.logging_setup import setup_logging  # noqa: E402


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(
        prog="photosphere-detect-faces",
        description="Detect faces and store embeddings for scanned photos.",
    )
    parser.add_argument(
        "--reprocess",
        action="store_true",
        help="Re-examine every photo, replacing existing faces.",
    )
    parser.add_argument(
        "--limit", type=int, default=None, help="Max photos to process this run."
    )
    parser.add_argument(
        "--batch-size", type=int, default=None, help="Photos per committed transaction."
    )
    parser.add_argument("--log-level", default=None, help="e.g. DEBUG or INFO.")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    """Run the face-detection CLI and return a process exit code."""
    args = parse_args(argv)
    logger = setup_logging(args.log_level)

    # Imported here (not at module top) so the heavy InsightFace/ONNX runtime is
    # only required when actually running detection, not for --help.
    from faces.detector import InsightFaceDetector

    logger.info("Starting face detection (reprocess=%s)", args.reprocess)
    summary = process_faces(
        detector=InsightFaceDetector(),
        reprocess=args.reprocess,
        limit=args.limit,
        batch_size=args.batch_size,
    )

    print(summary.render())
    return 1 if summary.errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
