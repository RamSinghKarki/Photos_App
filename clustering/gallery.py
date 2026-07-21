"""Representative gallery — the heart of robust, Google-Photos-style recognition.

A person is not one average vector; they are a *diverse set* of representative
embeddings (front, profile, smiling, beard, glasses, low light, …). Recognizing
a new face by its **best** match against that set — instead of against a single
centroid — is what lets the same person be found across viewpoint, facial hair,
glasses, expression, lighting, and age.

This module is the pure logic that curates that set and derives a per-person
threshold from it. It operates on plain numpy arrays (no database), so it is
deterministic and unit-testable; :mod:`clustering.incremental` wires it to the
`person_embeddings` table.

Two responsibilities:

* :func:`select_representatives` — keep a *diverse*, quality-gated subset. Highest
  quality first, skipping near-duplicates so the gallery covers different
  appearances rather than many copies of the same one, capped in size.
* :func:`adaptive_threshold` — set each person's acceptance bar from how
  *consistent* their representatives are. A tight, consistent identity can demand
  a stricter match (fewer false accepts); a person with genuinely varied
  appearances gets a slightly more permissive bar so real variations still land.
"""

from __future__ import annotations

from typing import Optional

import numpy as np


def _max_sim_to(chosen: np.ndarray, vector: np.ndarray) -> float:
    """Largest cosine similarity between ``vector`` and any row of ``chosen``.

    Inputs are assumed L2-normalized, so the dot product is the cosine.
    ``chosen`` may be empty, in which case there is nothing to be similar to.
    """
    if chosen.shape[0] == 0:
        return -1.0
    return float((chosen @ vector).max())


def select_representatives(
    embeddings_norm: np.ndarray,
    qualities: np.ndarray,
    *,
    max_reps: int,
    diversity_sim: float,
    learn_min: float,
) -> list[int]:
    """Choose a diverse, quality-first subset; return indices into the inputs.

    Args:
        embeddings_norm: (N, dim) L2-normalized candidate embeddings.
        qualities: (N,) quality scores in [0, 1], aligned with ``embeddings_norm``.
        max_reps: maximum representatives to keep.
        diversity_sim: skip a candidate whose cosine similarity to an already-
            chosen representative exceeds this (a near-duplicate appearance).
        learn_min: preferred minimum quality; a below-``learn_min`` face is only
            taken while the person still has no representative at all, so a weak
            detection never displaces genuine diversity but coverage is guaranteed.
    """
    n = embeddings_norm.shape[0]
    if n == 0:
        return []
    order = np.argsort(qualities)[::-1]  # highest quality first
    chosen_idx: list[int] = []
    chosen_vecs = np.empty((0, embeddings_norm.shape[1]), dtype=np.float32)

    for i in order:
        i = int(i)
        weak = qualities[i] < learn_min
        if weak and chosen_idx:
            continue  # already have a real representative; don't add weak ones
        if _max_sim_to(chosen_vecs, embeddings_norm[i]) > diversity_sim:
            continue  # near-duplicate of an existing representative
        chosen_idx.append(i)
        chosen_vecs = np.vstack([chosen_vecs, embeddings_norm[i][None, :]])
        if len(chosen_idx) >= max_reps:
            break
    return chosen_idx


def consistency(embeddings_norm: np.ndarray) -> float:
    """Mean pairwise cosine similarity of a set (its internal tightness), 0..1.

    A single vector (or none) has no spread; treat it as fully consistent.
    """
    n = embeddings_norm.shape[0]
    if n < 2:
        return 1.0
    sims = embeddings_norm @ embeddings_norm.T
    off_diagonal_sum = float(sims.sum() - np.trace(sims))
    mean = off_diagonal_sum / (n * (n - 1))
    return float(np.clip(mean, 0.0, 1.0))


def adaptive_threshold(
    representatives_norm: np.ndarray,
    *,
    global_threshold: float,
    lo: float,
    hi: float,
    min_reps: int,
    strict_min_reps: int = 0,
) -> Optional[float]:
    """Per-person acceptance threshold from representative consistency.

    Returns ``None`` (meaning "use the global default") until the person has at
    least ``min_reps`` representatives — thresholds should adapt only once there
    is enough evidence. Otherwise centers on ``global_threshold`` at consistency
    0.5 and shifts within ``[lo, hi]``: more consistent -> stricter, more varied
    -> more permissive.

    ``strict_min_reps`` guards against self-inflicted fragmentation: a young
    gallery holding a single appearance looks *very* consistent, and a raised
    bar would lock out that person's other appearances (profile, beard, new
    hairstyle) — spawning duplicate profiles. Until the gallery is genuinely
    diverse (that many representatives), the threshold may only be *at or below*
    the global default, never above it.
    """
    n = representatives_norm.shape[0]
    if n < min_reps:
        return None
    margin = hi - lo
    shift = (consistency(representatives_norm) - 0.5) * margin
    threshold = float(np.clip(global_threshold + shift, lo, hi))
    if n < strict_min_reps:
        threshold = min(threshold, global_threshold)
    return threshold
