import tempfile
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import numpy as np

import pipeline as p


class ImportTests(unittest.TestCase):
    def test_ranges_cover_every_sample_and_prefer_pauses(self):
        pcm = np.zeros(260 * p.RATE + 1, np.int16)
        with patch.object(p, "speech_regions", return_value=[(0, 4), (6, 10)]):
            ranges = list(p.import_ranges(pcm, 0))
        self.assertEqual([a for a, _ in ranges], [s * p.RATE for s in (0, 60, 120, 180)])
        self.assertEqual([b for _, b in ranges], [a for a, _ in ranges[1:]] + [len(pcm)])
        self.assertEqual(list(p.import_ranges(pcm[:90 * p.RATE], 0)), [(0, 90 * p.RATE)])

    def test_workers_respect_length_memory_and_cpu(self):
        cfg = {"language": "es", "literal": True}
        memory = SimpleNamespace(available=32 << 30)
        with patch.object(p, "THREADS", 8), patch.object(p.psutil, "virtual_memory", return_value=memory):
            self.assertEqual([p.import_workers(n, p.models.FAST, cfg) for n in (1, 3, 20)], [1, 2, 4])
            memory.available = 2 << 30
            self.assertEqual(p.import_workers(20, p.models.FAST, cfg), 1)
            memory.available = 32 << 30
            with patch.object(p, "THREADS", 2):
                self.assertEqual(p.import_workers(20, p.models.FAST, cfg), 1)

    def test_cuda_parallelism_uses_free_video_memory(self):
        cfg = {"language": "es", "literal": False}
        with (
            patch.object(p, "WIN", True), patch.object(p, "THREADS", 8),
            patch.object(p.models, "uses_whisper_cpp", return_value=False),
            patch.object(p.models, "cuda_ready", return_value=True),
            patch.object(p.psutil, "virtual_memory", return_value=SimpleNamespace(available=32 << 30)),
            patch.object(p.subprocess, "check_output") as smi,
        ):
            for free, expected in [(3500, 1), (7800, 2), (16000, 4)]:
                smi.return_value = str(free)
                self.assertEqual(p.import_workers(10, "large-v3-turbo", cfg), expected)
            smi.side_effect = FileNotFoundError
            self.assertEqual(p.import_workers(10, "large-v3-turbo", cfg), 1)

    def test_ordered_checkpoints_and_retry_after_parallel_failure(self):
        cfg = {"language": "es", "literal": False, "model": p.models.FAST}
        later_finished = threading.Event()
        calls = []

        class Engine:
            device = "CPU"

            def __init__(self, cfg, name, *, threads, workers=1, engine=None):
                pass

            def words(self, audio, offset, report):
                calls.append(offset)
                if offset == 0 and not later_finished.wait(5):
                    raise AssertionError("The second chunk did not run concurrently")
                if offset == 1:
                    later_finished.set()
                if offset == 2 and calls.count(offset) == 1:
                    raise MemoryError("worker memory")
                return [[offset, offset + 0.5, " voz", 1.0]]

        def ranges(pcm, start):
            return [(a, a + p.RATE) for a in range(start, len(pcm), p.RATE)]

        with (
            tempfile.TemporaryDirectory() as folder,
            patch.object(p.models, "ensure", return_value=p.models.FAST),
            patch.object(p, "import_workers", return_value=2),
            patch.object(p, "import_ranges", ranges),
            patch.object(p, "Whisper", Engine),
        ):
            folder = Path(folder)
            np.zeros(4 * p.RATE, np.int16).tofile(folder / p.PCM)
            p.transcribe_import(folder, cfg, lambda *_: None)
            chunks = p.load_partial(folder, cfg)
            self.assertEqual([c["words"][0][0] for c in chunks], [0, 1, 2, 3])
            self.assertEqual([calls.count(t) for t in (0, 1, 2)], [1, 1, 2])

            # Simulate an interrupted write to the last line and resume the same file.
            journal = folder / p.PARTIAL
            lines = journal.read_bytes().splitlines(keepends=True)
            journal.write_bytes(b"".join(lines[:-1]) + lines[-1][:15])
            calls.clear()
            p.transcribe_import(folder, cfg, lambda *_: None)
            self.assertEqual(calls, [3])
            self.assertEqual(p.load_partial(folder, cfg), chunks)
            self.assertEqual(p.load_partial(folder, dict(cfg, language="en"), repair=True), [])
            self.assertEqual(journal.stat().st_size, 0)
