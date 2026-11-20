#!/usr/bin/env python3
"""Проверка работы NPU RK3588 на плате: корректность моделей, скорость, общая нагрузка.

Запуск (на плате, после ./install.sh):

    ~/.local/share/eyetracker/venv/bin/python ~/eyetracker/scripts/npu_check.py

Скрипт ничего не меняет в системе; работающую программу закрывать не обязательно
(но замеры будут точнее, если она закрыта).
"""
from __future__ import annotations

import argparse
import os
import platform
import sys
import tempfile
import time
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from eyetracker.resources import limit_threads_env  # noqa: E402

limit_threads_env(1)

import cv2  # noqa: E402
import numpy as np  # noqa: E402

from eyetracker import models, npu  # noqa: E402
from eyetracker.devtools import FakeCamera, FakeLocker, canvas, test_images  # noqa: E402

RKNN = ("yunet_320x256.rknn", "yunet_128x128.rknn", "sface_112.rknn", "face_landmarks_256.rknn")
results = []


def section(title):
    print(f"\n=== {title}")


def verdict(name, ok, text):
    results.append((name, ok))
    print(f"[{'OK' if ok else 'ОШИБКА'}] {name}: {text}")


def cpu_ms(fn, n=30):
    for _ in range(3):
        fn()
    t, c = time.perf_counter(), time.process_time()
    for _ in range(n):
        fn()
    return (time.perf_counter() - t) / n * 1000, (time.process_time() - c) / n * 1000


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--seconds", type=float, default=15, help="длительность замера нагрузки в каждом режиме")
    args = ap.parse_args()
    cv2.setNumThreads(1)

    section("Окружение")
    print(f"Python {platform.python_version()}, {platform.machine()}, ядро {platform.release()}")
    print(f"OpenCV {cv2.__version__}")
    ok, why = npu.availability()
    print(f"NPU: {why}")
    for name in RKNN:
        print(f"  {name}: {models.find_rknn(name) or 'НЕ НАЙДЕН'}")
    if not ok:
        verdict("NPU доступен", False, why)
        return summary()
    try:
        m = npu.RknnModel(models.find_rknn(RKNN[0]))
        api, drv = m.sdk_version()
        print(f"librknnrt: {api}; драйвер: {drv}")
        print("Входы:", [(a.name.decode(), m.input_shape(i)) for i, a in enumerate(m.inputs)])
        print("Выходы:", m.output_names)
        m.close()
        verdict("NPU доступен", True, "модель загружена")
    except Exception as exc:  # noqa: BLE001
        verdict("NPU доступен", False, f"{exc}")
        traceback.print_exc()
        return summary()

    section("Тестовые изображения")
    imgs = [canvas(cv2.imread(str(p))) for p in test_images(ROOT / "tests" / "data")]
    print(f"{len(imgs)} шт.")

    from eyetracker.vision.detector import FaceDetector, NpuFaceDetector
    from eyetracker.vision.gaze import GazeEstimator
    from eyetracker.vision.recognizer import FaceEmbedder, NpuFaceEmbedder

    cpu_det = FaceDetector(models.ensure("yunet"), detect_width=320)
    npu_det = NpuFaceDetector(models.find_rknn(RKNN[0]), models.find_rknn(RKNN[1]))

    section("Детекция лиц (YuNet): NPU против CPU")
    rows = []
    try:
        errs = []
        for img in imgs:
            a, b = cpu_det.detect(img), npu_det.detect(img)
            if a.shape[0] != b.shape[0] or a.shape[0] == 0:
                raise AssertionError(f"лиц CPU {a.shape[0]}, NPU {b.shape[0]}")
            errs.append(np.abs(a[0, :14] - b[0, :14]).max() / a[0, 2] * 100)
            ra, rb = cpu_det.detect_rois(img, a), npu_det.detect_rois(img, a)
            if ra.shape[0] != rb.shape[0] or ra.shape[0] == 0:
                raise AssertionError(f"окрестность: лиц CPU {ra.shape[0]}, NPU {rb.shape[0]}")
            errs.append(np.abs(ra[0, :14] - rb[0, :14]).max() / ra[0, 2] * 100)
            rows.append(a[0])
        verdict("Детекция на NPU", max(errs) < 10, f"макс. расхождение с CPU {max(errs):.1f}% ширины лица")
        w1, c1 = cpu_ms(lambda: cpu_det.detect(imgs[0]))
        w2, c2 = cpu_ms(lambda: npu_det.detect(imgs[0]))
        w3, c3 = cpu_ms(lambda: cpu_det.detect_rois(imgs[0], rows[:1]))
        w4, c4 = cpu_ms(lambda: npu_det.detect_rois(imgs[0], rows[:1]))
        print(f"  весь кадр:   CPU {w1:.1f} мс (процессор {c1:.1f} мс) | NPU {w2:.1f} мс (процессор {c2:.1f} мс)")
        print(f"  окрестность: CPU {w3:.1f} мс (процессор {c3:.1f} мс) | NPU {w4:.1f} мс (процессор {c4:.1f} мс)")
    except Exception as exc:  # noqa: BLE001
        verdict("Детекция на NPU", False, str(exc))
        traceback.print_exc()

    section("Распознавание (SFace): NPU против CPU")
    try:
        cpu_emb = FaceEmbedder(models.ensure("sface"))
        npu_emb = NpuFaceEmbedder(models.find_rknn(RKNN[2]))
        sims, embs = [], []
        for img, row in zip(imgs, rows):
            a, b = cpu_emb.embed(img, row), npu_emb.embed(img, row)
            sims.append(float(a @ b))
            embs.append(b)
        cross = float(embs[0] @ embs[1]) if len(embs) > 1 else 0.0
        verdict("Распознавание на NPU", min(sims) > 0.98,
                f"сходство с CPU {min(sims):.4f} (должно быть ≈1); разные люди {cross:.3f} (должно быть < 0.3)")
        w1, c1 = cpu_ms(lambda: cpu_emb.embed(imgs[0], rows[0]))
        w2, c2 = cpu_ms(lambda: npu_emb.embed(imgs[0], rows[0]))
        print(f"  CPU {w1:.1f} мс (процессор {c1:.1f} мс) | NPU {w2:.1f} мс (процессор {c2:.1f} мс)")
    except Exception as exc:  # noqa: BLE001
        verdict("Распознавание на NPU", False, str(exc))
        traceback.print_exc()

    section("Точки лица / взгляд: NPU против CPU")
    try:
        task = models.ensure("face_landmarker")
        g_cpu = GazeEstimator(task, True, backend="auto")
        g_npu = GazeEstimator(task, True, backend="npu", rknn_path=models.find_rknn(RKNN[3]))
        if "npu" not in g_npu.method:
            raise AssertionError(f"модель на NPU не запустилась ({g_npu.method})")
        diffs = []
        for img, row in zip(imgs, rows):
            a, b = g_cpu.estimate(img, row), g_npu.estimate(img, row)
            if a is None or b is None:
                raise AssertionError("точки лица не найдены")
            diffs.append(max(abs(a.yaw - b.yaw), abs(a.pitch - b.pitch)))
            print(f"  CPU yaw {a.yaw:+.1f} pitch {a.pitch:+.1f} | NPU yaw {b.yaw:+.1f} pitch {b.pitch:+.1f}")
        verdict("Взгляд на NPU", max(diffs) < 3, f"макс. расхождение углов {max(diffs):.2f}°")
        w1, c1 = cpu_ms(lambda: g_cpu.estimate(imgs[0], rows[0]))
        w2, c2 = cpu_ms(lambda: g_npu.estimate(imgs[0], rows[0]))
        print(f"  CPU ({g_cpu.method}) {w1:.1f} мс (процессор {c1:.1f} мс) | NPU {w2:.1f} мс (процессор {c2:.1f} мс)")
    except Exception as exc:  # noqa: BLE001
        verdict("Взгляд на NPU", False, str(exc))
        traceback.print_exc()

    section(f"Общая нагрузка программы (контроль взгляда включён, по {args.seconds:.0f} с)")
    loads = {}
    for accel in ("cpu", "npu"):
        try:
            loads[accel] = engine_load(accel, imgs[0], args.seconds)
            print(f"  {accel.upper()}: {loads[accel]}")
        except Exception as exc:  # noqa: BLE001
            print(f"  {accel.upper()}: ошибка {exc}")
            traceback.print_exc()
    return summary()


def engine_load(accel: str, frame, seconds: float) -> str:
    from eyetracker.config import Config
    from eyetracker.engine import Engine
    from eyetracker.events import EventDispatcher, EventStore
    from eyetracker.vision.recognizer import FaceDatabase

    cfg = Config()
    cfg.processing.accelerator = accel
    cfg.gaze.enabled = True
    tmp = Path(tempfile.mkdtemp())
    db = FaceDatabase(tmp / "faces")
    cams = []
    eng = Engine(cfg, db, EventDispatcher(cfg, EventStore(tmp / "e.db"), None), locker=FakeLocker(),
                 allow_download=False, camera_factory=lambda c: cams.append(FakeCamera(c, delay=0.002)) or cams[-1])
    eng.start()
    try:
        t0 = time.time()
        while not cams and time.time() - t0 < 30:
            time.sleep(0.05)
        cams[0].frame = frame
        emb = eng.submit(lambda e: e.embedder.embed(frame, e.detector.detect(frame)[0])).result(60)
        db.add_person("test", np.vstack([emb, emb]))
        time.sleep(3)
        t, c = time.monotonic(), time.process_time()
        time.sleep(seconds)
        cpu = (time.process_time() - c) / (time.monotonic() - t) * 100
        st = eng.status
        return (f"процессор {cpu:.1f}% одного ядра; нейросети: {st.accelerator}; взгляд: {st.gaze_method}; "
                f"анализ {st.fps:.1f} кадр/с; распознан: {', '.join(st.authorized) or 'нет'}")
    finally:
        eng.stop()


def summary() -> int:
    section("Итог")
    for name, ok in results:
        print(f"  {'OK    ' if ok else 'ОШИБКА'} {name}")
    print("\nПришлите, пожалуйста, весь этот вывод.")
    return 0 if results and all(ok for _, ok in results) else 1


if __name__ == "__main__":
    os.environ.setdefault("PYTHONUNBUFFERED", "1")
    sys.exit(main())
