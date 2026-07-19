"""Unit tests for face quality scoring (pure, no database, no image I/O)."""

from __future__ import annotations

from clustering.quality import face_quality, quality_band


def test_score_is_bounded() -> None:
    # Extremes clamp into [0, 1] regardless of inputs.
    assert 0.0 <= face_quality(0.0, 0, 0) <= 1.0
    assert 0.0 <= face_quality(1.0, 1000, 1000) <= 1.0
    assert face_quality(None, 200, 200) == face_quality(0.0, 200, 200)


def test_higher_confidence_and_resolution_score_higher() -> None:
    tiny_blurry = face_quality(0.5, 20, 20)
    big_confident = face_quality(0.95, 200, 200)
    assert big_confident > tiny_blurry
    # A large, high-confidence face should be near the top of the range.
    assert big_confident > 0.9
    # A tiny, low-confidence detection should be poor.
    assert tiny_blurry < 0.4


def test_resolution_and_confidence_each_matter() -> None:
    # Same big size, better detector -> higher score.
    assert face_quality(0.9, 200, 200) > face_quality(0.6, 200, 200)
    # Same detector, bigger face -> higher score.
    assert face_quality(0.9, 200, 200) > face_quality(0.9, 45, 45)


def test_sharpness_blends_in_when_supplied() -> None:
    base = face_quality(0.9, 200, 200)                 # no blur term
    sharp = face_quality(0.9, 200, 200, sharpness=800)  # crisp
    blurry = face_quality(0.9, 200, 200, sharpness=20)  # smeared
    assert blurry < base           # a blurry crop is penalized
    assert sharp >= base - 1e-6    # a crisp crop is not penalized
    assert sharp > blurry


def test_quality_bands() -> None:
    assert quality_band(0.95) == "excellent"
    assert quality_band(0.7) == "good"
    assert quality_band(0.4) == "store"
    assert quality_band(0.1) == "ignore"
