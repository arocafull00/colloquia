import re
import unicodedata
from difflib import SequenceMatcher

MIN_SIMILARITY = 0.5
MAX_PROB = 1.01
WINDOW_GAP = 0.5
SLACK = 0.3
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


def windows(said):
    out = []
    for h in said:
        if out and h.start - out[-1][-1].end < WINDOW_GAP:
            out[-1].append(h)
        else:
            out.append([h])
    return out


def annotate(words, said, min_similarity=None, max_prob=None):
    for window in windows(said):
        lo, hi = window[0].start - SLACK, window[-1].end + SLACK
        idx = [i for i, w in enumerate(words) if lo <= (w[0] + w[1]) / 2 <= hi]
        if idx:
            _annotate(words, idx, window, min_similarity, max_prob)
    return words


def _annotate(words, idx, said, min_similarity, max_prob):
    min_similarity = MIN_SIMILARITY if min_similarity is None else min_similarity
    max_prob = MAX_PROB if max_prob is None else max_prob
    a = [phonetic(words[i][2]) for i in idx]
    b = [phonetic(h.word) for h in said]
    for op, i1, i2, j1, j2 in SequenceMatcher(None, a, b, autojunk=False).get_opcodes():
        if op != "replace":
            continue
        groups = {k: [] for k in range(i1, i2)}
        for j in range(j1, j2):
            mid = (said[j].start + said[j].end) / 2
            k = min(range(i1, i2), key=lambda k: max(words[idx[k]][0] - mid, mid - words[idx[k]][1], 0))
            w = words[idx[k]]
            if w[0] - SLACK <= mid <= w[1] + SLACK:
                groups[k].append(said[j])
        for k, hs in groups.items():
            i = idx[k]
            if not hs or not a[k] or words[i][3] >= max_prob or any(c.isdigit() for c in words[i][2]):
                continue
            got = "".join(phonetic(h.word) for h in hs)
            if got != a[k] and SequenceMatcher(None, a[k], got).ratio() >= min_similarity:
                text = " ".join(filter(None, (clean(h.word) for h in hs)))
                if text:
                    words[i] = [*words[i][:4], text]
