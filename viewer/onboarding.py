"""First-run welcome — the guided onboarding overlay (PDD rev 2).

Shown once, on the very first launch, before the library exists. It states the
product's promise in one breath (private, on-device) and offers a single clear
first action — pick a folder to import — with an unobtrusive way to skip. It is
a modal :class:`QDialog`, centred over the window; the caller decides what to do
with the outcome (import vs. dismiss) and records that onboarding was seen.
"""

from __future__ import annotations

from PySide6 import QtCore, QtWidgets

from viewer import theme


class WelcomeDialog(QtWidgets.QDialog):
    """A one-screen welcome. :meth:`exec` returns Accepted if 'Choose a folder'."""

    def __init__(self, parent: QtWidgets.QWidget | None = None) -> None:
        super().__init__(parent)
        self.setModal(True)
        self.setObjectName("Welcome")
        self.setFixedWidth(460)

        v = QtWidgets.QVBoxLayout(self)
        v.setContentsMargins(36, 32, 36, 28)
        v.setSpacing(10)
        v.setAlignment(QtCore.Qt.AlignmentFlag.AlignHCenter)

        lens = QtWidgets.QLabel()
        lens.setObjectName("WelcomeLens")
        lens.setFixedSize(48, 48)
        v.addWidget(lens, 0, QtCore.Qt.AlignmentFlag.AlignHCenter)

        title = QtWidgets.QLabel("Welcome to PhotoSphere")
        title.setObjectName("H1")
        title.setAlignment(QtCore.Qt.AlignmentFlag.AlignHCenter)
        v.addWidget(title)

        body = QtWidgets.QLabel(
            "Your photos, understood — privately. Everything happens on this "
            "computer. Nothing is ever uploaded."
        )
        body.setObjectName("Muted")
        body.setWordWrap(True)
        body.setAlignment(QtCore.Qt.AlignmentFlag.AlignHCenter)
        v.addWidget(body)
        v.addSpacing(10)

        buttons = QtWidgets.QHBoxLayout()
        buttons.addStretch(1)
        choose = QtWidgets.QPushButton("Choose a folder")
        choose.setObjectName("Primary")
        choose.clicked.connect(self.accept)
        skip = QtWidgets.QPushButton("Skip for now")
        skip.clicked.connect(self.reject)
        buttons.addWidget(choose)
        buttons.addWidget(skip)
        buttons.addStretch(1)
        v.addLayout(buttons)

    @staticmethod
    def maybe_run(parent: QtWidgets.QWidget, state, on_import) -> None:
        """Show onboarding once. On first run, mark it seen; import if chosen.

        ``state`` provides ``onboarded()`` / ``mark_onboarded()``; ``on_import``
        is invoked when the user picks 'Choose a folder'.
        """
        if state.onboarded():
            return
        state.mark_onboarded()
        dialog = WelcomeDialog(parent)
        chose_import = dialog.exec() == QtWidgets.QDialog.DialogCode.Accepted
        if chose_import:
            on_import()


def welcome_qss() -> str:
    """QSS for the welcome dialog (appended to the global stylesheet)."""
    return f"""
    QDialog#Welcome {{
        background-color: {theme.SURFACE_ALT};
        border: 1px solid {theme.BORDER};
        border-radius: {theme.RADIUS_LG}px;
    }}
    QDialog#Welcome QLabel {{ background: transparent; }}
    QLabel#WelcomeLens {{
        border: 4px solid {theme.PRIMARY}; border-radius: 24px;
        background-color: {theme.ACCENT_SOFT};
    }}
    """
