import json
import os
import sys

APP = "Colloquia"
MAC = sys.platform == "darwin"
WIN = sys.platform == "win32"


def app_dir():
    if not getattr(sys, "frozen", False):
        return os.path.dirname(os.path.abspath(__file__))
    if os.environ.get("APPIMAGE"):
        return os.path.dirname(os.environ["APPIMAGE"])
    exe_dir = os.path.dirname(sys.executable)
    if MAC and exe_dir.endswith(".app/Contents/MacOS"):
        return os.path.dirname(os.path.dirname(os.path.dirname(exe_dir)))
    return exe_dir


HERE = app_dir()

if WIN:
    CONFIG_DIR = os.path.join(os.environ["APPDATA"], APP)
elif MAC:
    CONFIG_DIR = os.path.expanduser(f"~/Library/Application Support/{APP}")
else:
    CONFIG_DIR = os.path.join(os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config"), "colloquia")
CONFIG_PATH = os.path.join(CONFIG_DIR, "config.json")
LOG_PATH = os.path.join(CONFIG_DIR, "colloquia.log")
MODELS_DIR = os.path.join(CONFIG_DIR, "models")
CUDA_DIR = os.path.join(os.environ.get("LOCALAPPDATA", CONFIG_DIR), APP, "cuda")
os.makedirs(CONFIG_DIR, exist_ok=True)

DEFAULTS = {
    "folder": os.path.join(os.path.expanduser("~"), "Documents", APP),
    "device": "",
    "model": "large-v3-turbo",
    "language": "es",
    "roles": ["Psicólogo", "Paciente"],
    "keep_wav": False,
    "appearance": "system",
    "verbatim": True,
    "pause_min": 1.5,
    "mark_doubtful": True,
}

PAUSES = {"1 segundo": 1.0, "1,5 segundos": 1.5, "2 segundos": 2.0, "3 segundos": 3.0}

LANGUAGES = {
    "Español": "es",
    "English": "en",
    "Català": "ca",
    "Português": "pt",
    "Français": "fr",
    "Deutsch": "de",
    "Italiano": "it",
    "Detectar automáticamente": "auto",
}
MODELS = {
    "Turbo · rápido y preciso (recomendado)": "large-v3-turbo",
    "Large v3 · máxima precisión, más lento": "large-v3",
    "Medium · para equipos sin GPU": "medium",
    "Small · ligero": "small",
}


def load_config():
    cfg = dict(DEFAULTS)
    try:
        with open(CONFIG_PATH, encoding="utf-8") as f:
            cfg.update(json.load(f))
    except (OSError, ValueError):
        pass
    return cfg


def save_config(cfg):
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)
