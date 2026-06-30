# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller spec for Transcriber.app.

Produces a genuine .app bundle whose Contents/MacOS/Transcriber is a real Mach-O
executable with Python embedded — so macOS TCC attributes microphone (and
BlackHole) access to Transcriber.app rather than to a shared system interpreter.

Build:  pyinstaller --noconfirm Transcriber.spec
"""
from PyInstaller.utils.hooks import collect_all, collect_submodules

datas = [("static", "static")]
binaries = []
hiddenimports = []

# Heavy native-dependency packages need everything collected (data files,
# dylibs, and submodules) or they fail to import at runtime inside the bundle.
for pkg in ("faster_whisper", "ctranslate2", "av", "tokenizers",
            "onnxruntime", "sounddevice", "_sounddevice_data", "webview"):
    try:
        d, b, h = collect_all(pkg)
        datas += d
        binaries += b
        hiddenimports += h
    except Exception:
        pass

# pywebview's macOS backend is imported dynamically.
hiddenimports += collect_submodules("webview.platforms")
hiddenimports += ["uvicorn", "uvicorn.logging", "uvicorn.loops.auto",
                  "uvicorn.protocols.http.auto", "uvicorn.protocols.websockets.auto",
                  "uvicorn.lifespan.on", "websockets", "anyio"]


a = Analysis(
    ["main.py"],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    runtime_hooks=[],
    excludes=["tkinter", "matplotlib", "PIL", "pytest"],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="Transcriber",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,  # GUI app — no terminal window
    target_arch=None,
    codesign_identity=None,  # signed explicitly in make_app.sh with entitlements
    entitlements_file=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="Transcriber",
)

app = BUNDLE(
    coll,
    name="Transcriber.app",
    icon="icon/AppIcon.icns" if __import__("os").path.exists("icon/AppIcon.icns") else None,
    bundle_identifier="com.lucashendrich.transcriber",
    info_plist={
        "CFBundleName": "Transcriber",
        "CFBundleDisplayName": "Transcriber",
        "CFBundleShortVersionString": "1.0",
        "CFBundleVersion": "1.0",
        "LSMinimumSystemVersion": "12.0",
        "NSHighResolutionCapable": True,
        "NSMicrophoneUsageDescription":
            "Transcriber captures audio from your microphone and meeting audio "
            "to produce a local transcript. No audio leaves your machine.",
        "NSHumanReadableCopyright": "Lucas Hendrich",
    },
)
