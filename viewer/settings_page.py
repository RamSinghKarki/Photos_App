"""Settings — user-friendly preferences over :mod:`config.user_config`.

Grouped sections (General / Appearance / AI & Recognition / Performance /
Storage / Database / Advanced) with plain-language controls. Values validate
and persist on change (atomic JSON under ``~/.photosphere``); wherever
practical they apply live — reduced motion and search size are read at use
time, pipeline-level values (threshold, algorithm, workers) are exported for
the *next* Update run, which the caption says honestly. Simple users never
need Advanced: it holds diagnostics only.
"""

from __future__ import annotations

from pathlib import Path

from PySide6 import QtCore, QtWidgets

from config.settings import get_settings
from config.user_config import get_config
from viewer.components import elevate
from viewer.gpuinfo import detect_gpu

_PAGE_CHOICES = [("Dashboard", "dashboard"), ("Photos", "photos"),
                 ("Timeline", "timeline"), ("People", "people"), ("Search", "search")]
_ALGO_CHOICES = [("Automatic", None), ("DBSCAN", "dbscan"), ("HDBSCAN", "hdbscan")]


class SettingsPage(QtWidgets.QScrollArea):
    """Scrollable, sectioned preferences editor."""

    def __init__(self) -> None:
        super().__init__()
        self.setWidgetResizable(True)
        self.setFrameShape(QtWidgets.QFrame.Shape.NoFrame)
        self._cfg = get_config()

        body = QtWidgets.QWidget()
        self._v = QtWidgets.QVBoxLayout(body)
        self._v.setContentsMargins(24, 20, 24, 24)
        self._v.setSpacing(12)

        title = QtWidgets.QLabel("Settings")
        title.setObjectName("H1")
        self._v.addWidget(title)
        sub = QtWidgets.QLabel("Preferences are saved instantly and survive restarts.")
        sub.setObjectName("Muted")
        self._v.addWidget(sub)

        self._build_general()
        self._build_appearance()
        self._build_ai()
        self._build_performance()
        self._build_storage()
        self._build_backup()
        self._build_database()
        self._build_advanced()

        reset = QtWidgets.QPushButton("Reset all settings to defaults")
        reset.clicked.connect(self._on_reset)
        self._v.addWidget(reset, 0, QtCore.Qt.AlignmentFlag.AlignLeft)
        self._v.addStretch(1)
        self.setWidget(body)

    # -- section scaffolding ---------------------------------------------------

    def _card(self, heading: str) -> QtWidgets.QFormLayout:
        card = QtWidgets.QFrame()
        card.setObjectName("Card")
        v = QtWidgets.QVBoxLayout(card)
        v.setContentsMargins(18, 14, 18, 14)
        v.setSpacing(8)
        h = QtWidgets.QLabel(heading)
        h.setObjectName("H2")
        v.addWidget(h)
        form = QtWidgets.QFormLayout()
        form.setLabelAlignment(QtCore.Qt.AlignmentFlag.AlignLeft)
        form.setHorizontalSpacing(24)
        v.addLayout(form)
        elevate(card, blur=16, y=3, alpha=55)
        self._v.addWidget(card)
        return form

    @staticmethod
    def _note(text: str) -> QtWidgets.QLabel:
        note = QtWidgets.QLabel(text)
        note.setObjectName("Muted")
        note.setWordWrap(True)
        return note

    # -- sections --------------------------------------------------------------

    def _build_general(self) -> None:
        form = self._card("General")
        self._startup = QtWidgets.QComboBox()
        for label, key in _PAGE_CHOICES:
            self._startup.addItem(label, key)
        self._startup.setCurrentIndex(
            max(0, [k for _, k in _PAGE_CHOICES].index(self._cfg.get("general", "startup_page"))))
        self._startup.currentIndexChanged.connect(
            lambda i: self._cfg.set("general", "startup_page", self._startup.itemData(i)))
        form.addRow("Start on", self._startup)

        self._confirm = QtWidgets.QCheckBox("Ask before deleting people or groups")
        self._confirm.setChecked(bool(self._cfg.get("general", "confirm_deletes")))
        self._confirm.toggled.connect(lambda v: self._cfg.set("general", "confirm_deletes", v))
        form.addRow("Confirmations", self._confirm)

    def _build_appearance(self) -> None:
        form = self._card("Appearance")
        theme_box = QtWidgets.QComboBox()
        theme_box.addItem("Dark")
        theme_box.setEnabled(False)
        theme_box.setToolTip("Light theme is planned; PhotoSphere 2.0 ships dark.")
        form.addRow("Theme", theme_box)

        self._motion = QtWidgets.QCheckBox("Reduce motion (skip animations)")
        self._motion.setChecked(bool(self._cfg.get("appearance", "reduced_motion")))
        self._motion.toggled.connect(lambda v: self._cfg.set("appearance", "reduced_motion", v))
        form.addRow("Motion", self._motion)
        form.addRow("", self._note("Applies immediately to new transitions."))

    def _build_ai(self) -> None:
        form = self._card("AI & Recognition")
        s = get_settings()

        self._threshold = QtWidgets.QDoubleSpinBox()
        self._threshold.setRange(0.30, 0.95)
        self._threshold.setSingleStep(0.05)
        self._threshold.setDecimals(2)
        current = self._cfg.get("ai", "face_match_threshold")
        self._threshold.setValue(float(current if current is not None else s.face_match_threshold))
        self._threshold.valueChanged.connect(
            lambda v: self._cfg.set("ai", "face_match_threshold", round(v, 2)))
        form.addRow("Face match strictness", self._threshold)
        form.addRow("", self._note(
            "Higher = fewer wrong matches, more 'is this…?' questions. "
            "Takes effect on the next Update."))

        self._algo = QtWidgets.QComboBox()
        for label, key in _ALGO_CHOICES:
            self._algo.addItem(label, key)
        cur_algo = self._cfg.get("ai", "cluster_algorithm")
        self._algo.setCurrentIndex(max(0, [k for _, k in _ALGO_CHOICES].index(cur_algo)))
        self._algo.currentIndexChanged.connect(
            lambda i: self._cfg.set("ai", "cluster_algorithm", self._algo.itemData(i)))
        form.addRow("Grouping method", self._algo)

        self._suggest = QtWidgets.QCheckBox("Offer suggestions when unsure")
        self._suggest.setChecked(bool(self._cfg.get("ai", "auto_suggestions")))
        self._suggest.toggled.connect(lambda v: self._cfg.set("ai", "auto_suggestions", v))
        form.addRow("Review queue", self._suggest)

    def _build_performance(self) -> None:
        form = self._card("Performance")
        gpu = detect_gpu()
        form.addRow("Compute device", QtWidgets.QLabel(
            gpu.device_name if gpu.available else "CPU (no CUDA GPU detected)"))

        self._workers = QtWidgets.QSpinBox()
        self._workers.setRange(0, 32)
        self._workers.setSpecialValueText("Automatic")
        self._workers.setValue(int(self._cfg.get("performance", "worker_threads") or 0))
        self._workers.valueChanged.connect(
            lambda v: self._cfg.set("performance", "worker_threads", v or None))
        form.addRow("Worker threads", self._workers)
        form.addRow("", self._note("Automatic matches your CPU. Takes effect on the next Update."))

    def _build_storage(self) -> None:
        form = self._card("Storage")
        s = get_settings()
        for label, path in (("Thumbnails", s.thumbnails_dir),
                            ("Face crops", s.face_crops_dir),
                            ("Cache", s.cache_dir)):
            row = QtWidgets.QLabel(str(path))
            row.setObjectName("Muted")
            row.setTextInteractionFlags(QtCore.Qt.TextInteractionFlag.TextSelectableByMouse)
            form.addRow(label, row)

    def _build_backup(self) -> None:
        form = self._card("Backup")
        form.addRow("", self._note(
            "Saves everything you've taught PhotoSphere — names, corrections, "
            "favorites — to one file. Your photos are never touched."))
        row = QtWidgets.QHBoxLayout()
        back = QtWidgets.QPushButton("Back up knowledge…")
        back.clicked.connect(self._on_backup)
        restore = QtWidgets.QPushButton("Restore from backup…")
        restore.clicked.connect(self._on_restore)
        row.addWidget(back)
        row.addWidget(restore)
        row.addStretch(1)
        form.addRow("Knowledge", row)
        self._backup_note = QtWidgets.QLabel("")
        self._backup_note.setObjectName("Muted")
        self._backup_note.setWordWrap(True)
        form.addRow("", self._backup_note)

    def _on_backup(self) -> None:
        from backup.knowledge import save_backup
        from database import db
        path, _ = QtWidgets.QFileDialog.getSaveFileName(
            self, "Back up knowledge", "photosphere-knowledge.json", "Backup (*.json)")
        if not path:
            return
        try:
            with db.connection() as conn, conn.cursor() as cur:
                data = save_backup(cur, Path(path))
            self._backup_note.setText(
                f"Backed up {len(data['people'])} people, "
                f"{len(data['favorites'])} favorites, "
                f"{len(data['feedback'])} corrections.")
        except Exception as exc:  # noqa: BLE001
            self._backup_note.setText(f"Backup failed: {exc}")

    def _on_restore(self) -> None:
        from backup.knowledge import load_backup, restore_knowledge
        from database import db
        path, _ = QtWidgets.QFileDialog.getOpenFileName(
            self, "Restore knowledge", "", "Backup (*.json)")
        if not path:
            return
        try:
            data = load_backup(Path(path))  # validated before anything is written
            with db.connection() as conn, conn.cursor() as cur:
                report = restore_knowledge(cur, data)
            self._backup_note.setText(
                f"Restored: {report['faces_assigned']} faces across people, "
                f"{report['favorites']} favorites, {report['feedback']} corrections "
                f"({report['faces_skipped'] + report['favorites_skipped'] + report['feedback_skipped']} "
                "entries had no matching photo and were skipped).")
        except Exception as exc:  # noqa: BLE001
            self._backup_note.setText(f"Restore failed: {exc}")

    def _build_database(self) -> None:
        form = self._card("Database")
        self._db_status = QtWidgets.QLabel("—")
        self._db_status.setObjectName("Muted")
        form.addRow("PostgreSQL", self._db_status)
        self._vector_status = QtWidgets.QLabel("—")
        self._vector_status.setObjectName("Muted")
        form.addRow("Vector search", self._vector_status)

    def _build_advanced(self) -> None:
        form = self._card("Advanced")
        form.addRow("", self._note("Everyday use never needs these."))
        optimize = QtWidgets.QPushButton("Rebuild search indexes")
        optimize.setToolTip("Retrains the vector indexes and refreshes statistics "
                            "(also runs automatically after every import).")
        optimize.clicked.connect(self._on_optimize)
        form.addRow("Indexes", optimize)

        reset = QtWidgets.QPushButton("Reset library (start over)…")
        reset.setToolTip("Remove all indexed photos, people and learning so you "
                        "can train from zero. Your original photo files are not "
                        "touched.")
        reset.clicked.connect(self._on_reset_library)
        form.addRow("Start over", reset)

        self._advanced_note = QtWidgets.QLabel("")
        self._advanced_note.setObjectName("Muted")
        self._advanced_note.setWordWrap(True)
        form.addRow("", self._advanced_note)

    # -- live data -------------------------------------------------------------

    def refresh(self) -> None:
        from database import db
        try:
            with db.connection() as conn, conn.cursor() as cur:
                cur.execute("SHOW server_version")
                version = cur.fetchone()[0]
                cur.execute("SELECT count(*) FROM pg_extension WHERE extname = 'vector'")
                has_vector = bool(cur.fetchone()[0])
            self._db_status.setText(f"Connected · PostgreSQL {version}")
            self._vector_status.setText(
                "Ready (pgvector installed)" if has_vector else "pgvector missing")
        except Exception as exc:  # noqa: BLE001 - page must render with DB down
            self._db_status.setText(f"Not reachable — {exc.__class__.__name__}")
            self._vector_status.setText("—")

    # -- actions ---------------------------------------------------------------

    def _on_optimize(self) -> None:
        from database import db
        try:
            with db.connection() as conn, conn.cursor() as cur:
                db.optimize_after_import(cur)
            self._advanced_note.setText("Indexes rebuilt.")
        except Exception as exc:  # noqa: BLE001
            self._advanced_note.setText(f"Could not rebuild: {exc}")

    def _on_reset_library(self) -> None:
        """Wipe all indexed data + caches after a typed confirmation."""
        from database import db
        with db.connection() as conn, conn.cursor() as cur:
            cur.execute("SELECT count(*) FROM photos")
            n = int(cur.fetchone()[0])

        text, ok = QtWidgets.QInputDialog.getText(
            self, "Reset library",
            f"This permanently removes all {n:,} indexed photos and every person, "
            "name, correction, album and search index.\n\nYour original photo "
            "files are NOT affected — you can re-import them.\n\nType 'reset' to "
            "confirm:")
        if not ok or text.strip().lower() != "reset":
            self._advanced_note.setText("Reset cancelled.")
            return
        try:
            from reset_library import reset_library
            report = reset_library(clear_caches=True)
            self._advanced_note.setText(
                f"Library reset — removed {report.photos_before:,} photos and "
                "cleared caches. Import your photos to train from zero.")
        except Exception as exc:  # noqa: BLE001
            self._advanced_note.setText(f"Reset failed: {exc}")

    def _on_reset(self) -> None:
        if QtWidgets.QMessageBox.question(
            self, "Reset settings",
            "Restore every setting to its default? Your photos and people are unaffected.",
        ) != QtWidgets.QMessageBox.StandardButton.Yes:
            return
        self._cfg.reset()
        # Re-read every control from the store.
        self._startup.setCurrentIndex(0)
        self._confirm.setChecked(True)
        self._motion.setChecked(False)
        self._threshold.setValue(float(get_settings().face_match_threshold))
        self._algo.setCurrentIndex(0)
        self._suggest.setChecked(True)
        self._workers.setValue(0)
