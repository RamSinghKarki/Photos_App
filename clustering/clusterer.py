"""Face clustering for Module 3.

Groups face embeddings into people using density-based clustering. Two engines
are supported and both leave ambiguous faces *ungrouped* (label ``-1``) rather
than forcing them into the wrong person:

* **DBSCAN** (scikit-learn, always available) over cosine distance.
* **HDBSCAN** (optional dependency) which handles clusters of varying density
  and needs no ``eps`` — usually more robust for real face libraries.

``algorithm="auto"`` uses HDBSCAN if it is installed, otherwise DBSCAN.

Embeddings are unit-normalized first, honouring the project rule that
similarity comparisons always run on normalized vectors. This function is pure
(NumPy in, labels out) so it is trivial to test and independent of the
database.
"""

from __future__ import annotations

import numpy as np

# Shared noise label for both engines. Faces with this label stay ungrouped.
NOISE_LABEL = -1


def _hdbscan_available() -> bool:
    try:
        import hdbscan  # type: ignore  # noqa: F401
        return True
    except Exception:  # noqa: BLE001
        return False


def resolve_algorithm(algorithm: str) -> str:
    """Resolve 'auto' to a concrete engine name based on what is installed."""
    algo = (algorithm or "auto").lower()
    if algo == "hdbscan":
        return "hdbscan"
    if algo == "dbscan":
        return "dbscan"
    return "hdbscan" if _hdbscan_available() else "dbscan"


def normalize_embeddings(embeddings: np.ndarray) -> np.ndarray:
    """Return unit-length (L2-normalized) copies of the input row vectors.

    A zero vector (should not occur for real embeddings) is left as zeros
    rather than dividing by zero.
    """
    norms = np.linalg.norm(embeddings, axis=1, keepdims=True)
    norms[norms == 0.0] = 1.0
    return embeddings / norms


def cluster_faces(
    embeddings: np.ndarray, eps: float, min_samples: int, algorithm: str = "auto"
) -> np.ndarray:
    """Cluster face embeddings and return an integer label per row.

    Args:
        embeddings: (N, dim) array of raw face embeddings.
        eps: DBSCAN neighbourhood radius as cosine distance (ignored by HDBSCAN).
        min_samples: Minimum cluster size (HDBSCAN) / neighbourhood size (DBSCAN).
        algorithm: "auto" (HDBSCAN if installed, else DBSCAN), "hdbscan", or
            "dbscan".

    Returns:
        (N,) int array of labels. Labels >= 0 are clusters; ``NOISE_LABEL``
        (-1) marks ungrouped faces. An empty input yields an empty array.
    """
    if embeddings.shape[0] == 0:
        return np.empty((0,), dtype=int)

    normalized = normalize_embeddings(embeddings.astype(np.float32))

    if resolve_algorithm(algorithm) == "hdbscan":
        import hdbscan  # type: ignore

        # On unit-normalized vectors, euclidean distance is monotonic with
        # cosine distance, so euclidean HDBSCAN clusters by cosine similarity.
        model = hdbscan.HDBSCAN(min_cluster_size=max(2, min_samples), metric="euclidean")
        return model.fit_predict(normalized).astype(int)

    # Imported here so importing this module doesn't require scikit-learn.
    from sklearn.cluster import DBSCAN

    model = DBSCAN(eps=eps, min_samples=min_samples, metric="cosine")
    return model.fit_predict(normalized)
