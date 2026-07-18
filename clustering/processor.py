"""Module 3 — Clustering pipeline.

Reads every stored face embedding, groups them into people, and writes the
result back: one ``persons`` row per group with each member face's
``person_id`` set. Faces DBSCAN judges ambiguous are left ungrouped
(``person_id = NULL``) rather than misfiled.

This is a full **re-cluster**: existing person groupings are cleared and rebuilt
from scratch, which keeps the operation simple and deterministic. Incremental
assignment of only-new faces (using the pgvector index to find each new face's
nearest existing person) is a future optimization that this schema already
supports.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from typing import Optional

import numpy as np

from clustering.clusterer import NOISE_LABEL, cluster_faces
from config.settings import get_settings
from database import db
from utils.logging_setup import get_logger

logger = get_logger("clustering")


@dataclass
class ClusterSummary:
    """Outcome of a clustering run, shown to the user at the end."""

    total_faces: int = 0      # faces considered
    persons: int = 0          # person groups created
    grouped: int = 0          # faces assigned to a person
    ungrouped: int = 0        # faces left as noise (person_id NULL)

    def render(self) -> str:
        """Return the human-readable summary block."""
        return (
            "\n"
            f"Faces:      {self.total_faces}\n"
            f"People:     {self.persons}\n"
            f"Grouped:    {self.grouped}\n"
            f"Ungrouped:  {self.ungrouped}"
        )


def _pick_cover_face(
    member_ids: list[int], member_scores: list[float]
) -> Optional[int]:
    """Choose the highest-confidence face in a group as its cover image."""
    if not member_ids:
        return None
    best_index = int(np.argmax(member_scores))
    return member_ids[best_index]


def recluster(
    eps: Optional[float] = None, min_samples: Optional[int] = None
) -> ClusterSummary:
    """Re-cluster all faces into people and persist the grouping.

    Args:
        eps: Cosine-distance radius (defaults to the configured value).
        min_samples: Minimum neighbourhood size (defaults to configured).

    Returns:
        A :class:`ClusterSummary` describing the run.
    """
    settings = get_settings()
    eff_eps = settings.cluster_eps if eps is None else eps
    eff_min = settings.cluster_min_samples if min_samples is None else min_samples

    db.apply_schema()
    summary = ClusterSummary()

    with db.connection() as conn, conn.cursor() as cur:
        face_ids, det_scores, embeddings = db.fetch_face_vectors(cur)
        summary.total_faces = len(face_ids)
        if summary.total_faces == 0:
            logger.info("No faces to cluster")
            return summary

        labels = cluster_faces(embeddings, eps=eff_eps, min_samples=eff_min)

        # Group member face indices by their cluster label.
        clusters: dict[int, list[int]] = defaultdict(list)
        for index, label in enumerate(labels):
            clusters[int(label)].append(index)

        # Rebuild persons from scratch for a deterministic result.
        db.clear_persons(cur)

        for label, indices in clusters.items():
            if label == NOISE_LABEL:
                summary.ungrouped += len(indices)
                continue

            member_ids = [face_ids[i] for i in indices]
            member_scores = [det_scores[i] for i in indices]
            cover = _pick_cover_face(member_ids, member_scores)

            person_id = db.create_person(cur, face_count=len(member_ids), cover_face_id=cover)
            db.assign_faces_to_person(cur, person_id, member_ids)

            summary.persons += 1
            summary.grouped += len(member_ids)

        logger.info(
            "Clustered %d faces into %d people (%d ungrouped)",
            summary.total_faces, summary.persons, summary.ungrouped,
        )

    return summary
