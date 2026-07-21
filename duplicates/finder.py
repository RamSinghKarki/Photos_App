"""Group visually-identical photos from their perceptual hashes.

Pure grouping logic + a thin DB assembly step:

* :func:`group_hashes` — union-find over candidate pairs. Candidates come from
  **banding**: each 64-bit hash is split into eight 8-bit chunks, and two
  hashes are only compared if they share at least one (position, value) chunk.
  By pigeonhole, any pair within Hamming distance ≤ 7 must share a chunk, so
  banding is exact for our threshold (default 5) while avoiding the O(n²)
  all-pairs scan — a 100k-photo library compares only within tiny buckets.
* :func:`find_duplicate_groups` — resolves groups to photo rows, drops sets
  the user already dismissed ("these are different"), and orders largest
  group first. Nothing here ever deletes or modifies a photo.
"""

from __future__ import annotations

from collections import defaultdict
from typing import Any, Optional

from config.settings import get_settings
from database import db
from duplicates.phash import from_signed, hamming

_CHUNKS = 8          # 8 chunks × 8 bits; exact for any threshold ≤ 7
_CHUNK_BITS = 64 // _CHUNKS
_MASK = (1 << _CHUNK_BITS) - 1


class _UnionFind:
    def __init__(self) -> None:
        self._parent: dict[int, int] = {}

    def find(self, x: int) -> int:
        parent = self._parent.setdefault(x, x)
        if parent != x:
            parent = self._parent[x] = self.find(parent)
        return parent

    def union(self, a: int, b: int) -> None:
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self._parent[rb] = ra


def group_hashes(
    rows: list[tuple[int, int]], max_distance: int
) -> list[list[int]]:
    """Group (photo_id, signed_phash) rows into duplicate sets (size ≥ 2)."""
    hashes = {pid: from_signed(ph) for pid, ph in rows}

    buckets: dict[tuple[int, int], list[int]] = defaultdict(list)
    for pid, value in hashes.items():
        for chunk in range(_CHUNKS):
            buckets[(chunk, (value >> (chunk * _CHUNK_BITS)) & _MASK)].append(pid)

    # Within a bucket, compare every pair (buckets are tiny) and union those
    # within the threshold. Pairs are deduplicated across buckets by union-find.
    uf = _UnionFind()
    for members in buckets.values():
        if len(members) < 2:
            continue
        for i, a in enumerate(members):
            for b in members[i + 1:]:
                if uf.find(a) != uf.find(b) and \
                        hamming(hashes[a], hashes[b]) <= max_distance:
                    uf.union(a, b)

    groups: dict[int, list[int]] = defaultdict(list)
    for pid in hashes:
        groups[uf.find(pid)].append(pid)
    return sorted(
        (sorted(g) for g in groups.values() if len(g) >= 2),
        key=len, reverse=True,
    )


def find_duplicate_groups(
    cur, max_distance: Optional[int] = None, limit: int = 50
) -> list[dict[str, Any]]:
    """Pending duplicate groups with photo details, biggest first.

    Each group: ``{"key", "photos": [(id, path, thumb, taken_at, size), …]}``
    with photos ordered largest file first (the natural "keep" candidate).
    Groups the user dismissed are excluded.
    """
    if max_distance is None:
        max_distance = get_settings().phash_max_distance
    dismissed = db.fetch_duplicate_dismissals(cur)

    result: list[dict[str, Any]] = []
    for ids in group_hashes(db.list_phashes(cur), max_distance):
        key = db.duplicate_group_key(ids)
        if key in dismissed:
            continue
        result.append({"key": key, "photos": db.list_photos_brief_by_ids(cur, ids)})
        if len(result) >= limit:
            break
    return result
