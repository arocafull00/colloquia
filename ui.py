import os
import queue
import shutil
import threading
import time
import traceback
from tkinter import filedialog, messagebox

import customtkinter as ctk

import models
import pipeline
from config import APP, LANGUAGES, MODELS, PAUSES, load_config, save_config
from platform_utils import KeepAwake, open_folder
from recorder import Recorder, input_devices, interrupted_sessions

BLUE = ("#2f6fed", "#3b7bff")
BLUE_HOVER = ("#2559c4", "#2f6fed")
RED = "#e5484d"
RED_HOVER = "#c93a3f"
ORANGE = "#f5a524"
GREEN = "#30a46c"
MUTED = ("#6b6b70", "#9a9aa2")
CARD = ("#f3f4f6", "#25262b")
SUBTLE = ("#e4e5e9", "#33343a")
DEFAULT_MIC = "Predeterminado del sistema"
STAGES = ["Guardando MP3", "Transcribiendo", "Identificando voces", "Generando texto"]
APPEARANCE = {"Según el sistema": "system", "Claro": "light", "Oscuro": "dark"}
SILENCE_LEVEL = 0.003
SILENCE_SECONDS = 30


def font(size, weight="normal"):
    return ctk.CTkFont(size=size, weight=weight)


def key_for(mapping, value):
    return next((k for k, v in mapping.items() if v == value), next(iter(mapping)))


def clock(seconds):
    s = int(seconds)
    return f"{s // 3600:02d}:{s % 3600 // 60:02d}:{s % 60:02d}"


class RoundButton(ctk.CTkFrame):
    def __init__(self, master, text, size, color, hover, command):
        super().__init__(master, width=size, height=size, corner_radius=size // 2, fg_color=color)
        self.pack_propagate(False)
        self.color, self.hover, self.command = color, hover, command
        self.label = ctk.CTkLabel(self, text=text, font=font(22, "bold"), text_color="white")
        self.label.place(relx=0.5, rely=0.5, anchor="center")
        for w in (self, self.label):
            w.bind("<Enter>", lambda e: self.configure(fg_color=self.hover))
            w.bind("<Leave>", lambda e: self.configure(fg_color=self.color))
            w.bind("<Button-1>", lambda e: self.command())
            w.configure(cursor="hand2")


class App(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.cfg = load_config()
        ctk.set_appearance_mode(self.cfg.get("appearance", "system"))
        self.title(APP)
        self.geometry(self.centered(480, 640))
        self.minsize(440, 600)
        self.protocol("WM_DELETE_WINDOW", self.on_close)

        self.events = queue.Queue()
        self.recorder = Recorder()
        self.awake = KeepAwake()
        self.screen = "home"
        self.session_dir = None
        self.meta = None
        self.silent_since = None
        self.blink = 0
        self.settings = None
        self.processing_started = 0
        self.pending = []

        self.build_header()
        self.body = ctk.CTkFrame(self, fg_color="transparent")
        self.body.pack(fill="both", expand=True, padx=28, pady=(6, 24))
        self.screens = {
            "home": self.build_home(),
            "recording": self.build_recording(),
            "processing": self.build_processing(),
            "done": self.build_done(),
            "error": self.build_error(),
        }
        self.show("home")
        self.open_mic()
        self.refresh_interrupted()
        self.prepare_models()
        self.after(50, self.pump)

    def centered(self, w, h):
        x = (self.winfo_screenwidth() - w) // 2
        y = max(0, (self.winfo_screenheight() - h) // 3)
        return f"{w}x{h}+{x}+{y}"

    def build_header(self):
        bar = ctk.CTkFrame(self, fg_color="transparent")
        bar.pack(fill="x", padx=28, pady=(22, 0))
        titles = ctk.CTkFrame(bar, fg_color="transparent")
        titles.pack(side="left")
        ctk.CTkLabel(titles, text=APP, font=font(26, "bold")).pack(anchor="w")
        ctk.CTkLabel(titles, text="Grabación y transcripción local de sesiones", font=font(13), text_color=MUTED).pack(
            anchor="w"
        )
        self.gear = ctk.CTkButton(
            bar,
            text="⚙",
            width=38,
            height=38,
            corner_radius=19,
            font=font(18),
            fg_color="transparent",
            hover_color=SUBTLE,
            text_color=MUTED,
            command=self.open_settings,
        )
        self.gear.pack(side="right")
        self.banner = ctk.CTkLabel(self, text="", font=font(12), text_color=MUTED, wraplength=420, justify="left")

    def build_home(self):
        f = ctk.CTkFrame(self.body, fg_color="transparent")

        ctk.CTkLabel(f, text="Carpeta de destino", font=font(13, "bold")).pack(anchor="w", pady=(10, 4))
        row = ctk.CTkFrame(f, fg_color=CARD, corner_radius=10)
        row.pack(fill="x")
        self.folder_label = ctk.CTkLabel(row, text="", font=font(13), anchor="w")
        self.folder_label.pack(side="left", fill="x", expand=True, padx=12, pady=10)
        ctk.CTkButton(row, text="Cambiar…", width=90, height=30, command=self.choose_folder).pack(side="right", padx=8)

        ctk.CTkLabel(f, text="Nombre de la sesión (opcional)", font=font(13, "bold")).pack(anchor="w", pady=(16, 4))
        self.name_entry = ctk.CTkEntry(f, height=40, placeholder_text="p. ej. Paciente 014 · Sesión 3", font=font(14))
        self.name_entry.pack(fill="x")

        RoundButton(f, "●\nGrabar", 168, RED, RED_HOVER, self.start_recording).pack(pady=(34, 22))

        self.mic_label = ctk.CTkLabel(f, text="", font=font(12), text_color=MUTED)
        self.mic_label.pack()
        self.home_level = ctk.CTkProgressBar(f, height=8, progress_color=GREEN)
        self.home_level.pack(fill="x", padx=60, pady=(6, 0))
        self.home_level.set(0)

        self.recover = ctk.CTkFrame(f, fg_color=("#fff4e0", "#3a2f1a"), corner_radius=10)
        self.recover_label = ctk.CTkLabel(self.recover, text="", font=font(12), wraplength=300, justify="left")
        self.recover_label.pack(side="left", padx=12, pady=10)
        ctk.CTkButton(
            self.recover, text="Procesar", width=90, height=30, fg_color=ORANGE, hover_color="#d98e14", command=self.recover_session
        ).pack(side="right", padx=10)
        return f

    def build_recording(self):
        f = ctk.CTkFrame(self.body, fg_color="transparent")
        top = ctk.CTkFrame(f, fg_color="transparent")
        top.pack(pady=(60, 0))
        self.rec_dot = ctk.CTkLabel(top, text="●", font=font(22), text_color=RED)
        self.rec_dot.pack(side="left", padx=(0, 8))
        self.rec_state = ctk.CTkLabel(top, text="Grabando", font=font(18, "bold"))
        self.rec_state.pack(side="left")

        self.timer = ctk.CTkLabel(f, text="00:00:00", font=ctk.CTkFont(size=64, weight="bold"))
        self.timer.pack(pady=(14, 4))
        self.rec_folder = ctk.CTkLabel(f, text="", font=font(12), text_color=MUTED, wraplength=400)
        self.rec_folder.pack()

        self.rec_level = ctk.CTkProgressBar(f, height=10, progress_color=GREEN)
        self.rec_level.pack(fill="x", padx=40, pady=(36, 6))
        self.rec_level.set(0)
        self.silence = ctk.CTkLabel(f, text="", font=font(13, "bold"), text_color=ORANGE)
        self.silence.pack(pady=(4, 0))

        buttons = ctk.CTkFrame(f, fg_color="transparent")
        buttons.pack(side="bottom", fill="x", pady=(0, 10))
        self.pause_btn = ctk.CTkButton(
            buttons,
            text="❚❚  Pausar",
            height=52,
            font=font(16, "bold"),
            fg_color=SUBTLE,
            hover_color=CARD,
            text_color=("#1c1c1f", "#f0f0f2"),
            command=self.toggle_pause,
        )
        self.pause_btn.pack(side="left", fill="x", expand=True, padx=(0, 8))
        ctk.CTkButton(
            buttons, text="■  Detener", height=52, font=font(16, "bold"), fg_color=RED, hover_color=RED_HOVER, command=self.stop_recording
        ).pack(side="left", fill="x", expand=True, padx=(8, 0))
        ctk.CTkLabel(
            f,
            text="El audio se guarda en disco continuamente.\nEl equipo no entrará en suspensión mientras grabas.",
            font=font(12),
            text_color=MUTED,
        ).pack(side="bottom", pady=(0, 18))
        return f

    def build_processing(self):
        f = ctk.CTkFrame(self.body, fg_color="transparent")
        ctk.CTkLabel(f, text="Procesando la sesión", font=font(20, "bold")).pack(anchor="w", pady=(30, 4))
        ctk.CTkLabel(
            f,
            text="Todo se procesa en este equipo. Puede tardar unos minutos;\nno cierres Colloquia ni apagues el ordenador.",
            font=font(13),
            text_color=MUTED,
            justify="left",
        ).pack(anchor="w")
        steps = ctk.CTkFrame(f, fg_color=CARD, corner_radius=12)
        steps.pack(fill="x", pady=(24, 18))
        self.step_labels = []
        for name in STAGES:
            lbl = ctk.CTkLabel(steps, text=f"○   {name}", font=font(15), anchor="w", text_color=MUTED)
            lbl.pack(fill="x", padx=18, pady=7)
            self.step_labels.append(lbl)
        self.proc_text = ctk.CTkLabel(f, text="", font=font(13), anchor="w", wraplength=420, justify="left")
        self.proc_text.pack(fill="x")
        self.proc_bar = ctk.CTkProgressBar(f, height=10, progress_color=ORANGE)
        self.proc_bar.pack(fill="x", pady=(8, 4))
        self.proc_bar.set(0)
        self.proc_elapsed = ctk.CTkLabel(f, text="", font=font(12), text_color=MUTED, anchor="w")
        self.proc_elapsed.pack(fill="x")
        return f

    def build_done(self):
        f = ctk.CTkFrame(self.body, fg_color="transparent")
        ctk.CTkLabel(f, text="✓  Sesión guardada", font=font(22, "bold"), text_color=GREEN).pack(anchor="w", pady=(24, 2))
        self.done_info = ctk.CTkLabel(f, text="", font=font(12), text_color=MUTED, anchor="w", justify="left", wraplength=420)
        self.done_info.pack(fill="x")
        ctk.CTkLabel(
            f, text="¿Están bien asignadas las voces?", font=font(14, "bold"), anchor="w"
        ).pack(fill="x", pady=(20, 6))
        self.cards = []
        for color in (BLUE[0], ORANGE):
            card = ctk.CTkFrame(f, fg_color=CARD, corner_radius=12)
            card.pack(fill="x", pady=4)
            ctk.CTkFrame(card, width=5, height=10, fg_color=color, corner_radius=3).pack(side="left", fill="y", padx=(10, 0), pady=10)
            inner = ctk.CTkFrame(card, fg_color="transparent")
            inner.pack(side="left", fill="both", expand=True, padx=10, pady=8)
            role = ctk.CTkLabel(inner, text="", font=font(13, "bold"), anchor="w")
            role.pack(fill="x")
            quote = ctk.CTkLabel(inner, text="", font=font(13), anchor="w", justify="left", wraplength=360, text_color=MUTED)
            quote.pack(fill="x")
            self.cards.append((role, quote))
        ctk.CTkButton(
            f,
            text="⇄  Intercambiar psicólogo y paciente",
            height=36,
            fg_color="transparent",
            border_width=1,
            border_color=SUBTLE,
            text_color=("#1c1c1f", "#f0f0f2"),
            hover_color=SUBTLE,
            command=self.swap,
        ).pack(fill="x", pady=(8, 0))
        buttons = ctk.CTkFrame(f, fg_color="transparent")
        buttons.pack(side="bottom", fill="x", pady=(0, 10))
        ctk.CTkButton(
            buttons,
            text="Nueva sesión",
            height=48,
            font=font(15, "bold"),
            fg_color=SUBTLE,
            hover_color=CARD,
            text_color=("#1c1c1f", "#f0f0f2"),
            command=self.new_session,
        ).pack(side="left", fill="x", expand=True, padx=(0, 8))
        ctk.CTkButton(
            buttons,
            text="Abrir carpeta",
            height=48,
            font=font(15, "bold"),
            fg_color=BLUE,
            hover_color=BLUE_HOVER,
            command=lambda: open_folder(self.session_dir),
        ).pack(side="left", fill="x", expand=True, padx=(8, 0))
        return f

    def build_error(self):
        f = ctk.CTkFrame(self.body, fg_color="transparent")
        ctk.CTkLabel(f, text="No se pudo procesar la sesión", font=font(20, "bold"), text_color=RED).pack(anchor="w", pady=(30, 8))
        self.error_text = ctk.CTkLabel(f, text="", font=font(13), anchor="w", justify="left", wraplength=420)
        self.error_text.pack(fill="x")
        ctk.CTkLabel(
            f,
            text="La grabación está a salvo en la carpeta de la sesión. Puedes reintentarlo ahora o más tarde desde la pantalla de inicio.",
            font=font(12),
            text_color=MUTED,
            anchor="w",
            justify="left",
            wraplength=420,
        ).pack(fill="x", pady=(12, 0))
        buttons = ctk.CTkFrame(f, fg_color="transparent")
        buttons.pack(side="bottom", fill="x", pady=(0, 10))
        ctk.CTkButton(
            buttons,
            text="Volver",
            height=48,
            fg_color=SUBTLE,
            hover_color=CARD,
            text_color=("#1c1c1f", "#f0f0f2"),
            command=self.new_session,
        ).pack(side="left", fill="x", expand=True, padx=(0, 8))
        ctk.CTkButton(buttons, text="Reintentar", height=48, command=lambda: self.process(self.session_dir)).pack(
            side="left", fill="x", expand=True, padx=(8, 0)
        )
        return f

    def show(self, screen):
        self.screen = screen
        for name, frame in self.screens.items():
            if name == screen:
                frame.pack(fill="both", expand=True)
            else:
                frame.pack_forget()
        self.gear.configure(state="normal" if screen in ("home", "done", "error") else "disabled")
        if screen == "home":
            self.refresh_home()

    def refresh_home(self):
        folder = self.cfg["folder"]
        shown = folder if len(folder) <= 44 else "…" + folder[-43:]
        self.folder_label.configure(text=shown)
        self.mic_label.configure(text=f"🎙  {self.cfg['device'] or DEFAULT_MIC}")

    def refresh_interrupted(self):
        self.pending = interrupted_sessions(self.cfg["folder"])
        if self.pending:
            name = os.path.basename(self.pending[0])
            more = f" (y {len(self.pending) - 1} más)" if len(self.pending) > 1 else ""
            self.recover_label.configure(text=f"Hay una grabación sin procesar: {name}{more}")
            self.recover.pack(fill="x", side="bottom")
        else:
            self.recover.pack_forget()

    def open_mic(self):
        try:
            self.recorder.open(self.cfg["device"])
        except Exception as e:
            traceback.print_exc()
            messagebox.showerror(APP, f"No se pudo abrir el micrófono:\n{e}")

    def prepare_models(self):
        model = self.cfg["model"]

        def status(text, p):
            self.events.put(("banner", text + (f" {p * 100:.0f}%" if p is not None else "")))

        def work():
            if not models.missing(model):
                return
            status("Preparando modelos (solo la primera vez)…", None)
            try:
                models.ensure(model, status)
                self.events.put(("banner", ""))
            except Exception as e:
                traceback.print_exc()
                self.events.put(("banner", f"No se pudieron descargar los modelos ({e}). Se reintentará al procesar la sesión."))

        threading.Thread(target=work, daemon=True).start()

    def choose_folder(self):
        path = filedialog.askdirectory(initialdir=self.cfg["folder"] if os.path.isdir(self.cfg["folder"]) else os.path.expanduser("~"))
        if path:
            self.cfg["folder"] = os.path.normpath(path)
            save_config(self.cfg)
            self.refresh_home()
            self.refresh_interrupted()

    def start_recording(self):
        if self.recorder.stream is None:
            self.open_mic()
            if self.recorder.stream is None:
                return
        try:
            self.session_dir = self.recorder.start(self.cfg["folder"], self.name_entry.get())
        except OSError as e:
            messagebox.showerror(APP, f"No se puede escribir en la carpeta de destino:\n{e}")
            return
        save_config(self.cfg)
        self.awake.start()
        self.silent_since = None
        self.rec_state.configure(text="Grabando")
        self.pause_btn.configure(text="❚❚  Pausar")
        self.rec_folder.configure(text=os.path.basename(self.session_dir))
        self.show("recording")

    def toggle_pause(self):
        self.recorder.paused = not self.recorder.paused
        paused = self.recorder.paused
        self.pause_btn.configure(text="▶  Reanudar" if paused else "❚❚  Pausar")
        self.rec_state.configure(text="En pausa" if paused else "Grabando")

    def stop_recording(self):
        if not messagebox.askyesno(APP, "¿Terminar la grabación y procesar la sesión?", parent=self):
            return
        session_dir = self.recorder.stop()
        if self.recorder.seconds < 1:
            self.awake.stop()
            shutil.rmtree(session_dir, ignore_errors=True)
            messagebox.showinfo(APP, "La grabación está vacía; no hay nada que procesar.", parent=self)
            self.show("home")
            return
        self.process(session_dir)

    def recover_session(self):
        if self.pending:
            self.process(self.pending[0])

    def process(self, session_dir):
        self.session_dir = session_dir
        self.awake.start()
        self.processing_started = time.monotonic()
        for lbl, name in zip(self.step_labels, STAGES):
            lbl.configure(text=f"○   {name}", text_color=MUTED, font=font(15))
        self.proc_text.configure(text="Preparando…")
        self.proc_bar.set(0)
        self.show("processing")
        cfg = dict(self.cfg)

        def status(text, p):
            self.events.put(("status", text, p))

        def work():
            try:
                self.events.put(("done", pipeline.process(session_dir, cfg, status)))
            except Exception as e:
                traceback.print_exc()
                self.events.put(("error", str(e) or e.__class__.__name__))

        threading.Thread(target=work, daemon=True).start()

    def on_status(self, text, p):
        self.proc_text.configure(text=text)
        current = next((i for i, name in enumerate(STAGES) if text.startswith(name)), None)
        if current is not None:
            for i, (lbl, name) in enumerate(zip(self.step_labels, STAGES)):
                if i < current:
                    lbl.configure(text=f"✓   {name}", text_color=GREEN, font=font(15))
                elif i == current:
                    lbl.configure(text=f"●   {name}", text_color=ORANGE, font=font(15, "bold"))
        if p is None:
            if self.proc_bar.cget("mode") != "indeterminate":
                self.proc_bar.configure(mode="indeterminate")
                self.proc_bar.start()
        else:
            if self.proc_bar.cget("mode") != "determinate":
                self.proc_bar.stop()
                self.proc_bar.configure(mode="determinate")
            self.proc_bar.set(p)

    def on_done(self, meta):
        self.awake.stop()
        self.proc_bar.stop()
        self.proc_bar.configure(mode="determinate")
        self.meta = meta
        self.done_info.configure(
            text=f"{os.path.basename(self.session_dir)} · {clock(meta['duration'])} · {len(meta['turns'])} intervenciones\n"
            f"sesion.mp3 y transcripcion.txt"
        )
        self.fill_cards()
        self.refresh_interrupted()
        self.show("done")
        self.bell()

    def fill_cards(self):
        found = pipeline.samples(self.meta)
        for i, (role, quote) in enumerate(self.cards):
            role.configure(text=self.cfg["roles"][i])
            quote.configure(text=f"«{found[i]}»" if i in found else "(no se ha detectado otra voz)")

    def on_error(self, message):
        self.awake.stop()
        self.proc_bar.stop()
        self.proc_bar.configure(mode="determinate")
        self.error_text.configure(text=message)
        self.refresh_interrupted()
        self.show("error")

    def swap(self):
        self.meta = pipeline.swap_roles(self.session_dir, self.cfg)
        self.fill_cards()

    def new_session(self):
        self.name_entry.delete(0, "end")
        self.refresh_interrupted()
        self.show("home")

    def pump(self):
        while True:
            try:
                event = self.events.get_nowait()
            except queue.Empty:
                break
            kind, *args = event
            if kind == "status":
                self.on_status(*args)
            elif kind == "done":
                self.on_done(*args)
            elif kind == "error":
                self.on_error(*args)
            elif kind == "banner":
                self.set_banner(*args)
        level = min(1.0, (self.recorder.level * 40) ** 0.6)
        if self.screen == "home":
            self.home_level.set(level)
        elif self.screen == "recording":
            self.tick_recording(level)
        elif self.screen == "processing":
            self.proc_elapsed.configure(text=f"Tiempo transcurrido: {clock(time.monotonic() - self.processing_started)}")
        self.after(50, self.pump)

    def tick_recording(self, level):
        rec = self.recorder
        self.timer.configure(text=clock(rec.seconds))
        self.rec_level.set(0 if rec.paused else level)
        self.blink = (self.blink + 1) % 20
        self.rec_dot.configure(text_color=ORANGE if rec.paused else (RED if self.blink < 12 else CARD[1]))
        if rec.error:
            self.silence.configure(text=f"Error al escribir en disco: {rec.error}", text_color=RED)
            return
        if rec.paused or rec.level > SILENCE_LEVEL:
            self.silent_since = None
        elif self.silent_since is None:
            self.silent_since = time.monotonic()
        silent = self.silent_since and time.monotonic() - self.silent_since > SILENCE_SECONDS
        self.silence.configure(text="No se detecta audio. Revisa el micrófono." if silent else "")

    def set_banner(self, text):
        if text:
            self.banner.configure(text=text)
            self.banner.pack(after=self.gear.master, fill="x", padx=28, pady=(8, 0))
        else:
            self.banner.pack_forget()

    def open_settings(self):
        if self.settings and self.settings.winfo_exists():
            self.settings.focus()
            return
        self.settings = Settings(self)

    def apply_settings(self, cfg):
        model_changed = cfg["model"] != self.cfg["model"]
        self.cfg = cfg
        save_config(cfg)
        ctk.set_appearance_mode(cfg["appearance"])
        self.open_mic()
        self.refresh_home()
        if self.meta and self.screen == "done":
            pipeline.write_txt(self.session_dir, cfg)
            self.fill_cards()
        if model_changed:
            self.prepare_models()

    def on_close(self):
        if self.screen == "recording":
            if not messagebox.askyesno(
                APP, "Hay una grabación en curso. ¿Detenerla y salir?\nPodrás procesarla la próxima vez que abras Colloquia.", parent=self
            ):
                return
            self.recorder.stop()
        elif self.screen == "processing":
            if not messagebox.askyesno(
                APP, "Se está procesando la sesión. Si sales ahora podrás retomarla la próxima vez.\n¿Salir de todos modos?", parent=self
            ):
                return
        self.awake.stop()
        self.recorder.close()
        self.destroy()
        os._exit(0)


class Settings(ctk.CTkToplevel):
    def __init__(self, app):
        super().__init__(app)
        self.app = app
        cfg = app.cfg
        self.title(f"{APP} · Ajustes")
        self.geometry(f"+{app.winfo_x() + 30}+{app.winfo_y() + 60}")
        self.resizable(False, False)
        self.transient(app)

        f = ctk.CTkFrame(self, fg_color="transparent")
        f.pack(fill="both", expand=True, padx=24, pady=20)
        f.columnconfigure(1, weight=1)

        self.device = ctk.StringVar(value=cfg["device"] or DEFAULT_MIC)
        self.model = ctk.StringVar(value=key_for(MODELS, cfg["model"]))
        self.language = ctk.StringVar(value=key_for(LANGUAGES, cfg["language"]))
        self.appearance = ctk.StringVar(value=key_for(APPEARANCE, cfg.get("appearance", "system")))
        self.keep_wav = ctk.BooleanVar(value=cfg["keep_wav"])
        self.verbatim = ctk.BooleanVar(value=cfg["verbatim"])
        self.doubtful = ctk.BooleanVar(value=cfg["mark_doubtful"])
        self.pause = ctk.StringVar(value=key_for(PAUSES, cfg["pause_min"]))

        r = 0
        for label, var, values in (
            ("Micrófono", self.device, [DEFAULT_MIC] + input_devices()),
            ("Modelo", self.model, list(MODELS)),
            ("Idioma", self.language, list(LANGUAGES)),
            ("Marcar silencios de", self.pause, list(PAUSES)),
            ("Apariencia", self.appearance, list(APPEARANCE)),
        ):
            ctk.CTkLabel(f, text=label, font=font(13)).grid(row=r, column=0, sticky="w", pady=6, padx=(0, 14))
            ctk.CTkOptionMenu(f, variable=var, values=values, width=300, dynamic_resizing=False).grid(row=r, column=1, sticky="ew")
            r += 1

        self.roles = []
        for i, label in enumerate(("Primera voz", "Segunda voz")):
            ctk.CTkLabel(f, text=label, font=font(13)).grid(row=r, column=0, sticky="w", pady=6, padx=(0, 14))
            e = ctk.CTkEntry(f)
            e.insert(0, cfg["roles"][i])
            e.grid(row=r, column=1, sticky="ew")
            self.roles.append(e)
            r += 1
        ctk.CTkLabel(
            f, text="La primera voz es la de quien habla primero en la sesión.", font=font(11), text_color=MUTED
        ).grid(row=r, column=1, sticky="w")
        r += 1

        for text, var, pady in (
            ("Transcripción literal: conservar muletillas, repeticiones y titubeos", self.verbatim, (14, 0)),
            ("Marcar las palabras dudosas con [?] para revisarlas", self.doubtful, (8, 0)),
            ("Conservar también el audio sin comprimir (.wav)", self.keep_wav, (8, 0)),
        ):
            ctk.CTkSwitch(f, text=text, variable=var).grid(row=r, column=0, columnspan=2, sticky="w", pady=pady)
            r += 1
        ctk.CTkLabel(
            f,
            text="Los modelos se descargan una sola vez. Después Colloquia funciona sin conexión\ny nunca envía audio ni texto fuera de este equipo.",
            font=font(11),
            text_color=MUTED,
            justify="left",
        ).grid(row=r, column=0, columnspan=2, sticky="w", pady=(14, 0))
        r += 1

        buttons = ctk.CTkFrame(f, fg_color="transparent")
        buttons.grid(row=r, column=0, columnspan=2, sticky="e", pady=(18, 0))
        ctk.CTkButton(
            buttons, text="Cancelar", width=100, fg_color=SUBTLE, hover_color=CARD, text_color=("#1c1c1f", "#f0f0f2"), command=self.destroy
        ).pack(side="right")
        ctk.CTkButton(buttons, text="Guardar", width=100, command=self.save).pack(side="right", padx=(0, 8))
        self.after(150, self.lift_once)

    def lift_once(self):
        self.lift()
        self.focus_force()

    def save(self):
        mic = self.device.get()
        roles = [e.get().strip() or default for e, default in zip(self.roles, ("Psicólogo", "Paciente"))]
        cfg = dict(self.app.cfg)
        cfg.update(
            device="" if mic == DEFAULT_MIC else mic,
            model=MODELS[self.model.get()],
            language=LANGUAGES[self.language.get()],
            appearance=APPEARANCE[self.appearance.get()],
            roles=roles,
            keep_wav=self.keep_wav.get(),
            verbatim=self.verbatim.get(),
            mark_doubtful=self.doubtful.get(),
            pause_min=PAUSES[self.pause.get()],
        )
        self.app.apply_settings(cfg)
        self.destroy()
