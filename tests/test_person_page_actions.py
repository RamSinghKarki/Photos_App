"""Widget-level tests for the person-page correction flows (audit item T1/P0-3).

These exercise the *Qt wiring* — handler → database action → page refresh /
navigation — not just the ``viewer.data`` functions underneath. They poll for the
expected end state (pump-until pattern) so they hold whether the actions run
synchronously or on a background worker; they were written *before* the
off-thread refactor precisely to guard it.
"""

from __future__ import annotations

import datetime as _dt
import os
import time

import numpy as np
import pytest

os.environ["QT_QPA_PLATFORM"] = "offscreen"

pytest.importorskip("PySide6")

from PySide6 import QtWidgets  # noqa: E402

from clustering.clusterer import normalize_embeddings, person_centroid  # noqa: E402
from clustering.incremental import rebuild_person_gallery  # noqa: E402
from database import db  # noqa: E402

DIM = 512
_RNG = np.random.default_rng(41)
_CENTER = normalize_embeddings(_RNG.standard_normal((1, DIM)).astype("float32"))[0]


@pytest.fixture(scope="module")
def qapp():
    from viewer.app import create_application

    yield create_application([])


def _pump_until(qapp, condition, timeout: float = 8.0) -> None:
    """Process events until ``condition()`` is true (works sync or async)."""
    deadline = time.time() + timeout
    while not condition():
        if time.time() > deadline:
            raise AssertionError("timed out waiting for the action to take effect")
        qapp.processEvents()
        time.sleep(0.01)


def _photo(path: str) -> int:
    meta = db.PhotoMetadata(
        file_path=path, file_hash="0" * 64, file_size=1,
        file_mtime=_dt.datetime(2021, 1, 1),
    )
    with db.connection() as conn, conn.cursor() as cur:
        return db.insert_photo(cur, meta)


def _face(photo_id: int, noise: float = 0.01) -> int:
    emb = _CENTER + _RNG.standard_normal(DIM).astype("float32") * noise
    with db.connection() as conn, conn.cursor() as cur:
        return db.insert_face(cur, photo_id, (0, 0, 120, 120), emb.tolist(), det_score=0.9)


def _person(face_ids: list[int]) -> int:
    with db.connection() as conn, conn.cursor() as cur:
        pid = db.create_person(cur, len(face_ids), face_ids[0])
        db.assign_faces_to_person(cur, pid, face_ids)
        embs = np.vstack([_CENTER] * len(face_ids))
        db.set_person_centroid(cur, pid, person_centroid(embs))
        rebuild_person_gallery(cur, pid)
    return pid


def _face_person(face_id: int):
    with db.connection() as conn, conn.cursor() as cur:
        cur.execute("SELECT person_id FROM faces WHERE id = %s", (face_id,))
        return cur.fetchone()[0]


def test_confirm_suggestion_assigns_and_refreshes(qapp, clean_db) -> None:
    from viewer.pages import PersonDetailPage

    pid = _person([_face(_photo(f"/virtual/pa_c_{i}.jpg")) for i in range(3)])
    loose = _face(_photo("/virtual/pa_c_loose.jpg"))
    with db.connection() as conn, conn.cursor() as cur:
        db.record_suggestion(cur, loose, pid, 0.53)

    page = PersonDetailPage()
    changed: list[int] = []
    page.person_changed.connect(lambda: changed.append(1))
    page.show_person(pid, "Ram")
    assert page._suggestions.isVisible() or page._suggestions.isVisibleTo(page)

    page._on_confirm_suggestion(loose)
    _pump_until(qapp, lambda: _face_person(loose) == pid)
    _pump_until(qapp, lambda: bool(changed))

    with db.connection() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT verdict FROM recognition_feedback WHERE face_id = %s AND person_id = %s",
            (loose, pid),
        )
        assert cur.fetchone()[0] == "confirm"
        assert not db.list_suggestions_for_person(cur, pid)


def test_reject_suggestion_records_and_clears(qapp, clean_db) -> None:
    from viewer.pages import PersonDetailPage

    pid = _person([_face(_photo(f"/virtual/pa_r_{i}.jpg")) for i in range(3)])
    loose = _face(_photo("/virtual/pa_r_loose.jpg"))
    with db.connection() as conn, conn.cursor() as cur:
        db.record_suggestion(cur, loose, pid, 0.53)

    page = PersonDetailPage()
    page.show_person(pid, "Ram")
    page._on_reject_suggestion(loose)

    def rejected() -> bool:
        with db.connection() as conn, conn.cursor() as cur:
            return loose in db.fetch_rejections(cur).get(pid, set())

    _pump_until(qapp, rejected)
    assert _face_person(loose) is None  # stays ungrouped
    with db.connection() as conn, conn.cursor() as cur:
        assert not db.list_suggestions_for_person(cur, pid)


def test_remove_from_person_detaches_and_remembers(qapp, clean_db, monkeypatch) -> None:
    from viewer.pages import PersonDetailPage

    photos = [_photo(f"/virtual/pa_m_{i}.jpg") for i in range(3)]
    faces = [_face(p) for p in photos]
    pid = _person(faces)

    monkeypatch.setattr(
        QtWidgets.QMessageBox, "question",
        staticmethod(lambda *a, **k: QtWidgets.QMessageBox.StandardButton.Yes),
    )

    page = PersonDetailPage()
    changed: list[int] = []
    page.person_changed.connect(lambda: changed.append(1))
    page.show_person(pid, "Ram")

    page._on_remove_from_person([photos[0]])
    _pump_until(qapp, lambda: _face_person(faces[0]) is None)
    _pump_until(qapp, lambda: bool(changed))

    with db.connection() as conn, conn.cursor() as cur:
        assert faces[0] in db.fetch_rejections(cur).get(pid, set())
        cur.execute("SELECT face_count FROM persons WHERE id = %s", (pid,))
        assert cur.fetchone()[0] == 2  # profile re-curated over the remaining faces
    assert _face_person(faces[1]) == pid  # others untouched


def test_action_error_shows_dialog_not_crash(qapp, clean_db, monkeypatch) -> None:
    """A failing DB action must surface an error dialog, not die silently."""
    from viewer import data
    from viewer.pages import PersonDetailPage

    pid = _person([_face(_photo("/virtual/pa_e_0.jpg"))])
    loose = _face(_photo("/virtual/pa_e_loose.jpg"))
    with db.connection() as conn, conn.cursor() as cur:
        db.record_suggestion(cur, loose, pid, 0.53)

    def boom(*_a, **_k):
        raise RuntimeError("simulated db failure")

    monkeypatch.setattr(data, "confirm_suggestion", boom)
    warnings: list[str] = []
    monkeypatch.setattr(
        QtWidgets.QMessageBox, "warning",
        staticmethod(lambda _p, title, msg, *a, **k: warnings.append(str(msg))),
    )

    page = PersonDetailPage()
    page.show_person(pid, "Ram")
    page._on_confirm_suggestion(loose)
    _pump_until(qapp, lambda: bool(warnings))
    assert "simulated db failure" in warnings[0]
    assert _face_person(loose) is None  # nothing was assigned
