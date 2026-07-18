"""Face clustering for Module 3.

Groups face embeddings into people using density-based clustering (DBSCAN) over
**cosine distance**. DBSCAN is a good fit because the number of people is not
known in advance and it can leave ambiguous faces *ungrouped* (labelled noise)
rather than forcing them into the wrong person.

Embeddings are unit-normalized first, honouring the project rule that
similarity comparisons always run on normalized vectors. This function is pure
(NumPy in, labels out) so it is trivial to test and independent of the
database.
"""

from __future__ import annotations

import numpy as np

# DBSCAN's noise label. Faces with this label are left ungrouped.
NOISE_LABEL = -1


def normalize_embeddings(embeddings: np.ndarray) -> np.ndarray:
    """Return unit-length (L2-normalized) copies of the input row vectors.

    A zero vector (should not occur for real embeddings) is left as zeros
    rather than dividing by zero.
    """
    norms = np.linalg.norm(embeddings, axis=1, keepdims=True)
    norms[norms == 0.0] = 1.0
    return embeddings / norms


def cluster_faces(
    embeddings: np.ndarray, eps: float, min_samples: int
) -> np.ndarray:
    """Cluster face embeddings and return an integer label per row.

    Args:
        embeddings: (N, dim) array of raw face embeddings.
        eps: Neighbourhood radius as cosine distance (1 - cosine similarity).
        min_samples: Minimum neighbourhood size to seed a cluster.

    Returns:
        (N,) int array of labels. Labels >= 0 are clusters; ``NOISE_LABEL``
        (-1) marks ungrouped faces. An empty input yields an empty array.
    """
    # Imported here so importing this module doesn't pull in scikit-learn.
    from sklearn.cluster import DBSCAN

    if embeddings.shape[0] == 0:
        return np.empty((0,), dtype=int)

    normalized = normalize_embeddings(embeddings.astype(np.float32))
    model = DBSCAN(eps=eps, min_samples=min_samples, metric="cosine")
    return model.fit_predict(normalized)
