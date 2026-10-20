import glob
import json
import os
import re
import ssl
import sys
import tarfile
import threading
import urllib.request
import zipfile

import truststore

from config import CUDA_DIR, HERE, MAC, MODELS_DIR, WIN

RELEASES = "https://github.com/k2-fsa/sherpa-onnx/releases/download"
SEGMENTATION_URL = f"{RELEASES}/speaker-segmentation-models/sherpa-onnx-pyannote-segmentation-3-0.tar.bz2"
EMBEDDING_URL = f"{RELEASES}/speaker-recongition-models/3dspeaker_speech_campplus_sv_zh_en_16k-common_advanced.onnx"
LOCAL_DIR = os.path.join(HERE, "models")
LOCK = threading.Lock()
CUDA_PACKAGES = ["nvidia-cublas-cu12", "nvidia-cudnn-cu12", "nvidia-cuda-nvrtc-cu12"]
PACKAGES = getattr(sys, "_MEIPASS", os.path.join(sys.prefix, "Lib", "site-packages"))
GGML_URL = "https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-{}.bin"
GGML = {"large-v3-turbo": "large-v3-turbo-q5_0", "large-v3": "large-v3-q5_0", "medium": "medium-q5_0", "small": "small-q5_1"}


def segmentation_path():
    return _find("sherpa-onnx-pyannote-segmentation-3-0", "model.onnx")


def embedding_path():
    return _find(os.path.basename(EMBEDDING_URL))


def whisper_path(name):
    local = os.path.join(LOCAL_DIR, f"faster-whisper-{name}")
    if os.path.exists(os.path.join(local, "model.bin")):
        return local
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


def missing(model_name):
    return [
        label
        for label, ok in (
            ("voces", segmentation_path() and embedding_path()),
            ("transcripción", ggml_path(model_name) if uses_whisper_cpp() else whisper_path(model_name)),
        )
        if not ok
    ]


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
    tmp = dest + ".part"
    with _open(url) as r, open(tmp, "wb") as f:
        total = int(r.headers.get("Content-Length") or 0)
        done = 0
        while chunk := r.read(1 << 16):
            f.write(chunk)
            done += len(chunk)
            if total:
                progress(done / total)
    os.replace(tmp, dest)


def ensure(model_name, status, cpp=None):
    with LOCK:
        _ensure(model_name, status, uses_whisper_cpp() if cpp is None else cpp)


def _ensure(model_name, status, cpp):
    os.makedirs(MODELS_DIR, exist_ok=True)
    if not segmentation_path():
        archive = os.path.join(MODELS_DIR, "segmentation.tar.bz2")
        _download(SEGMENTATION_URL, archive, lambda p: status("Descargando modelo de voces (1/3)…", p))
        with tarfile.open(archive) as t:
            t.extractall(MODELS_DIR, filter="data")
        os.remove(archive)
    if not embedding_path():
        _download(
            EMBEDDING_URL,
            os.path.join(MODELS_DIR, os.path.basename(EMBEDDING_URL)),
            lambda p: status("Descargando modelo de voces (2/3)…", p),
        )
    if cpp and not ggml_path(model_name):
        file = GGML.get(model_name, model_name)
        _download(
            GGML_URL.format(file),
            os.path.join(MODELS_DIR, f"ggml-{file}.bin"),
            lambda p: status(f"Descargando modelo de transcripción {model_name} (3/3)…", p),
        )
    if not cpp and not whisper_path(model_name):
        status(f"Descargando modelo de transcripción {model_name} (3/3). Puede tardar varios minutos…", None)
        from faster_whisper import download_model

        download_model(model_name)
    os.environ["HF_HUB_OFFLINE"] = "1"
