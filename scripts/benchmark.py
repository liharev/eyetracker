#!/usr/bin/env python3
"""Замер нагрузки движка на CPU/память без камеры (подставляется тестовое фото).

    python3 scripts/benchmark.py [empty|person|gaze] [секунды] [--accelerator auto|npu|cpu]
                                 [--gaze-backend auto|litert|opencv]

Нужны модели (python3 -m eyetracker --download-models) и тестовые фото (scripts/fetch_test_data.sh).
"""
import resource
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from eyetracker.resources import apply_limits, limit_threads_env  # noqa: E402

limit_threads_env(1)
import cv2  # noqa: E402
import numpy as np  # noqa: E402

from eyetracker.config import Config  # noqa: E402
from eyetracker.engine import Engine  # noqa: E402
from eyetracker.events import EventDispatcher, EventStore  # noqa: E402
from eyetracker.vision.recognizer import FaceDatabase  # noqa: E402
from eyetracker.devtools import FakeCamera, FakeLocker, canvas, test_images  # noqa: E402


class Cam(FakeCamera):
    def read(self, timeout=1.0):
        time.sleep(0.005)
        self.seq += 1
        return (None if self.frame is None else self.frame.copy()), time.monotonic(), self.seq


def main():
    import argparse

    ap = argparse.ArgumentParser()
    ap.add_argument("mode", nargs="?", default="person", choices=["empty", "person", "gaze"])
    ap.add_argument("seconds", nargs="?", type=float, default=20)
    ap.add_argument("--accelerator", default="auto", choices=["auto", "npu", "cpu"])
    ap.add_argument("--gaze-backend", default="auto", choices=["auto", "litert", "opencv"])
    a = ap.parse_args()
    mode, seconds = a.mode, a.seconds
    apply_limits("", 10)
    face = canvas(cv2.imread(str(test_images(ROOT / "tests" / "data")[0])))
    cfg = Config()
    cfg.gaze.enabled = mode == "gaze"
    cfg.processing.gaze_backend = a.gaze_backend
    cfg.processing.accelerator = a.accelerator
    tmp = tempfile.mkdtemp()
    db = FaceDatabase(Path(tmp) / "faces")
    cams = []
    eng = Engine(cfg, db, EventDispatcher(cfg, EventStore(Path(tmp) / "e.db"), None), locker=FakeLocker(),
                 allow_download=False, camera_factory=lambda c: cams.append(Cam(c)) or cams[-1])
    eng.start()
    while not cams:
        time.sleep(0.01)
    cams[0].frame = face if mode != "empty" else np.zeros_like(face)
    emb = eng.submit(lambda e: e.embedder.embed(face, e.detector.detect(face)[0])).result(30)
    db.add_person("test", np.vstack([emb, emb]))
    time.sleep(3)
    t0, c0 = time.monotonic(), time.process_time()
    time.sleep(seconds)
    cpu = (time.process_time() - c0) / (time.monotonic() - t0) * 100
    rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024
    print(f"{mode}: CPU {cpu:.1f}% одного ядра, анализ {eng.status.fps:.1f} кадр/с, "
          f"пик памяти {rss:.0f} МБ, нейросети: {eng.status.accelerator}, взгляд: {eng.status.gaze_method or '—'}")
    eng.stop()


if __name__ == "__main__":
    main()
