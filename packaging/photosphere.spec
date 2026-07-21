# PyInstaller spec for PhotoSphere AI (run from the repo root):
#
#   pyinstaller packaging/photosphere.spec
#
# Produces dist/PhotoSphere/PhotoSphere.exe (one-dir build — faster startup and
# smaller memory than one-file, and friendlier for the installer to lay down).
# The SQL schema is a bundled data file so the frozen app can create its tables;
# utils.paths.resource_path() locates it inside the bundle.

from pathlib import Path

from PyInstaller.utils.hooks import collect_submodules

ROOT = Path(SPECPATH).resolve().parent  # packaging/ -> repo root

datas = [
    (str(ROOT / "database" / "schema.sql"), "database"),
]

# psycopg2 occasionally needs its C-extension submodules named explicitly.
hiddenimports = collect_submodules("psycopg2")

# Keep the "lite" installer small: never pull the heavy optional AI stack into
# the bundle even if it happens to be installed in the build environment.
excludes = [
    "torch", "torchvision", "open_clip", "insightface", "onnxruntime",
    "onnxruntime_gpu", "hdbscan", "rapidocr_onnxruntime", "matplotlib",
    "tkinter", "pytest",
]

a = Analysis(
    [str(ROOT / "main.py")],
    pathex=[str(ROOT)],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    runtime_hooks=[],
    excludes=excludes,
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="PhotoSphere",
    console=False,          # windowed GUI app — no console window
    icon=None,              # add packaging/photosphere.ico to brand the exe
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    name="PhotoSphere",
)
