import bisect
import gc
import glob
import json
import multiprocessing
import os
import queue
import re
import sys
import threading
import time
import traceback
import wave
from datetime import datetime

import lameenc
import numpy as np

import models
import whisper_cpp
from config import CUDA_DIR, MAC, WIN

PACKAGES = getattr(sys, "_MEIPASS", os.path.join(sys.prefix, "Lib", "site-packages"))


def add_cuda_dirs():
    for d in glob.glob(os.path.join(PACKAGES, "nvidia", "*", "bin")) + glob.glob(os.path.join(CUDA_DIR, "nvidia", "*", "bin")):
        if d not in os.environ["PATH"]:
            os.add_dll_directory(d)
            os.environ["PATH"] = d + os.pathsep + os.environ["PATH"]


if WIN:
    add_cuda_dirs()
from recorder import PCM, read_meta, write_meta

RATE = 16000
MP3 = "sesion.mp3"
WAV = "sesion.wav"
TXT = "transcripcion.txt"
PARTIAL = ".transcripcion.jsonl"
CHUNK = 1 << 20
THREADS = max(1, min(8, (os.cpu_count() or 2) // 2))
DOUBTFUL = 0.45
MIN_SILENCE = 0.8
CHUNK_MIN = 30
CHUNK_MAX = 90
CUT_GAP = 0.5
VERBATIM_HINT = "Eh... mmm, pues... yo, yo quería, eh... el pe... el perro. Mmm, no, no sé. Ah, vale. Este... o sea, eh..."
HALLUCINATIONS = ("amara.org", "subtítulos realizados", "subtítulos por la comunidad")
WORD_EDGES = re.compile(r"^(\s*)(.*?)([.,;:!?…»\"')\]]*)$", re.S)


def hms(t):
    t = int(t)
    return f"{t // 3600:02d}:{t % 3600 // 60:02d}:{t % 60:02d}"


def secs(t):
    return f"{t:.1f}".replace(".", ",") + " s"


def load_whisper(name):
    from faster_whisper import WhisperModel

    if models.uses_whisper_cpp():
        return whisper_cpp.Model(models.whisper_cli(), models.ggml_path(name), THREADS), "GPU"
    path = models.whisper_path(name) or name
    if WIN and models.cuda_ready():
        add_cuda_dirs()
        try:
            model = WhisperModel(path, device="cuda", compute_type="float16")
            list(model.transcribe(np.zeros(RATE, np.float32), language="es")[0])
            return model, "GPU"
        except Exception as e:
            print(f"GPU no disponible ({e}); usando CPU.")
    return WhisperModel(path, device="cpu", compute_type="int8"), "CPU"


def write_wav(session_dir, rate, status):
    pcm = os.path.join(session_dir, PCM)
    total = os.path.getsize(pcm) or 1
    done = 0
    with open(pcm, "rb") as src, wave.open(os.path.join(session_dir, WAV), "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(rate)
        while chunk := src.read(CHUNK):
            chunk = chunk[: len(chunk) // 2 * 2]
            wav.writeframes(chunk)
            done += len(chunk)
            status("Guardando MP3…", done / total)


def mp3_encoder(rate):
    enc = lameenc.Encoder()
    enc.set_bit_rate(64)
    enc.set_in_sample_rate(rate)
    enc.set_channels(1)
    enc.set_quality(2)
    return enc


class Whisper:
    def __init__(self, cfg):
        self.cfg = cfg
        self.model, self.device = load_whisper(cfg["model"])

    def words(self, audio, offset, status):
        try:
            words = run_whisper(self.model, audio, self.cfg, status)
        except whisper_cpp.Unavailable as e:
            print(f"whisper.cpp no disponible ({e}); usando CPU.")
            from faster_whisper import WhisperModel

            models.ensure(self.cfg["model"], status, cpp=False)
            self.model = WhisperModel(models.whisper_path(self.cfg["model"]), device="cpu", compute_type="int8")
            self.device = "CPU"
            words = run_whisper(self.model, audio, self.cfg, status)
        return [[round(s + offset, 3), round(e + offset, 3), w, p] for s, e, w, p in words]


def run_whisper(model, audio, cfg, status):
    duration = len(audio) / RATE or 1
    verbatim = cfg.get("verbatim", True)
    segments, _ = model.transcribe(
        audio,
        language=None if cfg["language"] == "auto" else cfg["language"],
        beam_size=5,
        vad_filter=True,
        vad_parameters=dict(threshold=0.3, min_silence_duration_ms=1000, speech_pad_ms=600) if verbatim else None,
        hotwords=VERBATIM_HINT if verbatim else None,
        word_timestamps=True,
        condition_on_previous_text=False,
    )
    words = []
    status("Transcribiendo…", 0)
    for seg in segments:
        if not any(h in seg.text.lower() for h in HALLUCINATIONS):
            words.extend([w.start, w.end, w.word, round(w.probability, 3)] for w in seg.words or [] if w.word.strip())
        status("Transcribiendo…", min(1.0, seg.end / duration))
    return words


def find_cut(audio, force):
    from faster_whisper.vad import VadOptions, get_speech_timestamps

    vad = VadOptions(threshold=0.35, min_silence_duration_ms=int(CUT_GAP * 1000), speech_pad_ms=100)
    speech = get_speech_timestamps(audio, vad)
    if not speech:
        return len(audio)
    gaps = [(a["end"], b["start"]) for a, b in zip(speech, speech[1:])]
    if len(audio) - speech[-1]["end"] >= 2 * CUT_GAP * RATE:
        gaps.append((speech[-1]["end"], len(audio)))
    for a, b in gaps:
        if (a + b) // 2 >= CHUNK_MIN * RATE:
            return (a + b) // 2
    if not force:
        return None
    if not gaps:
        return len(audio)
    a, b = max(gaps, key=lambda g: g[1] - g[0])
    return (a + b) // 2


def resample(resampler, data, rate):
    import av

    frame = av.AudioFrame.from_ndarray(np.frombuffer(data, np.int16).reshape(1, -1), format="s16", layout="mono")
    frame.sample_rate = rate
    out = [f.to_ndarray().reshape(-1) for f in resampler.resample(frame)]
    return np.concatenate(out).astype(np.float32) / 32768 if out else np.zeros(0, np.float32)


def partial_key(cfg):
    return [cfg["model"], cfg["language"], cfg.get("verbatim", True)]


def load_partial(session_dir, cfg):
    chunks = []
    try:
        with open(os.path.join(session_dir, PARTIAL), encoding="utf-8") as f:
            for line in f:
                try:
                    chunk = json.loads(line)
                except ValueError:
                    break
                if chunk.get("key") != partial_key(cfg):
                    return []
                chunks.append(chunk)
    except OSError:
        pass
    return chunks


def save_chunk(out, cfg, end, words):
    out.write(json.dumps({"key": partial_key(cfg), "end": end, "words": words}, ensure_ascii=False) + "\n")
    out.flush()


def live_transcribe(session_dir, rate, cfg, send, finish):
    import av

    models.ensure(cfg["model"], lambda text, p: send("status", text, p))
    send("status", "Cargando el modelo de transcripción…", None)
    whisper = Whisper(cfg)
    chunks = load_partial(session_dir, cfg)
    pos = chunks[-1]["end"] if chunks else 0
    send("pos", pos / RATE)
    while not os.path.exists(os.path.join(session_dir, PCM)):
        time.sleep(0.5)
    resampler = av.AudioResampler(format="s16", layout="mono", rate=RATE)
    enc = mp3_encoder(rate)
    offset, received = 0, 0
    pending = np.zeros(0, np.float32)
    with (
        open(os.path.join(session_dir, PCM), "rb") as src,
        open(os.path.join(session_dir, MP3), "wb") as mp3,
        open(os.path.join(session_dir, PARTIAL), "w", encoding="utf-8") as out,
    ):
        for chunk in chunks:
            save_chunk(out, cfg, chunk["end"], chunk["words"])
        while True:
            final = finish.is_set()
            src.seek(offset)
            data = src.read(CHUNK * 8)
            data = data[: len(data) // 2 * 2]
            offset += len(data)
            if data:
                mp3.write(enc.encode(data))
                audio = resample(resampler, data, rate)
                skip = max(0, min(len(audio), pos - received))
                received += len(audio)
                pending = np.concatenate([pending, audio[skip:]])
                if final:
                    continue
            elif final:
                mp3.write(enc.flush())
                break
            cut = None
            if data and len(pending) >= CHUNK_MIN * RATE:
                cut = find_cut(pending, len(pending) >= CHUNK_MAX * RATE)
            if cut is None:
                if not data:
                    time.sleep(1)
                continue
            words = whisper.words(pending[:cut], pos / RATE, lambda *_: None)
            pos += cut
            pending = pending[cut:]
            save_chunk(out, cfg, pos, words)
            send("pos", pos / RATE)
        start, lag = pos / RATE, len(pending) / RATE
        total = start + lag or 1
        if len(pending):
            words = whisper.words(pending, start, lambda text, p: send("progress", (start + (p or 0) * lag) / total))
            save_chunk(out, cfg, pos + len(pending), words)
    send("done", whisper.device, lag)


def transcribe_child(session_dir, rate, cfg, queue, finish):
    try:
        if WIN:
            import ctypes

            ctypes.windll.kernel32.SetPriorityClass(ctypes.windll.kernel32.GetCurrentProcess(), 0x4000)
        else:
            os.nice(5)
        live_transcribe(session_dir, rate, cfg, lambda *msg: queue.put(msg), finish)
    except Exception as e:
        traceback.print_exc()
        queue.put(("error", f"{e.__class__.__name__}: {e}"))


class Transcription:
    def __init__(self, session_dir, rate, cfg):
        ctx = multiprocessing.get_context("spawn")
        self.cfg = cfg
        self.queue = ctx.Queue()
        self.finish = ctx.Event()
        self.proc = ctx.Process(target=transcribe_child, args=(session_dir, rate, cfg, self.queue, self.finish), daemon=True)
        self.proc.start()
        self.lock = threading.Lock()
        self.seconds = 0.0
        self.note = "Preparando la transcripción…"
        self.error = None
        self.result = None

    def _handle(self, msg, status, total):
        kind, *rest = msg
        if kind == "pos":
            self.seconds, self.note = rest[0], None
            if status:
                status("Transcribiendo…", min(1.0, rest[0] / total))
        elif kind == "status":
            self.note = rest[0]
            if status:
                status(*rest)
        elif kind == "progress" and status:
            status("Transcribiendo…", rest[0])
        elif kind == "error":
            self.error = rest[0]
        elif kind == "done":
            self.result = rest

    def poll(self):
        if not self.lock.acquire(blocking=False):
            return
        try:
            while self.error is None and self.result is None:
                try:
                    self._handle(self.queue.get_nowait(), None, None)
                except queue.Empty:
                    break
        finally:
            self.lock.release()

    def alive(self):
        self.poll()
        return self.error is None and self.proc.is_alive()

    def wait(self, status, total):
        self.finish.set()
        with self.lock:
            status("Transcribiendo…", min(1.0, self.seconds / total))
            while self.error is None and self.result is None:
                try:
                    self._handle(self.queue.get(timeout=0.5), status, total)
                except queue.Empty:
                    if not self.proc.is_alive():
                        raise RuntimeError("La transcripción se detuvo inesperadamente.")
        if self.error:
            raise RuntimeError(self.error)
        self.proc.join()
        return self.result

    def cancel(self):
        if self.proc.is_alive():
            self.proc.terminate()


def diarize(audio, progress):
    import sherpa_onnx as so

    config = so.OfflineSpeakerDiarizationConfig(
        segmentation=so.OfflineSpeakerSegmentationModelConfig(
            pyannote=so.OfflineSpeakerSegmentationPyannoteModelConfig(model=models.segmentation_path()),
            num_threads=THREADS,
        ),
        embedding=so.SpeakerEmbeddingExtractorConfig(model=models.embedding_path(), num_threads=THREADS),
        clustering=so.FastClusteringConfig(num_clusters=2),
        min_duration_on=0.3,
        min_duration_off=0.5,
    )

    def callback(done, total):
        progress(done / total if total else 0)
        return 0

    result = so.OfflineSpeakerDiarization(config).process(audio, callback=callback).sort_by_start_time()
    return [(s.start, s.end, s.speaker) for s in result]


def diarize_child(wav_path, queue):
    try:
        from faster_whisper import decode_audio

        last = [-1]

        def progress(p):
            if p - last[0] >= 0.01:
                last[0] = p
                queue.put(("progress", p))

        queue.put(("result", diarize(decode_audio(wav_path, sampling_rate=RATE), progress)))
    except Exception as e:
        queue.put(("error", f"{e.__class__.__name__}: {e}"))


class Diarization:
    def __init__(self, wav_path):
        ctx = multiprocessing.get_context("spawn")
        self.queue = ctx.Queue()
        self.proc = ctx.Process(target=diarize_child, args=(wav_path, self.queue), daemon=True)
        self.proc.start()
        self.progress = 0.0

    def wait(self, status):
        while True:
            try:
                kind, value = self.queue.get(timeout=0.5)
            except queue.Empty:
                if not self.proc.is_alive():
                    raise RuntimeError("La identificación de voces se detuvo inesperadamente.")
                status("Identificando voces…", self.progress)
                continue
            if kind == "progress":
                self.progress = value
                status("Identificando voces…", value)
            elif kind == "error":
                raise RuntimeError(value)
            else:
                self.proc.join()
                return value


def detect_silences(audio):
    from faster_whisper.vad import VadOptions, get_speech_timestamps

    speech = get_speech_timestamps(audio, VadOptions(threshold=0.35, min_silence_duration_ms=300, speech_pad_ms=60))
    gaps = []
    for a, b in zip(speech, speech[1:]):
        start, end = a["end"] / RATE, b["start"] / RATE
        if end - start >= MIN_SILENCE:
            gaps.append([round(start, 2), round(end, 2)])
    return gaps


def silences_before_words(meta):
    words, owners = [], []
    for ti, t in enumerate(meta["turns"]):
        for wi, w in enumerate(t["words"]):
            words.append(w)
            owners.append((ti, wi))
    gaps = [(words[k - 1][1] + words[k][0]) / 2 for k in range(1, len(words))]
    found = {}
    for start, end in meta.get("silences", []):
        mid = (start + end) / 2
        i = bisect.bisect_left(gaps, mid)
        near = [j for j in (i - 1, i) if 0 <= j < len(gaps)]
        if not near:
            continue
        j = min(near, key=lambda j: abs(gaps[j] - mid))
        if abs(gaps[j] - mid) <= (end - start) / 2 + 1.0:
            found.setdefault(owners[j + 1], []).append((start, end - start))
    return found


def assign_speakers(words, spans):
    if not spans:
        return [0] * len(words)
    starts = [s[0] for s in spans]
    labels = []
    for ws, we, *_ in words:
        idx = bisect.bisect_right(starts, we)
        best, best_overlap, best_dist = 0, 0.0, float("inf")
        for s, e, spk in spans[max(0, idx - 30) : idx + 1]:
            overlap = min(we, e) - max(ws, s)
            dist = max(s - we, ws - e, 0)
            if overlap > best_overlap or (best_overlap == 0 and overlap <= 0 and dist < best_dist):
                best, best_overlap, best_dist = spk, max(overlap, 0.0), dist
        labels.append(best)
    for _ in range(2):
        runs, i = [], 0
        while i < len(labels):
            j = i
            while j < len(labels) and labels[j] == labels[i]:
                j += 1
            runs.append((i, j))
            i = j
        for k in range(1, len(runs) - 1):
            a, b = runs[k]
            prev, nxt = labels[runs[k - 1][0]], labels[runs[k + 1][0]]
            if prev == nxt and (b - a <= 2 or words[b - 1][1] - words[a][0] < 0.6):
                labels[a:b] = [prev] * (b - a)
    return labels


def build_turns(words, labels):
    turns = []
    for word, spk in zip(words, labels):
        if turns:
            last = turns[-1]
            sentence_end = last["words"][-1][2].rstrip().endswith((".", "?", "!", "…"))
            if last["speaker"] == spk and not (word[0] - last["end"] > 5 and sentence_end):
                last["words"].append(word)
                last["end"] = word[1]
                continue
        turns.append({"start": word[0], "end": word[1], "speaker": spk, "words": [word]})
    return turns


def plain(turn):
    return "".join(w[2] for w in turn["words"]).strip()


def render(turn, pauses, pause_min, mark_doubtful):
    out = []
    for wi, (start, end, text, prob) in enumerate(turn["words"]):
        if wi:
            out.extend(f" (pausa {secs(d)})" for _, d in pauses.get(wi, []) if d >= pause_min)
        if mark_doubtful and prob < DOUBTFUL:
            lead, core, tail = WORD_EDGES.match(text).groups()
            text = f"{lead}{core}[?]{tail}"
        out.append(text)
    return "".join(out).strip()


def first_speaker(turns):
    for t in turns:
        if t["end"] - t["start"] >= 3:
            return t["speaker"]
    return turns[0]["speaker"] if turns else 0


def role_of(meta, speaker):
    role = 0 if speaker == meta["first_speaker"] else 1
    return 1 - role if meta.get("swap") else role


def samples(meta):
    found = {}
    for t in meta["turns"]:
        role, text = role_of(meta, t["speaker"]), plain(t)
        if role not in found and len(text.split()) >= 6:
            found[role] = text if len(text) <= 140 else text[:140].rsplit(" ", 1)[0] + "…"
    return found


def entries(meta, cfg):
    pause_min, doubtful = cfg.get("pause_min", 1.5), cfg.get("mark_doubtful", True)
    silences = silences_before_words(meta)
    out = []
    for ti, t in enumerate(meta["turns"]):
        for start, d in silences.get((ti, 0), []):
            if d >= pause_min:
                out.append({"start": start, "role": None, "text": f"(silencio {secs(d)})"})
        pauses = {wi: v for (i, wi), v in silences.items() if i == ti}
        out.append({"start": t["start"], "role": role_of(meta, t["speaker"]), "text": render(t, pauses, pause_min, doubtful)})
    return out


def write_txt(session_dir, cfg):
    meta = read_meta(session_dir)
    roles, pause_min, doubtful = cfg["roles"], cfg.get("pause_min", 1.5), cfg.get("mark_doubtful", True)
    started = datetime.fromisoformat(meta["started"])
    lines = [
        "Colloquia · Transcripción",
        f"Sesión: {meta['name'] or '—'}",
        f"Fecha: {started.strftime('%d/%m/%Y %H:%M')}",
        f"Duración: {hms(meta['duration'])}",
        f"Modelo: {meta['model']} ({meta['device']})",
        "",
        "Notación:",
        f"  (pausa 2,3 s)          silencio de {secs(pause_min)} o más dentro de una intervención",
        f"  [00:01:02] (silencio)  silencio de {secs(pause_min)} o más entre intervenciones",
    ]
    if doubtful:
        lines.append("  palabra[?]             reconocida con poca seguridad: conviene escucharla en el MP3")
    lines += ["  Las duraciones son aproximadas (±0,5 s).", "", ""]
    for e in entries(meta, cfg):
        who = "" if e["role"] is None else f"{roles[e['role']]}: "
        lines += [f"[{hms(e['start'])}] {who}{e['text']}", ""]
    with open(os.path.join(session_dir, TXT), "w", encoding="utf-8") as f:
        f.write("\n".join(lines))


def swap_roles(session_dir, cfg):
    meta = read_meta(session_dir)
    meta["swap"] = not meta.get("swap", False)
    write_meta(session_dir, meta)
    write_txt(session_dir, cfg)
    return meta


def process(session_dir, cfg, status, live=None):
    from faster_whisper import decode_audio

    meta = read_meta(session_dir)
    meta["state"] = "processing"
    write_meta(session_dir, meta)
    if live is None or not live.alive():
        if live is not None:
            print(f"La transcripción durante la grabación falló ({live.error}); se repite.")
        live = Transcription(session_dir, meta["rate"], cfg)
    try:
        models.ensure(cfg["model"], status)
        write_wav(session_dir, meta["rate"], status)
        meta["duration"] = os.path.getsize(os.path.join(session_dir, PCM)) / 2 / meta["rate"]
        diarization = Diarization(os.path.join(session_dir, WAV))
        try:
            device, lag = live.wait(status, meta["duration"])
            words = [w for chunk in load_partial(session_dir, live.cfg) for w in chunk["words"]]
            status("Generando texto…", None)
            audio = decode_audio(os.path.join(session_dir, WAV), sampling_rate=RATE)
            silences = detect_silences(audio)
            del audio
            spans = diarization.wait(status)
        finally:
            if diarization.proc.is_alive():
                diarization.proc.terminate()
    finally:
        live.cancel()

    status("Generando texto…", None)
    turns = build_turns(words, assign_speakers(words, spans))
    meta.update(
        turns=turns,
        silences=silences,
        first_speaker=first_speaker(turns),
        swap=False,
        model=live.cfg["model"],
        device=device,
        lag=round(lag),
    )
    write_meta(session_dir, meta)
    write_txt(session_dir, cfg)

    os.remove(os.path.join(session_dir, PCM))
    os.remove(os.path.join(session_dir, PARTIAL))
    if not cfg["keep_wav"]:
        os.remove(os.path.join(session_dir, WAV))
    meta["state"] = "done"
    write_meta(session_dir, meta)
    return meta


def import_audio(path, folder):
    from faster_whisper import decode_audio

    from recorder import new_session_dir

    session_dir = new_session_dir(folder, os.path.splitext(os.path.basename(path))[0])
    audio = decode_audio(path, sampling_rate=RATE)
    with open(os.path.join(session_dir, PCM), "wb") as f:
        f.write((np.clip(audio, -1, 1) * 32767).astype(np.int16).tobytes())
    write_meta(
        session_dir,
        {"state": "recorded", "name": os.path.basename(path), "rate": RATE, "started": datetime.now().isoformat(timespec="seconds")},
    )
    return session_dir


def main(argv):
    import time

    from config import load_config

    if not argv or argv[0] in ("-h", "--help"):
        print(f"Uso: {os.path.basename(sys.argv[0])} <audio> [carpeta_salida]")
        return 0 if argv else 1
    cfg = load_config()
    out = argv[1] if len(argv) > 1 else cfg["folder"]
    t0 = time.time()
    last = [None]

    def show(text, p):
        line = f"{text} {p * 100:5.1f}%" if p is not None else text
        if line != last[0]:
            last[0] = line
            print(f"\r[{time.time() - t0:6.0f}s] {line:<70}", end="", flush=True)

    d = import_audio(argv[0], out)
    process(d, cfg, show)
    print(f"\nListo en {time.time() - t0:.0f} s → {d}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
