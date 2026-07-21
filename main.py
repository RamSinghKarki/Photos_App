"""PhotoSphere AI — desktop launcher and PyInstaller entry point.

Kept deliberately tiny: all startup logic lives in :func:`viewer.app.run`.
Running ``python main.py`` from source and launching the packaged executable
both funnel through here.
"""

from __future__ import annotations

from viewer.app import run

if __name__ == "__main__":
    raise SystemExit(run())
