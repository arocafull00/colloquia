import os
import ssl
import tarfile
import threading
import urllib.request

import truststore

from config import HERE, MODELS_DIR

RELEASES = "https://github.com/k2-fsa/sherpa-onnx/releases/download"
SEGMENTATION_URL = f"{RELEASES}/speaker-segmentation-models/sherpa-onnx-pyannote-segmentation-3-0.tar.bz2"
EMBEDDING_URL = f"{RELEASES}/speaker-recongition-models/3dspeaker_speech_campplus_sv_zh_en_16k-common_advanced.onnx"
LOCAL_DIR = os.path.join(HERE, "models")
LOCK = threading.Lock()


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


def _download(url, dest, progress):
    tmp = dest + ".part"
    with urllib.request.urlopen(url, context=truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT)) as r, open(tmp, "wb") as f:
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
