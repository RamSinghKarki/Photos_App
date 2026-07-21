"""Face quality assessment — decide which detections are trusted to *teach*.

Not every detected face should shape a person's identity. A tiny, blurry, or
low-confidence detection is fine to *show*, but letting it update a person's
representative gallery corrupts recognition. This module turns the signals we
already store per face into a single 0..1 quality score; the recognition engine
uses it to gate learning (ignore / store-only / representative).

The score is a **pure function** of features, so it is deterministic and unit-
testable with no image I/O. Today it fuses detector confidence and face
resolution — the two signals present on every `faces` row. Blur, pose, and
occlusion are designed in as optional terms: pass ``sharpness`` when a caller
has computed it (Laplacian variance of the crop) and it blends in automatically;
richer terms slot into :func:`face_quality` the same way without changing callers.
"""

from __future__ import annotations

from typing import Optional

# Resolution mapping (min side, pixels): below MIN is unusable, at/above FULL is
# ideal (InsightFace aligns to ~112 px, so a face captured that large is sharp
# and detailed enough to trust fully).
_RES_MIN_PX = 40.0
_RES_FULL_PX = 112.0

# Sharpness mapping (variance of the Laplacian): a common, model-free blur proxy.
_SHARP_BLURRY = 100.0
_SHARP_SHARP = 500.0


def _clamp01(value: float) -> float:
    return 0.0 if value < 0.0 else 1.0 if value > 1.0 else value


def _ramp(value: float, lo: float, hi: float) -> float:
    """Linearly map ``value`` from [lo, hi] onto [0, 1], clamped at the ends."""
    if hi <= lo:
        return 0.0
    return _clamp01((value - lo) / (hi - lo))


def face_quality(
    det_score: Optional[float],
    bbox_w: int,
    bbox_h: int,
    sharpness: Optional[float] = None,
) -> float:
    """Return a 0..1 quality score for one detected face.

    Args:
        det_score: detector confidence (InsightFace, ~0..1); ``None`` -> 0.
        bbox_w, bbox_h: face bounding-box size in pixels (resolution proxy).
        sharpness: optional variance-of-Laplacian blur proxy; blends in when given.

    The terms are averaged with weights that sum to 1, so the result stays in
    [0, 1] whether or not the optional sharpness term is supplied.
    """
    confidence = _clamp01(det_score if det_score is not None else 0.0)
    resolution = _ramp(float(min(bbox_w, bbox_h)), _RES_MIN_PX, _RES_FULL_PX)

    if sharpness is None:
        # Two-signal blend (detector + resolution), weights renormalized to 1.
        return 0.5 * confidence + 0.5 * resolution

    sharp = _ramp(float(sharpness), _SHARP_BLURRY, _SHARP_SHARP)
    return 0.4 * confidence + 0.4 * resolution + 0.2 * sharp


# Human-readable bands (used in docs/UI and to explain a gating decision).
def quality_band(score: float) -> str:
    """Coarse label for a quality score: excellent / good / store / ignore."""
    if score >= 0.8:
        return "excellent"
    if score >= 0.6:
        return "good"
    if score >= 0.35:
        return "store"
    return "ignore"
