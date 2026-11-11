"""Compara modelos de transcripción con audios grabados leyendo tools/guion-prueba.md."""

import argparse
import ctypes
import glob
import multiprocessing
import os
import re
import sys
import time
import unicodedata

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

GUION = os.path.join(ROOT, "tools", "guion-prueba.md")
AUDIO = (".wav", ".mp3", ".m4a", ".ogg", ".flac", ".aac", ".opus", ".webm")
ENGINES = ["small", "large-v3-turbo", "parakeet-v3", "literal"]
SIMILARITIES = [0.5, 0.6, 0.7]
PROBS = [1.01, 0.95, 0.85]


def script():
    said, pairs = [], []
    with open(GUION, encoding="utf-8") as f:
        for line in f:
            m = re.match(r"\s*\d+\.\s+(.*)", line)
            if not m:
                continue
            for word in re.split(r"\s+", m.group(1)):
                pair = re.search(r"\{([^|}]+)\|([^}]+)\}", word)
                if pair:
                    said.append(pair.group(1))
                    if pair.group(1) != pair.group(2):
                        pairs.append((pair.group(1), pair.group(2)))
                else:
                    said.append(word)
    return said, pairs


def norm(text):
    text = unicodedata.normalize("NFD", text.lower().replace("ñ", "\0"))
    text = "".join(c for c in text if unicodedata.category(c) != "Mn").replace("\0", "ñ")
    return re.findall(r"[a-zñ]+", text)


def wer(ref, hyp):
    prev = list(range(len(hyp) + 1))
    for i, r in enumerate(ref, 1):
        cur = [i] + [0] * len(hyp)
        for j, h in enumerate(hyp, 1):
            cur[j] = min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (r != h))
        prev = cur
    return prev[-1] / max(1, len(ref))


def peak_mb():
    if sys.platform == "win32":

        class Counters(ctypes.Structure):
            _fields_ = [("cb", ctypes.c_ulong), ("faults", ctypes.c_ulong)] + [(f"f{i}", ctypes.c_size_t) for i in range(8)]

        c = Counters(cb=ctypes.sizeof(Counters))
        k32 = ctypes.windll.kernel32
        k32.GetCurrentProcess.restype = ctypes.c_void_p
        k32.K32GetProcessMemoryInfo.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_ulong]
        k32.K32GetProcessMemoryInfo(k32.GetCurrentProcess(), ctypes.byref(c), c.cb)
        return c.f0 / 2**20
    import resource

    rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return rss / 2**20 if sys.platform == "darwin" else rss / 1024


def run(engine, path, threads, out):
    import numpy as np
    from faster_whisper import decode_audio

    import models
    import pipeline
    import sherpa_asr

    audio = decode_audio(path, sampling_rate=16000)
    cfg = {"model": engine, "language": "es", "verbatim": True, "literal": False}
    if engine == "literal":
        model = sherpa_asr.Model.ctc(models.sherpa_path("literal"), threads)
    elif models.is_sherpa(engine):
        model = sherpa_asr.Model.transducer(models.sherpa_path(engine), threads)
    else:
        from faster_whisper import WhisperModel

        model = WhisperModel(models.whisper_path(engine), device="cpu", compute_type="int8", cpu_threads=threads)
    list(model.transcribe(np.zeros(16000, np.float32), language="es")[0])
    started = time.monotonic()
    words = pipeline.run_whisper(model, audio, cfg, lambda *_: None)
    elapsed = time.monotonic() - started
    out.put((words, elapsed / (len(audio) / 16000), peak_mb()))


def measure(engine, path, threads):
    ctx = multiprocessing.get_context("spawn")
    q = ctx.Queue()
    p = ctx.Process(target=run, args=(engine, path, threads, q))
    p.start()
    result = q.get()
    p.join()
    return result


def literal_scores(main, said, pairs, ref):
    import literal

    from whisper_cpp import Word

    targets = {literal.phonetic(t): literal.phonetic(s) for s, t in pairs}
    fine = {literal.phonetic(w) for w in ref} - set(targets.values())
    said_words = [Word(s, e, w, p) for s, e, w, p in said]
    rows = []
    for sim in SIMILARITIES:
        for prob in PROBS:
            words = literal.annotate([list(w) for w in main], said_words, sim, prob)
            hits = false = 0
            for w in words:
                if len(w) < 5:
                    continue
                key, got = literal.phonetic(w[2]), literal.phonetic(w[4].replace(" ", ""))
                if key in targets and got == targets[key]:
                    hits += 1
                elif key in fine:
                    false += 1
            corrected = sum(1 for w in main if literal.phonetic(w[2]) in targets)
            rows.append((sim, prob, hits, corrected, false))
    return rows


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("folder", nargs="?", default=os.path.join(ROOT, "tools", "audio"))
    parser.add_argument("--engines", default=",".join(ENGINES))
    parser.add_argument("--threads", default=f"2,{max(1, min(8, (os.cpu_count() or 2) // 2))}")
    args = parser.parse_args()

    import models

    files = sorted(f for f in glob.glob(os.path.join(args.folder, "*")) if f.lower().endswith(AUDIO))
    if not files:
        print(f"No hay audios en {args.folder}. Graba el guion de {GUION} y guárdalo ahí.")
        return 1
    engines = args.engines.split(",")
    threads = [int(t) for t in args.threads.split(",")]
    for e in engines:
        models.ensure("small" if e == "literal" else e, lambda t, p: print(f"\r{t} {(p or 0) * 100:3.0f} %", end=""), cpp=False, literal=e == "literal", transcriber=e != "literal")
    print()

    ref, pairs = script()
    ref_n = [w for r in ref for w in norm(r)]
    print(f"Guion: {len(ref_n)} palabras, {len(pairs)} pseudopalabras\n")
    for path in files:
        print(f"## {os.path.basename(path)}\n")
        print("| Modelo | Hilos | RTF | RAM pico | WER literal | Pseudopalabras conservadas | Corregidas |")
        print("|---|---|---|---|---|---|---|")
        outputs = {}
        for e in engines:
            for t in threads:
                words, rtf, ram = measure(e, path, t)
                outputs[e] = words
                hyp = [w for s, _, text, _ in words for w in norm(text)]
                kept = sum(1 for s, _ in pairs if norm(s)[0] in hyp)
                fixed = sum(1 for s, t in pairs if norm(t)[0] in hyp and norm(s)[0] not in hyp)
                print(f"| {e} | {t} | {rtf:.3f} | {ram:.0f} MB | {wer(ref_n, hyp) * 100:.1f} % | {kept}/{len(pairs)} | {fixed} |")
        if "literal" in outputs:
            for e in engines:
                if e == "literal":
                    continue
                print(f"\nPase literal sobre {e} (aciertos / palabras corregidas por el modelo; falsos = anotaciones en palabras bien dichas)\n")
                print("| Similitud mín. | Prob. máx. | Aciertos | Falsos |")
                print("|---|---|---|---|")
                for sim, prob, hits, corrected, false in literal_scores(outputs[e], outputs["literal"], pairs, ref):
                    print(f"| {sim} | {prob} | {hits}/{corrected} | {false} |")
        print("\nTranscripciones (último hilo medido):\n")
        for e in engines:
            print(f"- **{e}**: {''.join(w[2] for w in outputs[e]).strip()}")
        print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
