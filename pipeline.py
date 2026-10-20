import bisect
import gc
import glob
import multiprocessing
import os
import queue
import re
import sys
import wave
from datetime import datetime

PACKAGES = getattr(sys, "_MEIPASS", os.path.join(sys.prefix, "Lib", "site-packages"))
for d in glob.glob(os.path.join(PACKAGES, "nvidia", "*", "bin")):
    os.add_dll_directory(d)
    os.environ["PATH"] = d + os.pathsep + os.environ["PATH"]

import lameenc
import numpy as np

import models
from config import MAC
from recorder import PCM, read_meta, write_meta

RATE = 16000
MP3 = "sesion.mp3"
WAV = "sesion.wav"
TXT = "transcripcion.txt"
CHUNK = 1 << 20
THREADS = max(1, min(8, (os.cpu_count() or 2) // 2))
DOUBTFUL = 0.45
MIN_SILENCE = 0.8
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

    path = models.whisper_path(name) or name
    if not MAC:
        try:
            model = WhisperModel(path, device="cuda", compute_type="float16")
            list(model.transcribe(np.zeros(RATE, np.float32), language="es")[0])
            return model, "GPU"
        except Exception as e:
            print(f"GPU no disponible ({e}); usando CPU.")
    return WhisperModel(path, device="cpu", compute_type="int8"), "CPU"


def pcm_to_outputs(session_dir, rate, status):
    pcm = os.path.join(session_dir, PCM)
    total = os.path.getsize(pcm) or 1
    enc = lameenc.Encoder()
    enc.set_bit_rate(64)
    enc.set_in_sample_rate(rate)
    enc.set_channels(1)
    enc.set_quality(2)
    done = 0
    with open(pcm, "rb") as src, open(os.path.join(session_dir, MP3), "wb") as mp3, wave.open(
        os.path.join(session_dir, WAV), "wb"
    ) as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(rate)
        while chunk := src.read(CHUNK):
            chunk = chunk[: len(chunk) // 2 * 2]
            mp3.write(enc.encode(chunk))
            wav.writeframes(chunk)
            done += len(chunk)
            status("Guardando MP3…", done / total)
        mp3.write(enc.flush())


def transcribe(audio, cfg, status):
    model, device = load_whisper(cfg["model"])
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
    del model
    gc.collect()
    return words, device


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
    silences = silences_before_words(meta)
    for ti, t in enumerate(meta["turns"]):
        for start, d in silences.get((ti, 0), []):
            if d >= pause_min:
                lines += [f"[{hms(start)}] (silencio {secs(d)})", ""]
        pauses = {wi: v for (i, wi), v in silences.items() if i == ti}
        lines.append(f"[{hms(t['start'])}] {roles[role_of(meta, t['speaker'])]}: {render(t, pauses, pause_min, doubtful)}")
        lines.append("")
    with open(os.path.join(session_dir, TXT), "w", encoding="utf-8") as f:
        f.write("\n".join(lines))


def swap_roles(session_dir, cfg):
    meta = read_meta(session_dir)
    meta["swap"] = not meta.get("swap", False)
    write_meta(session_dir, meta)
    write_txt(session_dir, cfg)
    return meta


def process(session_dir, cfg, status):
    from faster_whisper import decode_audio

    meta = read_meta(session_dir)
    meta["state"] = "processing"
    write_meta(session_dir, meta)
    models.ensure(cfg["model"], status)

    pcm_to_outputs(session_dir, meta["rate"], status)
    meta["duration"] = os.path.getsize(os.path.join(session_dir, PCM)) / 2 / meta["rate"]
    status("Preparando audio…", None)
    diarization = Diarization(os.path.join(session_dir, WAV))
    try:
        audio = decode_audio(os.path.join(session_dir, WAV), sampling_rate=RATE)
        words, device = transcribe(audio, cfg, status)
        status("Generando texto…", None)
        silences = detect_silences(audio)
        del audio
        spans = diarization.wait(status)
    finally:
        if diarization.proc.is_alive():
            diarization.proc.terminate()

    status("Generando texto…", None)
    turns = build_turns(words, assign_speakers(words, spans))
    meta.update(
        turns=turns, silences=silences, first_speaker=first_speaker(turns), swap=False, model=cfg["model"], device=device
    )
    write_meta(session_dir, meta)
    write_txt(session_dir, cfg)

    os.remove(os.path.join(session_dir, PCM))
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
