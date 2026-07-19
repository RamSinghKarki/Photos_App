"""Unit tests for the representative gallery logic (pure numpy, no database)."""

from __future__ import annotations

import numpy as np

from clustering.gallery import (
    adaptive_threshold,
    consistency,
    select_representatives,
)


def _unit(rows) -> np.ndarray:
    arr = np.asarray(rows, dtype=np.float32)
    norms = np.linalg.norm(arr, axis=1, keepdims=True)
    return arr / norms


def test_near_duplicates_collapse_to_the_best_one() -> None:
    # Three near-identical "front face" vectors + one distinct "profile".
    embs = _unit([
        [1, 0.0, 0, 0],
        [1, 0.05, 0, 0],
        [1, 0.1, 0, 0],
        [0, 1, 0, 0],
    ])
    quals = np.array([0.8, 0.95, 0.85, 0.9], dtype=np.float32)
    reps = select_representatives(embs, quals, max_reps=12, diversity_sim=0.92, learn_min=0.55)
    # The distinct appearance is kept; the front-face trio contributes just one —
    # the highest-quality of them (index 1).
    assert sorted(reps) == [1, 3]


def test_capped_at_max_reps() -> None:
    embs = _unit(np.eye(6))  # six orthogonal (fully distinct) appearances
    quals = np.linspace(0.6, 0.95, 6).astype(np.float32)
    reps = select_representatives(embs, quals, max_reps=3, diversity_sim=0.92, learn_min=0.55)
    assert len(reps) == 3  # diversity would keep all six; the cap wins


def test_weak_faces_only_seed_when_nothing_better() -> None:
    embs = _unit(np.eye(4))
    quals = np.array([0.40, 0.30, 0.45, 0.35], dtype=np.float32)  # all below learn_min
    reps = select_representatives(embs, quals, max_reps=12, diversity_sim=0.92, learn_min=0.55)
    assert reps == [2]  # only the single best is seeded (highest quality index)


def test_consistency_bounds() -> None:
    identical = _unit([[1, 0, 0, 0], [1, 0, 0, 0], [1, 0, 0, 0]])
    assert consistency(identical) == 1.0
    orthogonal = _unit(np.eye(4))
    assert abs(consistency(orthogonal)) < 1e-6
    assert consistency(_unit([[1, 0, 0, 0]])) == 1.0  # a lone vector: no spread


def test_adaptive_threshold_needs_enough_reps() -> None:
    two = _unit([[1, 0, 0, 0], [0, 1, 0, 0]])
    assert adaptive_threshold(two, global_threshold=0.55, lo=0.45, hi=0.62, min_reps=3) is None


def test_adaptive_threshold_stricter_when_more_consistent() -> None:
    tight = _unit([[1, 0.02, 0, 0], [1, 0.0, 0, 0], [1, 0.04, 0, 0]])  # very consistent
    loose = _unit(np.eye(3))                                            # very spread
    t_tight = adaptive_threshold(tight, global_threshold=0.55, lo=0.45, hi=0.62, min_reps=3)
    t_loose = adaptive_threshold(loose, global_threshold=0.55, lo=0.45, hi=0.62, min_reps=3)
    assert t_tight is not None and t_loose is not None
    assert 0.45 <= t_loose <= 0.55 <= t_tight <= 0.62  # consistent -> stricter bar
