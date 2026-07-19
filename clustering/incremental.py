"""Incremental, name-preserving people update — the self-improving loop.

Instead of wiping and rebuilding every person on each run (which would destroy
the names the user assigned), this:

  1. **Recognizes** — matches each *ungrouped* face against every known person's
     **representative gallery** (a diverse, quality-gated set of embeddings), not
     just a single average. Taking the *best* match across a person's front /
     profile / bearded / bespectacled / low-light examples is what recognizes the
     same person across appearances. A per-person **adaptive threshold** (derived
     from how consistent that gallery is) decides acceptance. Accepted faces fold
     into the person's centroid *and* their gallery, so naming a cluster once
     teaches the app and every future photo of that person is auto-recognized.
  2. **Discovers** — clusters whatever faces remain ungrouped into *new* people,
     appended alongside the existing ones (names untouched), each seeded with its
     own gallery.

Recognition therefore improves as the library grows: the gallery accumulates
more appearances and the threshold tightens or loosens to fit the person. See
``clustering/quality.py`` (what is allowed to teach) and ``clustering/gallery.py``
(how the diverse set and threshold are maintained). A full destructive rebuild is
still available via :func:`clustering.processor.recluster`.
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
from clustering.gallery import adaptive_threshold, select_representatives
from clustering.quality import face_quality
from config.settings import Settings, get_settings
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


# ---------------------------------------------------------------------------
# Gallery maintenance
# ---------------------------------------------------------------------------
def _store_faces(
    cur,
    person_id: int,
    face_ids: list[int],
    det_scores: list[float],
    sizes: list[tuple[int, int]],
    embs_norm: "np.ndarray",
    settings: Settings,
    ensure_one: bool = True,
) -> int:
    """Add quality-passing faces to a person's gallery; return how many were added.

    A face below ``face_quality_store_min`` is *not* trusted to teach. If nothing
    clears the bar but ``ensure_one`` is set, the single best face is kept anyway
    so the person always has at least one embedding to match against.
    """
    quals = [
        face_quality(det_scores[i], sizes[i][0], sizes[i][1]) for i in range(len(face_ids))
    ]
    stored = 0
    for i, face_id in enumerate(face_ids):
        if quals[i] >= settings.face_quality_store_min:
            db.add_person_embedding(cur, person_id, face_id, embs_norm[i].tolist(), quals[i])
            stored += 1
    if stored == 0 and ensure_one and face_ids:
        best = int(np.argmax(quals))
        db.add_person_embedding(
            cur, person_id, face_ids[best], embs_norm[best].tolist(), quals[best]
        )
        stored = 1
    return stored


def _refresh_gallery(cur, person_id: int, settings: Settings) -> None:
    """Recompute a person's representative subset and adaptive threshold."""
    face_ids, quals, embs = db.fetch_person_gallery(cur, person_id)
    if len(face_ids) == 0:
        db.set_adaptive_threshold(cur, person_id, None)
        return
    embs_norm = normalize_embeddings(embs)
    rep_idx = select_representatives(
        embs_norm,
        quals,
        max_reps=settings.person_max_representatives,
        diversity_sim=settings.representative_diversity_sim,
        learn_min=settings.face_quality_learn_min,
    )
    db.set_person_representatives(cur, person_id, [face_ids[i] for i in rep_idx])
    threshold = adaptive_threshold(
        embs_norm[rep_idx],
        global_threshold=settings.face_match_threshold,
        lo=settings.adaptive_threshold_min,
        hi=settings.adaptive_threshold_max,
        min_reps=settings.adaptive_threshold_min_reps,
    )
    db.set_adaptive_threshold(cur, person_id, threshold)


def rebuild_person_gallery(cur, person_id: int, settings: Optional[Settings] = None) -> None:
    """Rebuild one person's gallery from scratch from their current faces.

    Call after faces are reassigned outside the recognition loop (e.g. a merge),
    so the representative set and adaptive threshold reflect the new membership.
    """
    settings = settings or get_settings()
    face_ids, det_scores, sizes, embs = db.fetch_person_face_rows(cur, person_id)
    db.clear_person_gallery(cur, person_id)
    if not face_ids:
        db.set_adaptive_threshold(cur, person_id, None)
        return
    embs_norm = normalize_embeddings(embs)
    _store_faces(cur, person_id, face_ids, det_scores, sizes, embs_norm, settings)
    _refresh_gallery(cur, person_id, settings)


def confirm_face(cur, face_id: int, person_id: int, settings: Optional[Settings] = None) -> None:
    """Active learning: the user confirmed a suggested face IS this person.

    Assigns the face, records a durable ``confirm``, teaches the gallery, and
    clears the pending suggestion.
    """
    settings = settings or get_settings()
    db.assign_faces_to_person(cur, person_id, [face_id])
    db.record_feedback(cur, face_id, person_id, "confirm")
    db.delete_suggestion(cur, face_id)
    db.recompute_person_profile(cur, person_id)
    rebuild_person_gallery(cur, person_id, settings)


def _backfill_galleries(cur, settings: Settings) -> None:
    """Seed galleries for people grouped before the gallery existed (one-time)."""
    for person_id in db.persons_missing_gallery(cur):
        face_ids, det_scores, sizes, embs = db.fetch_person_face_rows(cur, person_id)
        if not face_ids:
            continue
        embs_norm = normalize_embeddings(embs)
        _store_faces(cur, person_id, face_ids, det_scores, sizes, embs_norm, settings)
        _refresh_gallery(cur, person_id, settings)


# ---------------------------------------------------------------------------
# Recognition (match ungrouped faces to known people)
# ---------------------------------------------------------------------------
def _match_vectors_by_person(
    cur, global_threshold: float
) -> dict[int, dict]:
    """Build each person's match set: representatives + centroid, with a threshold.

    Fusing the diverse representatives with the centroid means a new face is
    accepted if it strongly matches *any* stored appearance or the average — the
    multi-stage match (representative -> centroid) collapsed into one best-of.
    """
    per_person: dict[int, dict] = {}

    for person_id, threshold, reps in db.fetch_person_representatives(cur):
        per_person[person_id] = {
            "vecs": normalize_embeddings(reps),
            "thr": global_threshold if threshold is None else threshold,
        }

    person_ids, _counts, centroids = db.fetch_person_centroids(cur)
    for idx, person_id in enumerate(person_ids):
        centroid = normalize_embeddings(centroids[idx : idx + 1])  # (1, dim)
        if person_id in per_person:
            per_person[person_id]["vecs"] = np.vstack(
                [per_person[person_id]["vecs"], centroid]
            )
        else:
            per_person[person_id] = {"vecs": centroid, "thr": global_threshold}
    return per_person


def _assign_to_existing(cur, global_threshold: float, settings: Settings) -> int:
    """Auto-assign ungrouped faces to their best-matching known person; count them."""
    per_person = _match_vectors_by_person(cur, global_threshold)
    if not per_person:
        return 0
    face_ids, det_scores, sizes, embeddings = db.fetch_ungrouped_faces(cur)
    if not face_ids:
        return 0
    faces_norm = normalize_embeddings(embeddings)

    # Correction memory: a (face, person) the user rejected is never re-assigned.
    rejections = db.fetch_rejections(cur)

    n = faces_norm.shape[0]
    best_score = np.full(n, -np.inf, dtype=np.float32)
    best_pid = np.full(n, -1, dtype=np.int64)
    # Track the closest candidate by *margin to threshold* for active learning.
    best_gap = np.full(n, -np.inf, dtype=np.float32)
    sugg_pid = np.full(n, -1, dtype=np.int64)
    sugg_score = np.zeros(n, dtype=np.float32)
    for person_id, info in per_person.items():
        sims = faces_norm @ info["vecs"].T          # (N_faces, k) cosine sims
        score = sims.max(axis=1)                     # best appearance per face
        rejected = rejections.get(person_id)
        if rejected:
            blocked = np.array([fid in rejected for fid in face_ids])
            score = np.where(blocked, -np.inf, score)  # never rejoin this person
        better = (score >= info["thr"]) & (score > best_score)
        best_score = np.where(better, score, best_score)
        best_pid = np.where(better, person_id, best_pid)

        gap = score - info["thr"]
        closer = gap > best_gap
        best_gap = np.where(closer, gap, best_gap)
        sugg_pid = np.where(closer, person_id, sugg_pid)
        sugg_score = np.where(closer, score, sugg_score)

    # Active learning: a face we did NOT assign but whose best candidate is just
    # below that person's bar becomes a pending "Is this <name>?" suggestion.
    margin = settings.suggestion_margin
    for row in range(n):
        if best_pid[row] >= 0:
            continue  # assigned outright
        if -margin <= best_gap[row] < 0 and sugg_pid[row] >= 0:
            db.record_suggestion(cur, face_ids[row], int(sugg_pid[row]), float(sugg_score[row]))

    assigned: dict[int, list[int]] = defaultdict(list)
    for row, person_id in enumerate(best_pid):
        if person_id >= 0:
            assigned[int(person_id)].append(row)
    if not assigned:
        return 0

    # Old centroids/counts, to fold accepted faces into the running average.
    cent_ids, cent_counts, cent_vecs = db.fetch_person_centroids(cur)
    old = {
        pid: (cent_counts[i], normalize_embeddings(cent_vecs[i : i + 1])[0])
        for i, pid in enumerate(cent_ids)
    }

    total = 0
    for person_id, rows in assigned.items():
        member_face_ids = [face_ids[r] for r in rows]
        db.assign_faces_to_person(cur, person_id, member_face_ids)

        new_vectors = faces_norm[rows]
        if person_id in old:
            old_count, old_centroid = old[person_id]
            blended = old_centroid * old_count + new_vectors.sum(axis=0)
        else:  # representative-only person without a centroid (defensive)
            old_count = 0
            blended = new_vectors.sum(axis=0)
        norm = float(np.linalg.norm(blended))
        centroid = (blended / norm) if norm else blended
        db.update_person_profile(
            cur, person_id, centroid.astype(np.float32).tolist(), old_count + len(rows)
        )

        # Teach the gallery from the accepted faces, then re-curate it.
        _store_faces(
            cur,
            person_id,
            member_face_ids,
            [det_scores[r] for r in rows],
            [sizes[r] for r in rows],
            new_vectors,
            settings,
            ensure_one=False,
        )
        _refresh_gallery(cur, person_id, settings)
        total += len(rows)

    return total


def _cluster_remaining(
    cur, eps: float, min_samples: int, algorithm: str, settings: Settings
) -> tuple[int, int, int]:
    """Cluster still-ungrouped faces into NEW people. Returns (people, grouped, noise)."""
    face_ids, det_scores, sizes, embeddings = db.fetch_ungrouped_faces(cur)
    if len(face_ids) < max(2, min_samples):
        return 0, 0, len(face_ids)

    labels = cluster_faces(embeddings, eps=eps, min_samples=min_samples, algorithm=algorithm)
    embs_norm = normalize_embeddings(embeddings)
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

        # Seed the new person's representative gallery.
        _store_faces(
            cur,
            person_id,
            member_ids,
            scores,
            [sizes[i] for i in indices],
            embs_norm[indices],
            settings,
        )
        _refresh_gallery(cur, person_id, settings)

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
        # Upgrade path: give pre-gallery people a gallery before matching.
        _backfill_galleries(cur, settings)

        if db.count_ungrouped_faces(cur) == 0:
            return summary
        summary.recognized = _assign_to_existing(cur, eff_thresh, settings)
        people, grouped, noise = _cluster_remaining(cur, eff_eps, eff_min, eff_algo, settings)
        summary.new_people = people
        summary.grouped_new = grouped
        summary.still_ungrouped = noise
        # A suggestion is only valid while its face is still ungrouped.
        db.delete_grouped_suggestions(cur)

    logger.info(
        "Incremental update: recognized %d, %d new people, %d still ungrouped",
        summary.recognized, summary.new_people, summary.still_ungrouped,
    )
    return summary
