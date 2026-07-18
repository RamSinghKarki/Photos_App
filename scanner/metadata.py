"""Image metadata extraction for the scanner.

Given a path on disk, produce a :class:`~database.db.PhotoMetadata` describing
the file: its content hash and size (for identity and dedup) plus whatever EXIF
the image carries (dimensions, capture time, camera, orientation, GPS).

Robustness is a hard requirement: one corrupt or unreadable file must never
abort a scan. Extraction therefore reads identity information first (which only
needs the raw bytes) and treats every EXIF lookup as best-effort — a failure to
parse a tag downgrades to ``None`` rather than raising.
"""

from __future__ import annotations

import datetime as _dt
import hashlib
from pathlib import Path
from typing import Any, Optional

from PIL import ExifTags, Image

from database.db import PhotoMetadata
from utils.logging_setup import get_logger

logger = get_logger("scanner.metadata")

# Reverse lookups so we can address EXIF tags by name instead of magic numbers.
_TAG_IDS: dict[str, int] = {name: num for num, name in ExifTags.TAGS.items()}
_GPS_IDS: dict[str, int] = {name: num for num, name in ExifTags.GPSTAGS.items()}

# Sub-IFD pointers within the base EXIF IFD.
_EXIF_IFD = 0x8769
_GPS_IFD = 0x8825

_HASH_CHUNK = 1 << 20  # 1 MiB — hash in chunks so large files never load fully.


def compute_file_hash(path: Path) -> str:
    """Return the SHA-256 hex digest of a file's bytes, read in chunks."""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(_HASH_CHUNK), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _parse_exif_datetime(value: Any) -> Optional[_dt.datetime]:
    """Parse an EXIF datetime string ('YYYY:MM:DD HH:MM:SS') if possible."""
    if not isinstance(value, str):
        return None
    try:
        return _dt.datetime.strptime(value.strip(), "%Y:%m:%d %H:%M:%S")
    except ValueError:
        return None


def _to_float(value: Any) -> Optional[float]:
    """Best-effort conversion of an EXIF rational/number to float."""
    try:
        return float(value)
    except (TypeError, ValueError, ZeroDivisionError):
        return None


def _convert_gps_coordinate(dms: Any, ref: Any) -> Optional[float]:
    """Convert an EXIF (degrees, minutes, seconds) tuple + ref to decimal.

    ``ref`` of 'S' or 'W' yields a negative value. Returns ``None`` when the
    data is missing or malformed.
    """
    if not dms or len(dms) != 3:
        return None
    degrees, minutes, seconds = (_to_float(part) for part in dms)
    if degrees is None or minutes is None or seconds is None:
        return None
    decimal = degrees + minutes / 60.0 + seconds / 3600.0
    if isinstance(ref, str) and ref.upper() in ("S", "W"):
        decimal = -decimal
    return decimal


def _extract_gps(exif: Image.Exif) -> tuple[Optional[float], Optional[float]]:
    """Return (latitude, longitude) in decimal degrees, or (None, None)."""
    try:
        gps = exif.get_ifd(_GPS_IFD)
    except Exception:  # noqa: BLE001 - any malformed IFD must not abort a scan
        return None, None
    if not gps:
        return None, None

    lat = _convert_gps_coordinate(
        gps.get(_GPS_IDS.get("GPSLatitude")), gps.get(_GPS_IDS.get("GPSLatitudeRef"))
    )
    lon = _convert_gps_coordinate(
        gps.get(_GPS_IDS.get("GPSLongitude")), gps.get(_GPS_IDS.get("GPSLongitudeRef"))
    )
    return lat, lon


def extract_metadata(path: Path) -> PhotoMetadata:
    """Build a :class:`PhotoMetadata` for ``path``.

    Identity fields (hash, size, mtime) always succeed for a readable file.
    Image and EXIF fields are best-effort and default to ``None``.

    Raises:
        OSError: if the file cannot be read at all (caller treats as a skip).
    """
    stat = path.stat()
    file_hash = compute_file_hash(path)
    mtime = _dt.datetime.fromtimestamp(stat.st_mtime)

    width = height = None
    image_format: Optional[str] = None
    taken_at = camera_make = camera_model = None
    orientation = None
    gps_lat = gps_lon = None

    try:
        with Image.open(path) as img:
            width, height = img.size
            image_format = img.format
            exif = img.getexif()
            if exif:
                make = exif.get(_TAG_IDS.get("Make"))
                model = exif.get(_TAG_IDS.get("Model"))
                orient = exif.get(_TAG_IDS.get("Orientation"))
                camera_make = str(make).strip() if make else None
                camera_model = str(model).strip() if model else None
                orientation = int(orient) if isinstance(orient, int) else None

                # DateTimeOriginal lives in the Exif sub-IFD; fall back to the
                # base DateTime tag if the original capture time is absent.
                exif_ifd = exif.get_ifd(_EXIF_IFD) or {}
                taken_at = _parse_exif_datetime(
                    exif_ifd.get(_TAG_IDS.get("DateTimeOriginal"))
                ) or _parse_exif_datetime(exif.get(_TAG_IDS.get("DateTime")))

                gps_lat, gps_lon = _extract_gps(exif)
    except Exception as exc:  # noqa: BLE001 - decode/EXIF errors are non-fatal
        # We still have valid identity metadata, so keep the photo but note the
        # image could not be fully parsed. This is why one bad EXIF block never
        # loses a file.
        logger.warning("Could not read image data for %s: %s", path, exc)

    return PhotoMetadata(
        file_path=str(path),
        file_hash=file_hash,
        file_size=stat.st_size,
        file_mtime=mtime,
        width=width,
        height=height,
        format=image_format,
        taken_at=taken_at,
        camera_make=camera_make,
        camera_model=camera_model,
        orientation=orientation,
        gps_latitude=gps_lat,
        gps_longitude=gps_lon,
    )
