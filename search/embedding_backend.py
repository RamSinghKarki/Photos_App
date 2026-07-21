"""Embedding backend interface for the AI search subsystem.

The search engine depends only on this small contract, never on a specific
model. CLIP is the first backend; SigLIP, OpenCLIP variants, or other local
models can be added later by implementing the same interface — the storage,
search, and UI code stays unchanged.

All backends return **L2-normalized** float32 vectors, so cosine similarity is a
dot product and the values drop straight into pgvector's cosine index.
"""

from __future__ import annotations

from typing import List, Protocol, runtime_checkable

import numpy as np
from PIL import Image


@runtime_checkable
class EmbeddingBackend(Protocol):
    """A local image+text embedding model usable for semantic search."""

    @property
    def model_id(self) -> str:
        """Stable identifier stored with each embedding, e.g. 'ViT-B-32/openai'."""
        ...

    @property
    def version(self) -> int:
        """Embedding version; bump to force re-embedding with the same model."""
        ...

    @property
    def dim(self) -> int:
        """Embedding dimension (must match the clip_embeddings vector size)."""
        ...

    def encode_images(self, images: List[Image.Image]) -> np.ndarray:
        """Encode a batch of PIL images to an (N, dim) L2-normalized array."""
        ...

    def encode_text(self, text: str) -> np.ndarray:
        """Encode a text query to a (dim,) L2-normalized vector."""
        ...


def l2_normalize(vectors: np.ndarray) -> np.ndarray:
    """Return L2-normalized rows (safe against zero vectors)."""
    arr = np.asarray(vectors, dtype=np.float32)
    if arr.ndim == 1:
        norm = float(np.linalg.norm(arr))
        return arr / norm if norm else arr
    norms = np.linalg.norm(arr, axis=1, keepdims=True)
    norms[norms == 0.0] = 1.0
    return arr / norms
