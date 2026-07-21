"""Backup and restore of user-generated knowledge (names, corrections, favorites).

What gets exported is the *irreplaceable* layer: person names and which faces
belong to them (the materialized result of every merge and correction),
recognition feedback (durable yes/no answers), and favorites. Everything is
keyed by **stable natural keys** — a photo's content hash and a face's bounding
box — never database ids, so a backup restores correctly into a fresh database
or after a re-import. Original photo files are never touched.

Safety rules:

* **Versioned** — the file carries ``format``; unknown versions are refused.
* **Validated before restore** — structure problems abort with a message list;
  nothing is written unless validation passes.
* **Non-destructive** — restore only adds/renames; it never deletes people,
  detaches faces, or clears favorites. Unmatched entries are counted and
  reported, not errors.
"""

from __future__ import annotations

import datetime as _dt
import json
from pathlib import Path
from typing import Any

FORMAT = 1

_FaceKey = tuple[str, int, int, int, int]  # file_hash + bbox


def _face_key_row(row) -> list:
    return [row[0], int(row[1]), int(row[2]), int(row[3]), int(row[4])]


def export_knowledge(cur) -> dict[str, Any]:
    """Collect the knowledge layer into a plain, versioned dict."""
    cur.execute("SELECT file_hash FROM photos WHERE is_favorite")
    favorites = [r[0] for r in cur.fetchall()]

    cur.execute(
        """
        SELECT p.display_name, ph.file_hash, f.bbox_x, f.bbox_y, f.bbox_w, f.bbox_h
          FROM persons p
          JOIN faces f ON f.person_id = p.id
          JOIN photos ph ON ph.id = f.photo_id
         WHERE p.display_name IS NOT NULL
         ORDER BY p.id, f.id
        """
    )
    people: dict[str, list] = {}
    for name, *face in cur.fetchall():
        people.setdefault(name, []).append(_face_key_row(face))

    cur.execute(
        """
        SELECT ph.file_hash, f.bbox_x, f.bbox_y, f.bbox_w, f.bbox_h,
               p.display_name, rf.verdict
          FROM recognition_feedback rf
          JOIN faces f ON f.id = rf.face_id
          JOIN photos ph ON ph.id = f.photo_id
          JOIN persons p ON p.id = rf.person_id
         WHERE p.display_name IS NOT NULL
        """
    )
    feedback = [
        {"face": _face_key_row(r[:5]), "person": r[5], "verdict": r[6]}
        for r in cur.fetchall()
    ]

    return {
        "format": FORMAT,
        "created": _dt.datetime.now().isoformat(timespec="seconds"),
        "favorites": favorites,
        "people": [{"name": n, "faces": faces} for n, faces in people.items()],
        "feedback": feedback,
    }


def save_backup(cur, path: Path) -> dict[str, Any]:
    """Export and write atomically; returns the exported dict."""
    data = export_knowledge(cur)
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, indent=1), "utf-8")
    tmp.replace(path)
    return data


def validate_backup(data: Any) -> list[str]:
    """Return a list of problems; empty means safe to restore."""
    problems: list[str] = []
    if not isinstance(data, dict):
        return ["backup is not a JSON object"]
    if data.get("format") != FORMAT:
        problems.append(f"unsupported format {data.get('format')!r} (expected {FORMAT})")
    if not isinstance(data.get("favorites", []), list):
        problems.append("'favorites' must be a list of file hashes")
    for i, person in enumerate(data.get("people", []) or []):
        if not isinstance(person, dict) or not person.get("name"):
            problems.append(f"people[{i}] missing a name")
        elif not isinstance(person.get("faces"), list):
            problems.append(f"people[{i}] ('{person.get('name')}') has no face list")
    for i, fb in enumerate(data.get("feedback", []) or []):
        if not isinstance(fb, dict) or fb.get("verdict") not in ("confirm", "reject") \
                or not fb.get("person") or not isinstance(fb.get("face"), list):
            problems.append(f"feedback[{i}] malformed")
    return problems


def _find_face(cur, key: list) -> int | None:
    cur.execute(
        """
        SELECT f.id FROM faces f JOIN photos ph ON ph.id = f.photo_id
         WHERE ph.file_hash = %s AND f.bbox_x = %s AND f.bbox_y = %s
           AND f.bbox_w = %s AND f.bbox_h = %s
         LIMIT 1
        """,
        tuple(key),
    )
    row = cur.fetchone()
    return int(row[0]) if row else None


def restore_knowledge(cur, data: dict[str, Any]) -> dict[str, int]:
    """Apply a validated backup additively; returns a match/skip report.

    Raises ValueError if the backup does not validate — call sites can rely on
    nothing having been written in that case.
    """
    problems = validate_backup(data)
    if problems:
        raise ValueError("invalid backup: " + "; ".join(problems))

    from database import db

    report = {"favorites": 0, "favorites_skipped": 0, "people": 0,
              "faces_assigned": 0, "faces_skipped": 0,
              "feedback": 0, "feedback_skipped": 0}

    for file_hash in data.get("favorites", []):
        cur.execute(
            "UPDATE photos SET is_favorite = TRUE WHERE file_hash = %s", (file_hash,))
        report["favorites" if cur.rowcount else "favorites_skipped"] += 1

    name_to_person: dict[str, int] = {}
    for person in data.get("people", []):
        name = person["name"]
        face_ids = [fid for key in person["faces"]
                    if (fid := _find_face(cur, key)) is not None]
        report["faces_skipped"] += len(person["faces"]) - len(face_ids)
        if not face_ids:
            continue
        cur.execute("SELECT id FROM persons WHERE display_name = %s LIMIT 1", (name,))
        row = cur.fetchone()
        if row:
            person_id = int(row[0])
        else:
            person_id = db.create_person(cur, 0, face_ids[0])
            db.rename_person(cur, person_id, name)
            report["people"] += 1
        db.assign_faces_to_person(cur, person_id, face_ids)
        db.recompute_person_profile(cur, person_id)
        report["faces_assigned"] += len(face_ids)
        name_to_person[name] = person_id

    for fb in data.get("feedback", []):
        face_id = _find_face(cur, fb["face"])
        person_id = name_to_person.get(fb["person"])
        if person_id is None:
            cur.execute("SELECT id FROM persons WHERE display_name = %s LIMIT 1",
                        (fb["person"],))
            row = cur.fetchone()
            person_id = int(row[0]) if row else None
        if face_id is None or person_id is None:
            report["feedback_skipped"] += 1
            continue
        db.record_feedback(cur, face_id, person_id, fb["verdict"])
        report["feedback"] += 1

    return report


def load_backup(path: Path) -> dict[str, Any]:
    """Read a backup file; raises ValueError with a clear message if unusable."""
    try:
        data = json.loads(Path(path).read_text("utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"could not read backup: {exc}") from exc
    problems = validate_backup(data)
    if problems:
        raise ValueError("invalid backup: " + "; ".join(problems))
    return data
