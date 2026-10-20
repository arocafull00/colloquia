import json
import os
import re
import subprocess
import tempfile
import wave
from collections import namedtuple

import numpy as np

Word = namedtuple("Word", "start end word probability")
Segment = namedtuple("Segment", "text end words")

RATE = 16000
PROMPT_TOKENS = 38
PROGRESS = re.compile(r"progress =\s*(\d+)%")


class Model:
    def __init__(self, cli, model, threads):
        self.cli, self.model, self.threads = cli, model, threads
        self.backend = None

    def transcribe(self, audio, language=None, hotwords=None, vad_filter=False, vad_parameters=None, beam_size=5, **_):
        return self._run(audio, language, hotwords, vad_filter, vad_parameters, beam_size), None

    def _run(self, audio, language, hotwords, vad_filter, vad_parameters, beam_size):
        from faster_whisper.vad import SpeechTimestampsMap, VadOptions, collect_chunks, get_speech_timestamps

        duration = len(audio) / RATE or 1
        ts_map = None
        if vad_filter:
            chunks = get_speech_timestamps(audio, VadOptions(**(vad_parameters or {})))
            if not chunks:
                return
            audio = np.concatenate(collect_chunks(audio, chunks)[0])
            ts_map = SpeechTimestampsMap(chunks, RATE)
        with tempfile.TemporaryDirectory(prefix="colloquia-") as tmp:
            wav, out = os.path.join(tmp, "audio.wav"), os.path.join(tmp, "out")
            with wave.open(wav, "wb") as f:
                f.setnchannels(1)
                f.setsampwidth(2)
                f.setframerate(RATE)
                f.writeframes((np.clip(audio, -1, 1) * 32767).astype(np.int16).tobytes())
            cmd = [self.cli, "-m", self.model, "-f", wav, "-of", out, "-ojf", "-pp", "-t", str(self.threads)]
            cmd += ["-bs", str(beam_size), "-l", language or "auto", "-dtw", dtw_preset(self.model), "-nfa"]
            if hotwords:
                cmd += ["--prompt", hotwords, "--carry-initial-prompt", "-mc", str(PROMPT_TOKENS + 1)]
            else:
                cmd += ["-mc", "0"]
            proc = subprocess.Popen(
                cmd,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                errors="replace",
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            log = []
            for line in proc.stderr:
                log.append(line)
                if "using " in line and " backend" in line:
                    self.backend = line.split("using ", 1)[1].split(" backend")[0]
                if m := PROGRESS.search(line):
                    yield Segment("", int(m.group(1)) / 100 * duration, [])
            if proc.wait():
                raise RuntimeError("whisper.cpp falló:\n" + "".join(log[-20:]))
            with open(out + ".json", "rb") as f:
                result = json.loads(f.read().decode("utf-8", "surrogateescape"))
        for seg in result["transcription"]:
            words = words_of(seg)
            if ts_map:
                words = [restore(ts_map, w) for w in words]
            yield Segment(seg["text"], words[-1].end if words else duration, words)


def restore(ts_map, w):
    i = ts_map.get_chunk_index((w.start + w.end) / 2)
    return w._replace(start=ts_map.get_original_time(w.start, i), end=ts_map.get_original_time(w.end, i))


def words_of(seg):
    words, prev = [], seg["offsets"]["from"] / 1000
    for t in seg["tokens"]:
        if t["text"].startswith("[_"):
            continue
        end = t["t_dtw"] / 100 if t["t_dtw"] >= 0 else t["offsets"]["to"] / 1000
        if t["text"].startswith(" ") or not words:
            words.append([prev, end, t["text"].encode("utf-8", "surrogateescape"), [t["p"]]])
        else:
            words[-1][1] = end
            words[-1][2] += t["text"].encode("utf-8", "surrogateescape")
            words[-1][3].append(t["p"])
        prev = end
    return [Word(s, e, w.decode("utf-8", "replace"), sum(p) / len(p)) for s, e, w, p in words]


def dtw_preset(model):
    name = os.path.basename(model)[5:-4]
    for suffix in ("-q5_0", "-q5_1", "-q8_0"):
        name = name.removesuffix(suffix)
    return name.replace("-", ".")
