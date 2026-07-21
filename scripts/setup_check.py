"""Preflight diagnostic for PhotoSphere AI.

Prints a green/red checklist of everything the app needs and — importantly —
tells you whether **face detection will actually run on your GPU**. Run it after
installing, or any time the GPU badge says "CPU only" and you expected CUDA:

    python -m scripts.setup_check

It never changes anything; it only inspects your environment.
"""

from __future__ import annotations

import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

OK = "[ OK ]"
WARN = "[WARN]"
FAIL = "[FAIL]"


def _line(status: str, label: str, detail: str = "") -> None:
    print(f"  {status}  {label}" + (f"  —  {detail}" if detail else ""))


def check_python() -> None:
    v = sys.version_info
    status = OK if v >= (3, 10) else WARN
    _line(status, "Python", f"{v.major}.{v.minor}.{v.micro}")


def check_database() -> None:
    try:
        from config.settings import get_settings
        from database import db

        settings = get_settings()
        with db.connection() as conn, conn.cursor() as cur:
            cur.execute("SELECT 1 FROM pg_extension WHERE extname = 'vector'")
            has_vector = cur.fetchone() is not None
        _line(OK, "PostgreSQL", f"connected to '{settings.database.name}' at "
                                f"{settings.database.host}:{settings.database.port}")
        if has_vector:
            _line(OK, "pgvector extension", "installed")
        else:
            _line(WARN, "pgvector extension", "not enabled yet (the app enables it on first run)")
    except Exception as exc:  # noqa: BLE001
        _line(FAIL, "PostgreSQL", str(exc).splitlines()[0])
        _line("     ", "", "check the container (docker compose up -d) or PHOTOSPHERE_DB_* settings")


def check_torch() -> bool:
    try:
        import torch  # type: ignore
    except Exception:  # noqa: BLE001
        _line(WARN, "PyTorch", "not installed (optional; used for GPU detection)")
        return False
    try:
        if torch.cuda.is_available():
            _line(OK, "PyTorch CUDA", f"{torch.cuda.get_device_name(0)}  (torch {torch.__version__})")
            return True
        _line(WARN, "PyTorch CUDA", f"torch {torch.__version__} installed but CUDA not available")
    except Exception as exc:  # noqa: BLE001
        _line(WARN, "PyTorch CUDA", f"probe failed: {exc}")
    return False


def check_onnxruntime() -> bool:
    """Return True if onnxruntime can use CUDA (this is what InsightFace uses)."""
    try:
        import onnxruntime  # type: ignore
    except Exception:  # noqa: BLE001
        _line(FAIL, "onnxruntime", "not installed — face detection cannot run")
        return False
    try:
        providers = onnxruntime.get_available_providers()
    except Exception as exc:  # noqa: BLE001
        _line(FAIL, "onnxruntime", f"present but broken: {exc}")
        return False

    if "CUDAExecutionProvider" in providers:
        _line(OK, "onnxruntime GPU", f"CUDAExecutionProvider available  (v{onnxruntime.__version__})")
        return True
    _line(WARN, "onnxruntime GPU", "CPU-only build — CUDAExecutionProvider NOT available")
    _line("     ", "", "for GPU faces: pip uninstall onnxruntime && pip install onnxruntime-gpu")
    return False


def check_insightface() -> bool:
    try:
        import insightface  # type: ignore  # noqa: F401
        _line(OK, "InsightFace", "installed")
        return True
    except Exception as exc:  # noqa: BLE001
        _line(WARN, "InsightFace", f"not importable ({exc}); face stages will be skipped")
        return False


def check_pyside() -> None:
    try:
        import PySide6  # type: ignore
        _line(OK, "PySide6 (desktop UI)", PySide6.__version__)
    except Exception as exc:  # noqa: BLE001
        _line(FAIL, "PySide6", f"not installed — the app UI cannot run ({exc})")


def main() -> int:
    print("\nPhotoSphere AI — environment check\n" + "-" * 40)

    check_python()
    check_pyside()
    check_database()
    print()
    torch_gpu = check_torch()
    ort_gpu = check_onnxruntime()
    insight = check_insightface()

    print("\nFace detection device:")
    if insight and ort_gpu:
        _line(OK, "Faces will run on the GPU (CUDA via onnxruntime)")
    elif insight and not ort_gpu:
        _line(WARN, "Faces will run on the CPU",
              "install onnxruntime-gpu to use your GPU"
              + ("  (torch already sees your CUDA device)" if torch_gpu else ""))
    else:
        _line(WARN, "Face detection unavailable", "install insightface + onnxruntime-gpu")

    print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
