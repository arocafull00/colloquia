import ctypes
import os
import shutil
import subprocess

from config import MAC, WIN

ES_CONTINUOUS = 0x80000000
ES_SYSTEM_REQUIRED = 0x00000001


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


def open_folder(path):
    if WIN:
        os.startfile(path)
    elif MAC:
        subprocess.Popen(["open", path])
    else:
        subprocess.Popen(["xdg-open", path])
