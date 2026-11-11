import ctypes
import os
import shutil
import subprocess
import sys

from config import MAC, WIN

ES_CONTINUOUS = 0x80000000
ES_SYSTEM_REQUIRED = 0x00000001


def prepare_webview():
    if not sys.platform.startswith("linux"):
        return
    if not getattr(sys, "frozen", False):
        # The native installer uses GTK/WebKit and PyGObject from the distro.
        os.environ.setdefault("PYWEBVIEW_GUI", "gtk")
        return
    # Use the bundled Qt backend and avoid mixing bundled Mesa/GLib with
    # graphics drivers and GVfs modules from a newer Linux distribution.
    os.environ.setdefault("PYWEBVIEW_GUI", "qt")
    os.environ.setdefault("QT_XCB_GL_INTEGRATION", "none")
    flags = os.environ.get("QTWEBENGINE_CHROMIUM_FLAGS", "")
    if "--disable-gpu" not in flags.split():
        os.environ["QTWEBENGINE_CHROMIUM_FLAGS"] = (flags + " --disable-gpu").strip()
    os.environ.setdefault("GIO_USE_VFS", "local")


class KeepAwake:
    def __init__(self):
        self.proc = None

    def start(self):
        if self.proc:
            return
        if WIN:
            ctypes.windll.kernel32.SetThreadExecutionState(ES_CONTINUOUS | ES_SYSTEM_REQUIRED)
        elif MAC:
            self.proc = subprocess.Popen(["caffeinate", "-i", "-w", str(os.getpid())])
        elif shutil.which("systemd-inhibit"):
            self.proc = subprocess.Popen(
                ["systemd-inhibit", "--what=sleep:idle", "--who=Colloquia", "--why=Grabando sesión", "sleep", "infinity"]
            )

    def stop(self):
        if WIN:
            ctypes.windll.kernel32.SetThreadExecutionState(ES_CONTINUOUS)
        if self.proc:
            self.proc.terminate()
            self.proc = None


def total_ram():
    if WIN:

        class MemoryStatus(ctypes.Structure):
            _fields_ = [("length", ctypes.c_ulong), ("load", ctypes.c_ulong), ("total", ctypes.c_ulonglong)] + [
                (f"f{i}", ctypes.c_ulonglong) for i in range(6)
            ]

        m = MemoryStatus(length=ctypes.sizeof(MemoryStatus))
        ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(m))
        return m.total
    try:
        return os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES")
    except (ValueError, OSError, AttributeError):
        return 0


def open_folder(path):
    if WIN:
        os.startfile(path)
    elif MAC:
        subprocess.Popen(["open", path])
    else:
        subprocess.Popen(["xdg-open", path])
