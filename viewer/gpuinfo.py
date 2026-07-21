"""Local GPU detection for the status bar and face inference.

Reports whether CUDA is usable and what device is present, without hard-
depending on any GPU library. It checks, in order:

1. **PyTorch** — if installed, ``torch.cuda`` gives the device name directly.
2. **onnxruntime** — the runtime InsightFace uses; presence of the CUDA
   execution provider means face detection will run on the GPU.
3. Otherwise, CPU.

All imports are lazy and failure-tolerant, so a machine with neither library
simply reports CPU rather than crashing.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache


@dataclass(frozen=True)
class GpuInfo:
    """Describes the local compute device for AI inference."""

    available: bool          # True if a CUDA GPU is usable
    device_name: str         # e.g. "NVIDIA GeForce RTX 5060" or "CPU"
    source: str              # which library reported it ("torch"/"onnxruntime"/"none")

    def badge(self) -> str:
        """Short label for the status bar."""
        if self.available:
            return f"GPU: {self.device_name}"
        return "GPU: CPU only"


def _from_torch() -> GpuInfo | None:
    try:
        import torch  # type: ignore
    except Exception:  # noqa: BLE001 - torch not installed / broken install
        return None
    try:
        if torch.cuda.is_available():
            name = torch.cuda.get_device_name(0)
            return GpuInfo(available=True, device_name=name, source="torch")
    except Exception:  # noqa: BLE001 - driver/runtime mismatch
        return None
    return None


def _from_onnxruntime() -> GpuInfo | None:
    try:
        import onnxruntime  # type: ignore
    except Exception:  # noqa: BLE001
        return None
    try:
        providers = onnxruntime.get_available_providers()
    except Exception:  # noqa: BLE001
        return None
    if "CUDAExecutionProvider" in providers:
        return GpuInfo(available=True, device_name="CUDA device", source="onnxruntime")
    return None


@lru_cache(maxsize=1)
def detect_gpu() -> GpuInfo:
    """Return cached information about the local compute device."""
    return _from_torch() or _from_onnxruntime() or GpuInfo(
        available=False, device_name="CPU", source="none"
    )
