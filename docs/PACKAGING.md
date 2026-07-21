# Packaging PhotoSphere AI for Windows

This documents how the Windows installer is built, what it contains, and the
honest limitations of the current v1.

## What the installer is

A PyInstaller one-directory build of the desktop app, wrapped in an Inno Setup
installer. It installs to `%ProgramFiles%\PhotoSphere AI` (or per-user), adds
Start-Menu / optional desktop shortcuts, and registers an uninstaller.

Generated data (thumbnails, face crops, logs, caches, and the
`~/.photosphere/config.json` preferences) is written to a **per-user**
location — `%LOCALAPPDATA%\PhotoSphere` — never under the read-only install
directory. This is handled by `utils.paths`, which switches from the
project-relative layout (used in development and tests) to the OS per-user
layout when running frozen.

## Prerequisites the installer does NOT bundle

1. **PostgreSQL 16+ with the `pgvector` extension.** PhotoSphere stores its
   library in PostgreSQL. A consumer-grade "double-click and go" experience
   would bundle an embedded/portable PostgreSQL; that is deliberately **out of
   scope for v1** and tracked as future work. For now PostgreSQL is a
   prerequisite — install it, create a database, and point PhotoSphere at it
   with the `PHOTOSPHERE_DB_*` environment variables (see `config/settings.py`).

2. **Local AI models (optional).** The base ("lite") installer excludes the
   heavy local-AI stack — PyTorch, InsightFace, ONNX Runtime, hdbscan,
   RapidOCR — which together add multiple GB. The app **degrades gracefully**
   without them: face recognition, semantic search and OCR show a friendly
   "not installed" state, while browsing, timeline, albums, favorites and
   duplicate detection work fully. Users who want the AI features install the
   extras into the same Python environment (see `requirements.txt`).

## Building locally (on Windows)

```powershell
python -m venv .venv; .\.venv\Scripts\Activate.ps1
pip install -r requirements-build.txt
pyinstaller packaging\photosphere.spec              # -> dist\PhotoSphere\
iscc "/DAppVersion=2.0.0" packaging\photosphere.iss  # -> packaging\Output\
```

`iscc` is the Inno Setup compiler (`choco install innosetup`).

## Building in CI (recommended)

`.github/workflows/build-windows.yml` builds the installer on a
`windows-latest` runner — the only place a Windows PyInstaller build can be
produced and verified. It runs on demand (**Actions → Build Windows installer
→ Run workflow**) and on version tags (`v*`), uploading the installer as a
build artifact and attaching it to the GitHub release for tagged builds. The
version comes from `utils/version.py` so it is stated in exactly one place.

The workflow smoke-tests that the app imports (offscreen Qt) before building,
so a broken dependency set fails the build rather than shipping a dead `.exe`.

## Cross-building note

A Windows executable cannot be produced from Linux/macOS — PyInstaller freezes
against the host OS's Python and native libraries. Build on Windows (locally or
via the CI job above).

## Future work

- Bundle a portable PostgreSQL + `pgvector` so no separate install is needed.
- Optional "full" installer variant that includes the AI extras.
- Code signing (removes the SmartScreen warning) and an app icon
  (`packaging/photosphere.ico`, referenced but not yet added).
