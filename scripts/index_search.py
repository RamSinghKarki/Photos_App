"""Build the CLIP semantic-search index from the command line.

Usage::

    python -m scripts.index_search              # embed new photos
    python -m scripts.index_search --batch 32

Computes CLIP image embeddings (incrementally — only photos without one for the
active model) and stores them for semantic search. The app's Import / Re-index
do this automatically; this CLI is for automation/headless use.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from utils.logging_setup import setup_logging  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="photosphere-index-search",
        description="Compute CLIP image embeddings for semantic search.",
    )
    parser.add_argument("--batch", type=int, default=None, help="Images per GPU batch.")
    parser.add_argument("--limit", type=int, default=None, help="Max photos this run.")
    parser.add_argument("--log-level", default=None, help="e.g. DEBUG or INFO.")
    args = parser.parse_args(argv)

    setup_logging(args.log_level)

    from search.clip_backend import default_backend
    from search.embedding_engine import embed_images

    backend = default_backend()
    if backend is None:
        print("CLIP runtime not installed. Install: pip install open_clip_torch torch")
        return 2

    summary = embed_images(backend, batch_size=args.batch, limit=args.limit)
    print(summary.render())
    return 1 if summary.errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
