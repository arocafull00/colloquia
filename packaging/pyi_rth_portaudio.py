import ctypes.util
import glob
import os
import sys

_bundled = glob.glob(os.path.join(sys._MEIPASS, "libportaudio.so*"))
if _bundled:
    _find_library = ctypes.util.find_library
    ctypes.util.find_library = lambda name: _find_library(name) or (_bundled[0] if name == "portaudio" else None)
