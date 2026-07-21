"""Unit tests for scanner.metadata (no database required)."""

from __future__ import annotations

import datetime as _dt
from pathlib import Path

from scanner.metadata import (
    _convert_gps_coordinate,
    _parse_exif_datetime,
    compute_file_hash,
    extract_metadata,
)


def test_hash_is_deterministic_and_content_based(tmp_path: Path) -> None:
    a = tmp_path / "a.bin"
    b = tmp_path / "b.bin"
    a.write_bytes(b"identical")
    b.write_bytes(b"identical")
    assert compute_file_hash(a) == compute_file_hash(b)

    b.write_bytes(b"different")
    assert compute_file_hash(a) != compute_file_hash(b)


def test_parse_exif_datetime() -> None:
    assert _parse_exif_datetime("2021:07:04 12:34:56") == _dt.datetime(2021, 7, 4, 12, 34, 56)
    assert _parse_exif_datetime("not a date") is None
    assert _parse_exif_datetime(None) is None


def test_gps_conversion_sign_and_value() -> None:
    # 37°46'30" N -> +37.775
    north = _convert_gps_coordinate((37.0, 46.0, 30.0), "N")
    assert north is not None and abs(north - 37.775) < 1e-6
    # 122°25'10" W -> negative
    west = _convert_gps_coordinate((122.0, 25.0, 10.0), "W")
    assert west is not None and west < 0
    # malformed input degrades to None
    assert _convert_gps_coordinate(None, "N") is None
    assert _convert_gps_coordinate((1.0, 2.0), "N") is None
    # a 0/0 EXIF rational floats to NaN — must degrade to None, never store NaN
    assert _convert_gps_coordinate((float("nan"), 0.0, 0.0), "N") is None


def test_extract_metadata_reads_exif(photo_tree: Path) -> None:
    meta = extract_metadata(photo_tree / "with_exif.jpg")
    assert (meta.width, meta.height) == (200, 150)
    assert meta.format == "JPEG"
    assert meta.camera_make == "TestMake"
    assert meta.camera_model == "TestModel"
    assert meta.taken_at == _dt.datetime(2021, 7, 4, 12, 34, 56)
    assert meta.gps_latitude is not None and abs(meta.gps_latitude - 37.775) < 1e-4
    assert meta.gps_longitude is not None and meta.gps_longitude < 0


def test_extract_metadata_survives_corrupt_image(photo_tree: Path) -> None:
    # A file with image extension but invalid bytes must still yield identity
    # metadata (hash/size) rather than raising.
    meta = extract_metadata(photo_tree / "broken.jpg")
    assert meta.file_size > 0
    assert len(meta.file_hash) == 64  # sha256 hex length
    assert meta.width is None and meta.height is None
