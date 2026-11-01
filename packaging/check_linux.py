"""Check the native Linux installation without recording or downloading models."""

import argparse
import importlib
import os
from pathlib import Path
import sys
import threading
import time
import traceback

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--gui", action="store_true", help="Comprobar también GTK/WebKit en una sesión gráfica")
    args = parser.parse_args()
    os.environ["PYWEBVIEW_GUI"] = "gtk"

    import gi

    gi.require_version("Gtk", "3.0")
    gi.require_version("WebKit2", "4.1")
    from gi.repository import Gtk, WebKit2

    # Also load transcription extensions, which the UI otherwise imports lazily.
    for module in ("av", "faster_whisper", "sherpa_onnx", "lameenc", "sounddevice", "ui"):
        importlib.import_module(module)

    print(f"Dependencias correctas: Python {sys.version.split()[0]}, GTK {Gtk.MAJOR_VERSION}, WebKit {WebKit2.get_major_version()}", flush=True)
    if not args.gui:
        return 0

    import webview
    import ui

    passed = False
    # Load the real home screen and JS API, without opening the mic or models.
    api = ui.Api()
    html = (Path(ui.HERE) / "ui.html").read_text(encoding="utf-8")
    window = webview.create_window("Colloquia · comprobación", html=html, js_api=api, hidden=True)
    api._window = window

    def check():
        nonlocal passed
        try:
            deadline = time.monotonic() + 30
            while not window.evaluate_js("typeof colloquia !== 'undefined' && colloquia.ready"):
                if time.monotonic() >= deadline:
                    raise RuntimeError("La pantalla de inicio no ha completado su comunicación con Python")
                time.sleep(0.1)
            passed = True
            print("Pantalla de inicio GTK/WebKit y comunicación JavaScript/Python correctas.", flush=True)
        except Exception:
            traceback.print_exc()
        finally:
            window.destroy()

    def timeout():
        print("No se ha podido iniciar la interfaz en 45 segundos.", file=sys.stderr, flush=True)
        os._exit(1)

    watchdog = threading.Timer(45, timeout)
    watchdog.daemon = True
    watchdog.start()
    window.events.loaded += check
    try:
        webview.start(gui="gtk")
    finally:
        watchdog.cancel()
    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(main())
