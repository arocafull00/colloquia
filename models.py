import glob
import json
import os
import re
import shutil
import ssl
import sys
import tarfile
import threading
import urllib.request
import zipfile

import truststore

from config import CONFIG_DIR, CUDA_DIR, HERE, MAC, MODELS_DIR, WIN
from platform_utils import total_ram

RELEASES = "https://github.com/k2-fsa/sherpa-onnx/releases/download"
EMBEDDING_URL = f"{RELEASES}/speaker-recongition-models/nemo_en_titanet_small.onnx"
LOCAL_DIR = os.path.join(HERE, "models")
LOCK = threading.Lock()
CUDA_PACKAGES = ["nvidia-cublas-cu12", "nvidia-cudnn-cu12", "nvidia-cuda-nvrtc-cu12"]
PACKAGES = getattr(sys, "_MEIPASS", os.path.join(sys.prefix, "Lib", "site-packages"))
GGML_URL = "https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-{}.bin"
GGML = {"large-v3-turbo": "large-v3-turbo-q5_0", "large-v3": "large-v3-q5_0", "medium": "medium-q5_0", "small": "small-q5_1"}
SHERPA_URL = f"{RELEASES}/asr-models/{{}}.tar.bz2"
SHERPA = {
    "parakeet-v3": ("sherpa-onnx-nemo-parakeet-tdt-0.6b-v3-int8", "encoder.int8.onnx"),
    "literal": ("sherpa-onnx-omnilingual-asr-1600-languages-300M-ctc-int8-2025-11-12", "model.int8.onnx"),
}
WHISPER_FILES = re.compile(r"^(config\.json|preprocessor_config\.json|model\.bin|tokenizer\.json|vocabulary\..*)$")
HF = "https://huggingface.co"
AUTO_PATH = os.path.join(CONFIG_DIR, "modelo-automatico.txt")
FAST = "parakeet-v3"
BALANCED = "large-v3-turbo"
STRONG_RAM = 12 << 30
STRONG_CPUS = 8


def embedding_path():
    return _find(os.path.basename(EMBEDDING_URL))


def whisper_path(name):
    local = _find(f"faster-whisper-{name}", "model.bin")
    if local:
        return os.path.dirname(local)
    from faster_whisper import download_model

    try:
        return download_model(name, local_files_only=True)
    except Exception:
        return None


def _find(*parts):
    for base in (LOCAL_DIR, MODELS_DIR):
        p = os.path.join(base, *parts)
        if os.path.exists(p):
            return p
    return None


def sherpa_path(name):
    folder, file = SHERPA[name]
    found = _find(folder, file)
    return os.path.dirname(found) if found else None


def is_sherpa(name):
    return name in SHERPA


def resolve(name):
    if name != "auto":
        return name
    try:
        with open(AUTO_PATH, encoding="utf-8") as f:
            saved = f.read().strip()
    except OSError:
        saved = ""
    return saved or guess()


def guess():
    if (WIN and (cuda_ready() or needs_cuda())) or uses_whisper_cpp():
        return BALANCED
    return BALANCED if total_ram() >= STRONG_RAM and (os.cpu_count() or 1) >= STRONG_CPUS else FAST


def remember(name):
    with open(AUTO_PATH, "w", encoding="utf-8") as f:
        f.write(name)


def wants_literal(cfg):
    return cfg.get("literal", True) and cfg.get("language") == "es"


def transcriber_path(name, cpp=None):
    if is_sherpa(name):
        return sherpa_path(name)
    if uses_whisper_cpp() if cpp is None else cpp:
        return ggml_path(name)
    return whisper_path(name)


def missing(model_name, literal=False):
    checks = (
        ("voces", embedding_path()),
        ("transcripción", transcriber_path(resolve(model_name))),
        ("pronunciación literal", sherpa_path("literal") if literal else True),
    )
    return [label for label, ok in checks if not ok]


def cuda_ready():
    return any(glob.glob(os.path.join(root, "nvidia", "cudnn", "bin", "cudnn64_*.dll")) for root in (PACKAGES, CUDA_DIR))


def gpu_wanted():
    import winreg

    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Colloquia") as k:
            return winreg.QueryValueEx(k, "GpuSupport")[0] != 0
    except OSError:
        return True


def needs_cuda():
    nvcuda = os.path.join(os.environ.get("SystemRoot", r"C:\Windows"), "System32", "nvcuda.dll")
    return WIN and os.path.exists(nvcuda) and not cuda_ready() and gpu_wanted()


def ensure_cuda(status):
    tmp = CUDA_DIR + ".partial"
    os.makedirs(tmp, exist_ok=True)
    for i, name in enumerate(CUDA_PACKAGES, 1):
        with _open(f"https://pypi.org/pypi/{name}/json") as r:
            files = json.load(r)["urls"]
        url = next(f["url"] for f in files if f["filename"].endswith("win_amd64.whl"))
        wheel = os.path.join(tmp, name + ".whl")
        _download(url, wheel, lambda p: status(f"Descargando soporte de GPU NVIDIA ({i}/{len(CUDA_PACKAGES)})…", p))
        with zipfile.ZipFile(wheel) as z:
            z.extractall(tmp, [m for m in z.namelist() if m.startswith("nvidia/") and m.lower().endswith(".dll")])
        os.remove(wheel)
    os.replace(tmp, CUDA_DIR)


def whisper_cli():
    exe = "whisper-cli.exe" if WIN else "whisper-cli"
    for p in (os.environ.get("COLLOQUIA_WHISPER_CLI"), os.path.join(PACKAGES, "whisper-cpp", exe), os.path.join(HERE, "whisper-cpp", exe)):
        if p and os.path.exists(p):
            return p
    return None


def ggml_path(name):
    return _find(f"ggml-{GGML.get(name, name)}.bin")


def gpu_names():
    import ctypes
    from ctypes import wintypes

    class DISPLAY_DEVICEW(ctypes.Structure):
        _fields_ = [
            ("cb", wintypes.DWORD),
            ("DeviceName", wintypes.WCHAR * 32),
            ("DeviceString", wintypes.WCHAR * 128),
            ("StateFlags", wintypes.DWORD),
            ("DeviceID", wintypes.WCHAR * 128),
            ("DeviceKey", wintypes.WCHAR * 128),
        ]

    names, i = set(), 0
    d = DISPLAY_DEVICEW(cb=ctypes.sizeof(DISPLAY_DEVICEW))
    while ctypes.windll.user32.EnumDisplayDevicesW(None, i, ctypes.byref(d), 0):
        names.add(d.DeviceString)
        i += 1
    return names


def has_gpu():
    if MAC:
        import platform

        return platform.machine() == "arm64"
    if WIN:
        return any(re.search(r"nvidia|amd|radeon|intel.*(arc|iris|uhd)", n, re.I) for n in gpu_names())
    return bool(glob.glob("/dev/dri/renderD*"))


def uses_whisper_cpp():
    engine = os.environ.get("COLLOQUIA_ENGINE")
    if engine:
        return engine == "whispercpp" and bool(whisper_cli())
    if WIN and (cuda_ready() or needs_cuda()):
        return False
    return bool(whisper_cli()) and has_gpu()


def _open(url):
    return urllib.request.urlopen(url, context=truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT))


def _download(url, dest, progress):
    tmp = f"{dest}.{os.getpid()}.part"
    with _open(url) as r, open(tmp, "wb") as f:
        total = int(r.headers.get("Content-Length") or 0)
        done = 0
        while chunk := r.read(1 << 16):
            f.write(chunk)
            done += len(chunk)
            if total:
                progress(done / total)
    os.replace(tmp, dest)


def _fetch_tar(url, progress):
    archive = os.path.join(MODELS_DIR, f".{os.path.basename(url)}.{os.getpid()}")
    tmp = os.path.join(MODELS_DIR, f".extract-{os.getpid()}")
    _download(url, archive, lambda p: progress(p * 0.85))
    size = os.path.getsize(archive) or 1
    shutil.rmtree(tmp, ignore_errors=True)
    with open(archive, "rb") as raw, tarfile.open(fileobj=raw, mode="r:bz2") as t:
        for member in t:
            t.extract(member, tmp, filter="data")
            progress(0.85 + 0.15 * raw.tell() / size)
    for entry in os.listdir(tmp):
        dest = os.path.join(MODELS_DIR, entry)
        shutil.rmtree(dest, ignore_errors=True)
        os.replace(os.path.join(tmp, entry), dest)
    shutil.rmtree(tmp, ignore_errors=True)
    os.remove(archive)


def _fetch_whisper(name, progress):
    from faster_whisper.utils import _MODELS

    repo = _MODELS.get(name, name)
    with _open(f"{HF}/api/models/{repo}?blobs=true") as r:
        siblings = json.load(r)["siblings"]
    files = [(s["rfilename"], s.get("size") or 0) for s in siblings if WHISPER_FILES.match(s["rfilename"])]
    total = sum(size for _, size in files) or 1
    dest = os.path.join(MODELS_DIR, f"faster-whisper-{name}")
    tmp = dest + ".partial"
    os.makedirs(tmp, exist_ok=True)
    done = 0
    for file, size in files:
        _download(f"{HF}/{repo}/resolve/main/{file}", os.path.join(tmp, file), lambda p: progress((done + p * size) / total))
        done += size
    shutil.rmtree(dest, ignore_errors=True)
    os.replace(tmp, dest)


def ensure(model_name, status, cpp=None, literal=False, transcriber=True):
    with LOCK:
        name = resolve(model_name)
        _ensure(name if transcriber else None, status, uses_whisper_cpp() if cpp is None else cpp, literal)
        return name


def _ensure(name, status, cpp, literal):
    os.makedirs(MODELS_DIR, exist_ok=True)
    steps = []
    if not embedding_path():
        steps.append(("el modelo de voces", lambda p: _download(EMBEDDING_URL, os.path.join(MODELS_DIR, os.path.basename(EMBEDDING_URL)), p)))
    if name is None:
        pass
    elif is_sherpa(name):
        if not sherpa_path(name):
            steps.append(("el modelo de transcripción", lambda p: _fetch_tar(SHERPA_URL.format(SHERPA[name][0]), p)))
    elif cpp:
        if not ggml_path(name):
            file = GGML.get(name, name)
            steps.append(("el modelo de transcripción", lambda p: _download(GGML_URL.format(file), os.path.join(MODELS_DIR, f"ggml-{file}.bin"), p)))
    elif not whisper_path(name):
        steps.append(("el modelo de transcripción", lambda p: _fetch_whisper(name, p)))
    if literal and not sherpa_path("literal"):
        steps.append(("el modelo de pronunciación literal", lambda p: _fetch_tar(SHERPA_URL.format(SHERPA["literal"][0]), p)))
    for i, (label, run) in enumerate(steps, 1):
        status(f"Descargando {label} ({i}/{len(steps)})…", 0)
        run(lambda p: status(f"Descargando {label} ({i}/{len(steps)})…", p))
    os.environ["HF_HUB_OFFLINE"] = "1"
