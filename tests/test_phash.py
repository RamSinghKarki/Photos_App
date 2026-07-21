"""Unit tests for perceptual hashing (duplicates.phash) — no database."""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw

from duplicates.phash import dhash, from_signed, hamming, to_signed


def _photo(path: Path, size=(320, 240)) -> Path:
    """A non-uniform test image (gradient + shapes) so dHash has structure."""
    img = Image.new("RGB", size)
    draw = ImageDraw.Draw(img)
    for x in range(size[0]):
        draw.line([(x, 0), (x, size[1])], fill=(x % 256, (x * 2) % 256, 80))
    draw.ellipse([40, 40, 160, 160], fill=(240, 220, 40))
    img.save(path, "JPEG", quality=92)
    return path


def test_reencoded_and_resized_copies_match(tmp_path: Path) -> None:
    original = _photo(tmp_path / "a.jpg")
    h0 = dhash(original)
    assert h0 is not None

    img = Image.open(original)
    img.save(tmp_path / "recompressed.jpg", "JPEG", quality=35)
    img.resize((160, 120)).save(tmp_path / "small.jpg", "JPEG", quality=85)

    assert hamming(h0, dhash(tmp_path / "recompressed.jpg")) <= 5
    assert hamming(h0, dhash(tmp_path / "small.jpg")) <= 5


def test_different_images_are_far_apart(tmp_path: Path) -> None:
    a = dhash(_photo(tmp_path / "a.jpg"))
    flat = Image.new("RGB", (320, 240), "white")
    d = ImageDraw.Draw(flat)
    d.rectangle([0, 0, 160, 240], fill="black")
    flat.save(tmp_path / "b.jpg", "JPEG")
    b = dhash(tmp_path / "b.jpg")
    assert hamming(a, b) > 16


def test_unreadable_file_returns_none(tmp_path: Path) -> None:
    bad = tmp_path / "bad.jpg"
    bad.write_bytes(b"not an image")
    assert dhash(bad) is None


def test_signed_round_trip() -> None:
    for value in (0, 1, 2**63 - 1, 2**63, 2**64 - 1):
        assert from_signed(to_signed(value)) == value
        assert -(2**63) <= to_signed(value) <= 2**63 - 1


def test_processor_hashes_library_idempotently(clean_db, photo_tree) -> None:
    from database import db
    from duplicates.processor import process_phashes
    from scanner.scanner import scan_directory

    scan_directory(photo_tree)
    first = process_phashes()
    # 4 decodable photos + broken.jpg marked unreadable, exactly once.
    assert first.hashed == 4 and first.unreadable == 1

    second = process_phashes()  # nothing left to do
    assert second.hashed == 0 and second.unreadable == 0

    with db.connection() as conn, conn.cursor() as cur:
        cur.execute("SELECT count(*) FROM photos WHERE phash IS NULL")
        assert cur.fetchone()[0] == 0
        # The byte-identical copy hashes identically to its original.
        cur.execute("SELECT phash FROM photos WHERE file_path LIKE '%a.jpg'")
        h_a = cur.fetchone()[0]
        cur.execute("SELECT phash FROM photos WHERE file_path LIKE '%a_copy.jpg'")
        assert cur.fetchone()[0] == h_a
