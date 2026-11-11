import math
import unicodedata

import numpy as np

from whisper_cpp import Segment, Word

RATE = 16000
MAX_PIECE = 20.0
MIN_TOKEN = 0.08


class Model:
    def __init__(self, recognizer, kind):
        self.recognizer, self.kind = recognizer, kind

    @classmethod
    def transducer(cls, d, threads):
        import sherpa_onnx as so

        rec = so.OfflineRecognizer.from_transducer(
            encoder=f"{d}/encoder.int8.onnx",
            decoder=f"{d}/decoder.int8.onnx",
            joiner=f"{d}/joiner.int8.onnx",
            tokens=f"{d}/tokens.txt",
            num_threads=threads,
            model_type="nemo_transducer",
        )
        return cls(rec, "bpe")

    @classmethod
    def ctc(cls, d, threads):
        import sherpa_onnx as so

        rec = so.OfflineRecognizer.from_omnilingual_asr_ctc(model=f"{d}/model.int8.onnx", tokens=f"{d}/tokens.txt", num_threads=threads)
        return cls(rec, "char")

    def transcribe(self, audio, vad_filter=True, vad_parameters=None, **_):
        return self._run(audio, vad_filter, vad_parameters), None

    def _run(self, audio, vad_filter, vad_parameters):
        duration = len(audio) / RATE or 1
        for start, end in pieces(audio, vad_filter, vad_parameters):
            words = self.decode(audio[start:end], start / RATE)
            yield Segment("".join(w.word for w in words), end / RATE if end < len(audio) else duration, words)

    def decode(self, audio, offset=0.0):
        stream = self.recognizer.create_stream()
        stream.accept_waveform(RATE, np.ascontiguousarray(audio, dtype=np.float32))
        self.recognizer.decode_stream(stream)
        r = stream.result
        return to_words(r.tokens, r.timestamps, list(r.durations or []), list(r.ys_log_probs or []), self.kind, offset, len(audio) / RATE)


def pieces(audio, vad_filter=True, vad_parameters=None):
    if not vad_filter:
        step = int(MAX_PIECE * RATE)
        return [(i, min(len(audio), i + step)) for i in range(0, len(audio), step)]
    from faster_whisper.vad import VadOptions, get_speech_timestamps

    opts = VadOptions(**{**(vad_parameters or {}), "max_speech_duration_s": MAX_PIECE})
    out = []
    for c in get_speech_timestamps(audio, opts):
        if out and c["end"] - out[-1][0] <= MAX_PIECE * RATE:
            out[-1][1] = c["end"]
        else:
            out.append([c["start"], c["end"]])
    return [tuple(p) for p in out]


def is_punct(text):
    return bool(text) and all(unicodedata.category(c).startswith("P") for c in text)


def to_words(tokens, times, durations, logprobs, kind, offset, length):
    words = []
    for i, tok in enumerate(tokens):
        start = times[i] if i < len(times) else 0.0
        end = start + (durations[i] if i < len(durations) and durations[i] > 0 else MIN_TOKEN)
        prob = math.exp(logprobs[i]) if i < len(logprobs) else 1.0
        if kind == "bpe":
            new = tok.startswith(("▁", " "))
            text = tok.replace("▁", "").strip()
        else:
            new = tok == " " or not words
            text = "" if tok == " " else tok
            if tok == " ":
                words.append(None)
                continue
        if not text:
            continue
        if words and words[-1] is None:
            words.pop()
            new = True
        if words and (not new or is_punct(text)):
            w = words[-1]
            w[1], w[2] = max(w[1], end), w[2] + text
            w[3].append(prob)
        else:
            words.append([start, end, text, [prob]])
    words = [w for w in words if w]
    for a, b in zip(words, words[1:]):
        a[1] = min(a[1], b[0])
    return [Word(round(offset + s, 3), round(offset + min(e, length), 3), " " + t, sum(p) / len(p)) for s, e, t, p in words]
