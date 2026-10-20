import glob
import json
import os
import ssl
import sys
import tarfile
import threading
import urllib.request
import zipfile

import truststore

from config import CUDA_DIR, HERE, MODELS_DIR, WIN

RELEASES = "https://github.com/k2-fsa/sherpa-onnx/releases/download"
SEGMENTATION_URL = f"{RELEASES}/speaker-segmentation-models/sherpa-onnx-pyannote-segmentation-3-0.tar.bz2"
EMBEDDING_URL = f"{RELEASES}/speaker-recongition-models/3dspeaker_speech_campplus_sv_zh_en_16k-common_advanced.onnx"
LOCAL_DIR = os.path.join(HERE, "models")
LOCK = threading.Lock()
CUDA_PACKAGES = ["nvidia-cublas-cu12", "nvidia-cudnn-cu12", "nvidia-cuda-nvrtc-cu12"]
PACKAGES = getattr(sys, "_MEIPASS", os.path.join(sys.prefix, "Lib", "site-packages"))


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
            ("transcripción", whisper_path(model_name)),
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


def ensure(model_name, status):
    with LOCK:
        _ensure(model_name, status)


def _ensure(model_name, status):
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
    if not whisper_path(model_name):
        status(f"Descargando modelo de transcripción {model_name} (3/3). Puede tardar varios minutos…", None)
        from faster_whisper import download_model

        download_model(model_name)
    os.environ["HF_HUB_OFFLINE"] = "1"
