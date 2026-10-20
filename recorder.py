import json
import os
import queue
import re
import threading
import time
from datetime import datetime

import numpy as np
import sounddevice as sd

PCM = ".grabacion.pcm"
META = ".colloquia.json"
PREFERRED_RATE = 48000


def input_devices():
    host = sd.default.hostapi
    return [d["name"] for d in sd.query_devices() if d["hostapi"] == host and d["max_input_channels"] > 0]


def find_device(name):
    if not name:
        return None
    for i, d in enumerate(sd.query_devices()):
        if d["name"] == name and d["max_input_channels"] > 0:
            return i
    return None


def pick_rate(device):
    try:
        sd.check_input_settings(device=device, channels=1, samplerate=PREFERRED_RATE)
        return PREFERRED_RATE
    except Exception:
        return int(sd.query_devices(device, "input")["default_samplerate"])


def read_meta(session_dir):
    with open(os.path.join(session_dir, META), encoding="utf-8") as f:
        return json.load(f)


def write_meta(session_dir, meta):
    tmp = os.path.join(session_dir, META + ".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=1)
    os.replace(tmp, os.path.join(session_dir, META))


def new_session_dir(folder, name):
    stamp = datetime.now().strftime("%Y-%m-%d_%H-%M")
    slug = re.sub(r"[^\w\- ]", "", name).strip().replace(" ", "-")
    base = os.path.join(folder, f"{stamp}_{slug}" if slug else stamp)
    path, n = base, 2
    while os.path.exists(path):
        path, n = f"{base}_{n}", n + 1
    os.makedirs(path)
    return path


def interrupted_sessions(folder):
    found = []
    if not os.path.isdir(folder):
        return found
    for entry in sorted(os.listdir(folder)):
        d = os.path.join(folder, entry)
        try:
            meta = read_meta(d)
        except (OSError, ValueError):
            continue
        if meta.get("state") != "done" and os.path.exists(os.path.join(d, PCM)):
            found.append(d)
    return found


class Recorder:
    def __init__(self):
        self.stream = None
        self.device_name = None
        self.rate = PREFERRED_RATE
        self.level = 0.0
        self.recording = False
        self.paused = False
        self.frames = 0
        self.session_dir = None
        self.error = None
        self.queue = queue.Queue()
        self.writer = None

    def open(self, device_name):
        if self.stream is not None and device_name == self.device_name:
            return
        self.close()
        device = find_device(device_name)
        try:
            self.rate = pick_rate(device)
            self.stream = sd.InputStream(samplerate=self.rate, channels=1, dtype="int16", device=device, callback=self.callback)
        except Exception:
            device = None
            self.rate = pick_rate(None)
            self.stream = sd.InputStream(samplerate=self.rate, channels=1, dtype="int16", callback=self.callback)
        self.stream.start()
        self.device_name = device_name

    def close(self):
        if self.stream is not None:
            self.stream.close()
            self.stream = None

    def callback(self, indata, frames, t, status):
        samples = indata[:, 0]
        self.level = float(np.sqrt(np.mean((samples.astype(np.float32) / 32768) ** 2)))
        if self.recording and not self.paused:
            self.queue.put(samples.tobytes())
            self.frames += frames

    @property
    def seconds(self):
        return self.frames / self.rate

    def start(self, folder, name):
        os.makedirs(folder, exist_ok=True)
        self.session_dir = new_session_dir(folder, name)
        write_meta(
            self.session_dir,
            {"state": "recording", "name": name, "rate": self.rate, "started": datetime.now().isoformat(timespec="seconds")},
        )
        self.frames = 0
        self.paused = False
        self.error = None
        self.queue = queue.Queue()
        self.writer = threading.Thread(target=self.write_loop, args=(os.path.join(self.session_dir, PCM),), daemon=True)
        self.writer.start()
        self.recording = True
        return self.session_dir

    def write_loop(self, path):
        last_sync = time.monotonic()
        try:
            with open(path, "ab") as f:
                while True:
                    data = self.queue.get()
                    if data is None:
                        break
                    f.write(data)
                    if time.monotonic() - last_sync > 5:
                        f.flush()
                        os.fsync(f.fileno())
                        last_sync = time.monotonic()
                f.flush()
                os.fsync(f.fileno())
        except OSError as e:
            self.error = str(e)

    def stop(self):
        self.recording = False
        self.queue.put(None)
        if self.writer:
            self.writer.join()
            self.writer = None
        meta = read_meta(self.session_dir)
        meta.update(state="recorded", duration=round(self.seconds, 2))
        write_meta(self.session_dir, meta)
        return self.session_dir
