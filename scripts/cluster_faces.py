"""Command-line entry point for Module 3 — face clustering.

Usage::

    python -m scripts.cluster_faces
    python -m scripts.cluster_faces --eps 0.30 --min-samples 4

Re-clusters every stored face into people and prints a summary. Tuning:
  * lower ``--eps`` for stricter grouping (fewer faces merged per person);
  * raise ``--min-samples`` to require more evidence before forming a person.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

# Allow running as a bare script as well as `python -m scripts.cluster_faces`.
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from clustering.processor import recluster  # noqa: E402
from utils.logging_setup import setup_logging  # noqa: E402


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(
        prog="photosphere-cluster-faces",
        description="Group stored face embeddings into people.",
    )
    parser.add_argument(
        "--eps", type=float, default=None,
        help="Cosine-distance radius (default from settings; smaller=stricter).",
    )
    parser.add_argument(
        "--min-samples", type=int, default=None,
        help="Minimum neighbourhood size to form a person (default from settings).",
    )
    parser.add_argument("--log-level", default=None, help="e.g. DEBUG or INFO.")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    """Run the clustering CLI and return a process exit code."""
    args = parse_args(argv)
    logger = setup_logging(args.log_level)

    logger.info("Starting face clustering")
    summary = recluster(eps=args.eps, min_samples=args.min_samples)
    print(summary.render())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
