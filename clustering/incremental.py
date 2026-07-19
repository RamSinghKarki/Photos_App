"""Incremental, name-preserving people update — the self-improving loop.

Instead of wiping and rebuilding every person on each run (which would destroy
the names the user assigned), this:

  1. **Recognizes** — matches each *ungrouped* face against existing person
     profiles (centroids). Above a confidence threshold it auto-assigns the face
     to that person and folds it into the person's running-average profile. So
     naming a cluster once teaches the app: future faces of that person are
     recognized automatically, with no reclustering.
  2. **Discovers** — clusters whatever faces remain ungrouped into *new* people,
     appended alongside the existing ones (names untouched).

This is what makes recognition improve as the library grows, while keeping
inference fast (existing people are never recomputed from scratch). A full
destructive rebuild is still available via :func:`clustering.processor.recluster`.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from typing import Optional

import numpy as np

from clustering.clusterer import (
    NOISE_LABEL,
    cluster_faces,
    normalize_embeddings,
    person_centroid,
)
from config.settings import get_settings
from database import db
from utils.logging_setup import get_logger

logger = get_logger("clustering.incremental")


@dataclass
class UpdateSummary:
    """Outcome of an incremental people update."""

    recognized: int = 0     # ungrouped faces auto-assigned to existing people
    new_people: int = 0     # new person groups discovered
    grouped_new: int = 0    # faces placed into the new groups
    still_ungrouped: int = 0

    def render(self) -> str:
        return (
            "\n"
            f"Recognized:      {self.recognized}\n"
            f"New people:      {self.new_people}\n"
            f"Grouped (new):   {self.grouped_new}\n"
            f"Still ungrouped: {self.still_ungrouped}"
        )


def _assign_to_existing(cur, threshold: float) -> int:
    """Auto-assign ungrouped faces to existing person centroids; return count."""
    person_ids, counts, centroids = db.fetch_person_centroids(cur)
    if not person_ids:
        return 0
    face_ids, _scores, embeddings = db.fetch_ungrouped_face_vectors(cur)
    if not face_ids:
        return 0

    faces_norm = normalize_embeddings(embeddings)
    cents_norm = normalize_embeddings(centroids)
    sims = faces_norm @ cents_norm.T            # (N_faces, N_people) cosine sims
    best_idx = sims.argmax(axis=1)
    best_sim = sims[np.arange(sims.shape[0]), best_idx]

    # Group accepted assignments by person.
    assigned: dict[int, list[int]] = defaultdict(list)
    for row, (pidx, score) in enumerate(zip(best_idx, best_sim)):
        if score >= threshold:
            assigned[int(pidx)].append(row)

    total = 0
    for pidx, face_rows in assigned.items():
        person_id = person_ids[pidx]
        member_face_ids = [face_ids[r] for r in face_rows]
        db.assign_faces_to_person(cur, person_id, member_face_ids)

        # Fold the new faces into the person's running-average profile.
        old_count = counts[pidx]
        old_centroid = normalize_embeddings(centroids[pidx : pidx + 1])[0]
        new_vectors = faces_norm[face_rows]
        blended = old_centroid * old_count + new_vectors.sum(axis=0)
        norm = float(np.linalg.norm(blended))
        centroid = (blended / norm) if norm else blended
        new_count = old_count + len(face_rows)
        db.update_person_profile(cur, person_id, centroid.astype(np.float32).tolist(), new_count)
        total += len(face_rows)

    return total


def _cluster_remaining(cur, eps: float, min_samples: int, algorithm: str) -> tuple[int, int, int]:
    """Cluster still-ungrouped faces into NEW people. Returns (people, grouped, noise)."""
    face_ids, det_scores, embeddings = db.fetch_ungrouped_face_vectors(cur)
    if len(face_ids) < max(2, min_samples):
        return 0, 0, len(face_ids)

    labels = cluster_faces(embeddings, eps=eps, min_samples=min_samples, algorithm=algorithm)
    groups: dict[int, list[int]] = defaultdict(list)
    for index, label in enumerate(labels):
        groups[int(label)].append(index)

    people = grouped = 0
    noise = 0
    for label, indices in groups.items():
        if label == NOISE_LABEL:
            noise += len(indices)
            continue
        member_ids = [face_ids[i] for i in indices]
        scores = [det_scores[i] for i in indices]
        cover = member_ids[int(np.argmax(scores))] if member_ids else None
        person_id = db.create_person(cur, face_count=len(member_ids), cover_face_id=cover)
        db.assign_faces_to_person(cur, person_id, member_ids)
        db.set_person_centroid(cur, person_id, person_centroid(embeddings[indices]))
        people += 1
        grouped += len(member_ids)
    return people, grouped, noise


def update_people(
    eps: Optional[float] = None,
    min_samples: Optional[int] = None,
    algorithm: Optional[str] = None,
    threshold: Optional[float] = None,
) -> UpdateSummary:
    """Recognize known people among new faces, then discover new people.

    Non-destructive: existing people (and their names) are preserved.
    """
    settings = get_settings()
    eff_eps = settings.cluster_eps if eps is None else eps
    eff_min = settings.cluster_min_samples if min_samples is None else min_samples
    eff_algo = settings.cluster_algorithm if algorithm is None else algorithm
    eff_thresh = settings.face_match_threshold if threshold is None else threshold

    db.apply_schema()
    summary = UpdateSummary()

    with db.connection() as conn, conn.cursor() as cur:
        if db.count_ungrouped_faces(cur) == 0:
            return summary
        summary.recognized = _assign_to_existing(cur, eff_thresh)
        people, grouped, noise = _cluster_remaining(cur, eff_eps, eff_min, eff_algo)
        summary.new_people = people
        summary.grouped_new = grouped
        summary.still_ungrouped = noise

    logger.info(
        "Incremental update: recognized %d, %d new people, %d still ungrouped",
        summary.recognized, summary.new_people, summary.still_ungrouped,
    )
    return summary
