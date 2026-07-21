"""Person-merge scan — heal duplicate profiles of the same individual.

Clustering can split one identity into several persons (frontal vs profile,
beard vs clean-shaven, occlusions): each appearance forms its own dense cluster,
and nothing ever joined them afterwards. This pass runs after every recognition
update and compares persons *pairwise by their galleries* (representatives +
centroid, best matching pair — the same best-of-appearances idea used for face
matching, lifted to person level):

* score >= ``merge_auto_threshold`` and **both persons unnamed** → merged
  automatically (smaller absorbed into larger, gallery re-curated).
* score >= ``merge_suggest_threshold`` → recorded as a "Same person?" suggestion
  for the People page. **Named persons are never auto-merged** — a name is a
  user decision, so the user is always asked.
* pairs the user rejected ("not the same person") are never asked again and
  never auto-merged.

The suggestion table is replaced wholesale each scan (rejections persist in
their own table), so stale pairs disappear as galleries evolve.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from clustering.clusterer import normalize_embeddings
from clustering.incremental import rebuild_person_gallery
from config.settings import Settings
from database import db
from utils.logging_setup import get_logger

logger = get_logger("clustering.merge_scan")


@dataclass
class MergeScanResult:
    auto_merged: int = 0
    suggested: int = 0


def _person_matrices(cur) -> dict[int, np.ndarray]:
    """Each person's matching vectors: representatives plus centroid, normalized."""
    vectors: dict[int, list[np.ndarray]] = {}
    for person_id, _thr, reps in db.fetch_person_representatives(cur):
        vectors.setdefault(person_id, []).append(normalize_embeddings(reps))
    person_ids, _counts, centroids = db.fetch_person_centroids(cur)
    for idx, person_id in enumerate(person_ids):
        vectors.setdefault(person_id, []).append(
            normalize_embeddings(centroids[idx : idx + 1])
        )
    return {pid: np.vstack(mats) for pid, mats in vectors.items()}


def _pair_scores(matrices: dict[int, np.ndarray]) -> list[tuple[int, int, float]]:
    """Best cross-gallery cosine for every person pair (a < b), one matmul."""
    if len(matrices) < 2:
        return []
    ids = sorted(matrices)
    stacked = np.vstack([matrices[pid] for pid in ids])
    owners = np.concatenate(
        [np.full(matrices[pid].shape[0], i) for i, pid in enumerate(ids)]
    )
    sims = stacked @ stacked.T  # (R, R); R = total vectors, ~13 per person max

    out: list[tuple[int, int, float]] = []
    for i in range(len(ids)):
        rows = owners == i
        for j in range(i + 1, len(ids)):
            cols = owners == j
            out.append((ids[i], ids[j], float(sims[np.ix_(rows, cols)].max())))
    return out


def scan_for_merges(cur, settings: Settings) -> MergeScanResult:
    """Auto-merge obvious duplicates, suggest the rest; refresh the suggestion set."""
    result = MergeScanResult()
    matrices = _person_matrices(cur)
    if len(matrices) < 2:
        db.replace_merge_suggestions(cur, [])
        return result

    rejected = db.fetch_merge_rejections(cur)
    names = db.fetch_person_names(cur)
    pairs = [
        (a, b, score)
        for a, b, score in _pair_scores(matrices)
        if score >= settings.merge_suggest_threshold and (a, b) not in rejected
    ]
    pairs.sort(key=lambda p: -p[2])  # strongest evidence first

    # `alias` follows persons that were absorbed during this scan, so a chain
    # (A~B, B~C) merges into one surviving person instead of a dangling pair.
    alias: dict[int, int] = {}

    def resolve(pid: int) -> int:
        while pid in alias:
            pid = alias[pid]
        return pid

    suggestions: list[tuple[int, int, float]] = []
    for a, b, score in pairs:
        a, b = resolve(a), resolve(b)
        if a == b:
            continue
        both_unnamed = names.get(a) is None and names.get(b) is None
        if score >= settings.merge_auto_threshold and both_unnamed:
            # Absorb the smaller into the larger; re-curate the survivor.
            _ids, counts, _cents = db.fetch_person_centroids(cur)
            size = dict(zip(_ids, counts))
            source, target = (a, b) if size.get(a, 0) <= size.get(b, 0) else (b, a)
            db.merge_persons(cur, source, target)
            rebuild_person_gallery(cur, target, settings)
            alias[source] = target
            result.auto_merged += 1
            logger.info("Auto-merged person %d into %d (score %.2f)", source, target, score)
        else:
            suggestions.append((a, b, score))

    # Re-resolve after merges and drop pairs that collapsed into one person.
    final = []
    seen: set[tuple[int, int]] = set()
    for a, b, score in suggestions:
        a, b = resolve(a), resolve(b)
        if a == b:
            continue
        key = (min(a, b), max(a, b))
        if key in seen or key in rejected:
            continue
        seen.add(key)
        final.append((a, b, score))
    db.replace_merge_suggestions(cur, final)
    result.suggested = len(final)
    return result
