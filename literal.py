import re
import unicodedata
from difflib import SequenceMatcher

MIN_SIMILARITY = 0.5
RULES = [
    (r"ch", "ʧ"),
    (r"h", ""),
    (r"qu(?=[ei])", "k"),
    (r"gu(?=[ei])", "g"),
    (r"g(?=[ei])", "j"),
    (r"c(?=[ei])", "s"),
    (r"[cq]", "k"),
    (r"z", "s"),
    (r"v", "b"),
    (r"ll", "y"),
    (r"y$", "i"),
    (r"x", "ks"),
    (r"^rr|(?<=[nls])rr", "r"),
    (r"([^r])\1", r"\1"),
]


def phonetic(word):
    w = "".join(
        c for c in unicodedata.normalize("NFD", word.lower().replace("ñ", "\0")) if unicodedata.category(c) != "Mn"
    ).replace("\0", "ñ")
    w = re.sub(r"[^a-zñ]", "", w)
    for pattern, repl in RULES:
        w = re.sub(pattern, repl, w)
    return w


def clean(text):
    return re.sub(r"[^\w'-]", "", text.strip().lower())


def heard(model, audio, progress=None):
    segments, _ = model.transcribe(audio, vad_filter=True)
    duration = len(audio) / 16000 or 1
    out = []
    for seg in segments:
        out.extend(seg.words)
        if progress:
            progress(min(1.0, seg.end / duration))
    return out


def annotate(words, said):
    a = [phonetic(w[2]) for w in words]
    b = [phonetic(h.word) for h in said]
    for op, i1, i2, j1, j2 in SequenceMatcher(None, a, b, autojunk=False).get_opcodes():
        if op != "replace":
            continue
        groups = {i: [] for i in range(i1, i2)}
        for j in range(j1, j2):
            mid = (said[j].start + said[j].end) / 2
            i = min(range(i1, i2), key=lambda i: max(words[i][0] - mid, mid - words[i][1], 0))
            groups[i].append(said[j])
        for i, hs in groups.items():
            if not hs or not a[i] or any(c.isdigit() for c in words[i][2]):
                continue
            got = "".join(phonetic(h.word) for h in hs)
            if got != a[i] and SequenceMatcher(None, a[i], got).ratio() >= MIN_SIMILARITY:
                text = " ".join(filter(None, (clean(h.word) for h in hs)))
                if text:
                    words[i] = [*words[i][:4], text]
    return words
