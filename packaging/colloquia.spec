import os
import sys

from PyInstaller.utils.hooks import collect_data_files, collect_dynamic_libs

ROOT = os.path.dirname(SPECPATH)
VERSION = os.environ.get("COLLOQUIA_VERSION", "1.0.0")
ICON = os.path.join(SPECPATH, "colloquia.png")
ICO = os.path.join(SPECPATH, "colloquia.ico")

binaries = collect_dynamic_libs("ctranslate2") + collect_dynamic_libs("sherpa_onnx")

a = Analysis(
    [os.path.join(ROOT, "colloquia.py")],
    pathex=[ROOT],
    binaries=binaries,
    datas=collect_data_files("faster_whisper") + [(os.path.join(ROOT, "ui.html"), "."), (ICON, "packaging"), (ICO, "packaging")],
    runtime_hooks=[os.path.join(SPECPATH, "pyi_rth_portaudio.py")] if sys.platform.startswith("linux") else [],
    excludes=["tkinter", "matplotlib", "pandas", "scipy", "torch", "IPython", "pytest"],
)
pyz = PYZ(a.pure)


def exe(name, console):
    return EXE(
        pyz,
        a.scripts,
        [("X utf8", None, "OPTION")],
        exclude_binaries=True,
        name=name,
        console=console,
        icon=ICO if sys.platform == "win32" else ICON,
        upx=False,
        argv_emulation=False,
    )


exes = [exe("Colloquia", False)]
if sys.platform == "win32":
    exes.append(exe("colloquia-cli", True))

coll = COLLECT(*exes, a.binaries, a.datas, name="Colloquia", upx=False)

if sys.platform == "darwin":
    app = BUNDLE(
        coll,
        name="Colloquia.app",
        icon=ICON,
        bundle_identifier="io.github.arocafull00.colloquia",
        version=VERSION,
        info_plist={
            "CFBundleDisplayName": "Colloquia",
            "CFBundleShortVersionString": VERSION,
            "NSMicrophoneUsageDescription": "Colloquia usa el micrófono para grabar las sesiones.",
            "NSHighResolutionCapable": True,
            "LSMinimumSystemVersion": "11.0",
        },
    )
