import json
import os
import shutil
import subprocess
import sys
import threading
import time
import traceback

import webview

import models
import pipeline
from config import APP, LANGUAGES, MAC, MODELS, PAUSES, WIN, load_config, save_config
from platform_utils import KeepAwake, open_folder
from recorder import PCM, Recorder, input_devices, read_meta

HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_MIC = "Predeterminado del sistema"
APPEARANCE = {"Según el sistema": "system", "Claro": "light", "Oscuro": "dark"}
DEFAULT_ROLES = ("Psicólogo", "Paciente")
SILENCE_LEVEL = 0.003
SILENCE_SECONDS = 30


def dark_mode():
    try:
        if MAC:
            r = subprocess.run(["defaults", "read", "-g", "AppleInterfaceStyle"], capture_output=True, text=True)
            return "Dark" in r.stdout
        if WIN:
            import winreg

            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize") as k:
                return winreg.QueryValueEx(k, "AppsUseLightTheme")[0] == 0
    except Exception:
        pass
    return False


def pairs(mapping):
    return [[label, value] for label, value in mapping.items()]


class Api:
    def __init__(self):
        self._cfg = load_config()
        self._window = None
        self._ready = False
        self._lock = threading.RLock()
        self._recorder = Recorder()
        self._awake = KeepAwake()
        self._screen = "home"
        self._session_dir = None
        self._meta = None
        self._error = ""
        self._banner = ""
        self._alerts = []
        self._silent_since = None
        self._processing_started = 0
        self._quitting = False

    def init(self):
        self._ready = True
        alerts, self._alerts = self._alerts, []
        return {
            "cfg": self._cfg,
            "options": {
                "models": pairs(MODELS),
                "languages": pairs(LANGUAGES),
                "pauses": pairs(PAUSES),
                "appearance": pairs(APPEARANCE),
                "mics": input_devices(),
                "defaultMic": DEFAULT_MIC,
            },
            "screen": self._screen_payload(),
            "banner": self._banner,
            "sessions": self._sessions(),
            "alerts": alerts,
        }

    def choose_folder(self):
        start = self._cfg["folder"] if os.path.isdir(self._cfg["folder"]) else os.path.expanduser("~")
        picked = self._window.create_file_dialog(webview.FileDialog.FOLDER, directory=start)
        if not picked:
            return None
        self._cfg["folder"] = os.path.normpath(picked[0] if isinstance(picked, (list, tuple)) else picked)
        save_config(self._cfg)
        self._send({"type": "sessions", "sessions": self._sessions()})
        return self._cfg["folder"]

    def apply(self, cfg):
        with self._lock:
            old = self._cfg
            cfg = {**old, **cfg}
            cfg["roles"] = [(r or "").strip() or d for r, d in zip(cfg["roles"], DEFAULT_ROLES)]
            self._cfg = cfg
            save_config(cfg)
            if cfg["device"] != old["device"] and self._screen != "recording":
                self._open_mic()
            if self._meta and self._screen == "done" and (cfg["roles"] != old["roles"] or cfg["pause_min"] != old["pause_min"] or cfg["mark_doubtful"] != old["mark_doubtful"]):
                pipeline.write_txt(self._session_dir, cfg)
                self._send({"type": "screen", "screen": self._screen_payload()})
            if cfg["model"] != old["model"]:
                self._prepare_models()
            return cfg

    def start(self, name):
        with self._lock:
            if self._screen not in ("home", "done", "error"):
                return
            if self._recorder.stream is None:
                self._open_mic()
                if self._recorder.stream is None:
                    return
            try:
                self._session_dir = self._recorder.start(self._cfg["folder"], (name or "").strip())
            except OSError as e:
                self._alert(f"No se puede escribir en la carpeta de destino:\n{e}")
                return
            save_config(self._cfg)
            self._awake.start()
            self._silent_since = None
            self._show("recording")

    def pause(self):
        self._recorder.paused = not self._recorder.paused
        return self._recorder.paused

    def stop(self):
        with self._lock:
            if self._screen != "recording":
                return
            session_dir = self._recorder.stop()
            if self._recorder.seconds < 1:
                self._awake.stop()
                shutil.rmtree(session_dir, ignore_errors=True)
                self._alert("La grabación está vacía; no hay nada que procesar.")
                self._show("home")
                return
            self._process(session_dir)

    def recover(self, path=None):
        with self._lock:
            if self._screen not in ("home", "done", "error"):
                return
            pending = [s["path"] for s in self._sessions() if s["pending"]]
            if path in pending or (path is None and pending):
                self._process(path or pending[0])

    def retry(self):
        with self._lock:
            if self._screen == "error" and self._session_dir:
                self._process(self._session_dir)

    def swap(self):
        with self._lock:
            if self._screen == "done":
                self._meta = pipeline.swap_roles(self._session_dir, self._cfg)
                self._send({"type": "screen", "screen": self._screen_payload()})

    def reset(self):
        with self._lock:
            if self._screen in ("done", "error"):
                self._show("home")

    def transcript(self, path=None):
        path = path or self._session_dir
        try:
            meta = read_meta(path)
        except (OSError, ValueError, TypeError):
            return None
        if meta.get("state") != "done":
            return None
        try:
            with open(os.path.join(path, pipeline.TXT), encoding="utf-8") as f:
                text = f.read()
        except OSError:
            text = ""
        return {
            "path": path,
            "folder": os.path.basename(path),
            "name": meta.get("name") or "",
            "started": meta.get("started"),
            "duration": meta.get("duration") or 0,
            "roles": self._cfg["roles"],
            "entries": pipeline.entries(meta, self._cfg),
            "text": text,
        }

    def open(self, path=None):
        target = path or (self._session_dir if self._screen == "done" else self._cfg["folder"])
        os.makedirs(target, exist_ok=True)
        open_folder(target)

    def quit(self):
        self._shutdown()
        self._window.destroy()

    def _send(self, msg):
        if self._ready and self._window:
            try:
                self._window.evaluate_js(f"colloquia.receive({json.dumps(msg, ensure_ascii=False)})")
            except Exception:
                traceback.print_exc()

    def _alert(self, text):
        if self._ready:
            self._send({"type": "alert", "text": text})
        else:
            self._alerts.append(text)

    def _screen_payload(self):
        p = {"name": self._screen}
        if self._session_dir:
            p["session"] = os.path.basename(self._session_dir)
        if self._screen == "done" and self._meta:
            found = pipeline.samples(self._meta)
            p["duration"] = self._meta["duration"]
            p["turns"] = len(self._meta["turns"])
            p["voices"] = [{"role": self._cfg["roles"][i], "quote": found.get(i)} for i in range(2)]
        elif self._screen == "error":
            p["message"] = self._error
        return p

    def _show(self, screen):
        self._screen = screen
        self._send({"type": "screen", "screen": self._screen_payload()})
        if screen in ("home", "done", "error"):
            self._send({"type": "sessions", "sessions": self._sessions()})

    def _sessions(self):
        folder = self._cfg["folder"]
        found = []
        if not os.path.isdir(folder):
            return found
        active = self._session_dir if self._screen in ("recording", "processing") else None
        for entry in os.listdir(folder):
            d = os.path.join(folder, entry)
            try:
                meta = read_meta(d)
            except (OSError, ValueError):
                continue
            state = meta.get("state")
            found.append(
                {
                    "path": d,
                    "folder": entry,
                    "name": meta.get("name") or "",
                    "started": meta.get("started"),
                    "duration": meta.get("duration") or 0,
                    "turns": len(meta.get("turns") or []),
                    "state": state,
                    "active": d == active,
                    "pending": d != active and state != "done" and os.path.exists(os.path.join(d, PCM)),
                }
            )
        return found

    def _open_mic(self):
        try:
            self._recorder.open(self._cfg["device"])
        except Exception as e:
            traceback.print_exc()
            self._alert(f"No se pudo abrir el micrófono:\n{e}")

    def _set_banner(self, text):
        self._banner = text
        self._send({"type": "banner", "text": text})

    def _prepare_models(self):
        model = self._cfg["model"]

        def status(text, p):
            self._set_banner(text + (f" {p * 100:.0f}%" if p is not None else ""))

        def work():
            if models.missing(model):
                status("Preparando modelos (solo la primera vez)…", None)
                try:
                    models.ensure(model, status)
                    self._set_banner("")
                except Exception as e:
                    traceback.print_exc()
                    self._set_banner(f"No se pudieron descargar los modelos ({e}). Se reintentará al procesar la sesión.")
                    return
            if models.needs_cuda():
                try:
                    models.ensure_cuda(status)
                    self._set_banner("")
                except Exception:
                    traceback.print_exc()
                    self._set_banner("")

        threading.Thread(target=work, daemon=True).start()

    def _process(self, session_dir):
        self._session_dir = session_dir
        self._meta = None
        self._awake.start()
        self._processing_started = time.monotonic()
        self._show("processing")
        cfg = dict(self._cfg)

        def status(text, p):
            self._send({"type": "progress", "text": text, "p": p})

        def work():
            try:
                meta = pipeline.process(session_dir, cfg, status)
            except Exception as e:
                traceback.print_exc()
                with self._lock:
                    self._awake.stop()
                    self._error = str(e) or e.__class__.__name__
                    self._show("error")
                return
            with self._lock:
                self._awake.stop()
                self._meta = meta
                self._show("done")

        threading.Thread(target=work, daemon=True).start()

    def _tick_loop(self):
        while True:
            time.sleep(0.08)
            if not self._ready:
                continue
            rec = self._recorder
            msg = {"type": "tick", "level": min(1.0, (rec.level * 40) ** 0.6)}
            if self._screen == "recording":
                if rec.paused or rec.level > SILENCE_LEVEL:
                    self._silent_since = None
                elif self._silent_since is None:
                    self._silent_since = time.monotonic()
                msg.update(
                    seconds=rec.seconds,
                    paused=rec.paused,
                    error=rec.error,
                    silent=bool(self._silent_since and time.monotonic() - self._silent_since > SILENCE_SECONDS),
                )
            elif self._screen == "processing":
                msg["elapsed"] = time.monotonic() - self._processing_started
            self._send(msg)

    def _on_closing(self):
        if self._quitting or self._screen not in ("recording", "processing"):
            self._shutdown()
            return True
        threading.Thread(target=self._send, args=({"type": "confirmQuit", "screen": self._screen},), daemon=True).start()
        return False

    def _shutdown(self):
        if self._quitting:
            return
        self._quitting = True
        if self._screen == "recording":
            self._recorder.stop()
        self._awake.stop()
        self._recorder.close()


def main():
    if WIN:
        import ctypes

        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("io.github.arocafull00.colloquia")
    api = Api()
    cfg = api._cfg
    dark = cfg.get("appearance") == "dark" or (cfg.get("appearance", "system") == "system" and dark_mode())
    with open(os.path.join(HERE, "ui.html"), encoding="utf-8") as f:
        html = f.read()
    api._window = webview.create_window(
        APP,
        html=html,
        js_api=api,
        text_select=True,
        width=1040,
        height=720,
        min_size=(760, 560),
        background_color="#171716" if dark else "#f3f1ec",
    )
    api._window.events.closing += api._on_closing
    api._open_mic()
    api._prepare_models()
    threading.Thread(target=api._tick_loop, daemon=True).start()
    icon = os.path.join(HERE, "packaging", "colloquia.ico" if WIN else "colloquia.png")
    webview.start(icon=icon if os.path.exists(icon) else None)
    os._exit(0)


if __name__ == "__main__":
    sys.exit(main())
