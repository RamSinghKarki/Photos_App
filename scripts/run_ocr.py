"""Extract OCR text from photos for search (RapidOCR, offline).

Usage::

    python -m scripts.run_ocr             # OCR new photos (incremental)
    python -m scripts.run_ocr --limit 500

The app's Import / Re-index do this automatically; this CLI is for
automation/headless use.
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
        prog="photosphere-ocr", description="Extract and index OCR text from photos."
    )
    parser.add_argument("--limit", type=int, default=None, help="Max photos this run.")
    parser.add_argument("--batch-size", type=int, default=None, help="Photos per commit.")
    parser.add_argument("--log-level", default=None, help="e.g. DEBUG or INFO.")
    args = parser.parse_args(argv)

    setup_logging(args.log_level)

    from ocr.backend import default_backend
    from ocr.processor import run_ocr

    backend = default_backend()
    if backend is None:
        print("RapidOCR not installed. Install: pip install rapidocr_onnxruntime")
        return 2

    summary = run_ocr(backend, limit=args.limit, batch_size=args.batch_size)
    print(summary.render())
    return 1 if summary.errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
