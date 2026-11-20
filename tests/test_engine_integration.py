"""Сквозной тест движка на реальных моделях (пропускается, если модели не найдены).

Модели: EYETRACKER_MODELS=/путь/к/models или python3 -m eyetracker --download-models
"""
import time
from pathlib import Path

import cv2
import numpy as np
import pytest

from eyetracker import models
from eyetracker.config import Config
from eyetracker.devtools import FakeCamera, FakeLocker, canvas  # noqa: F401
from eyetracker.engine import Engine
from eyetracker.events import EventDispatcher, EventStore
from eyetracker.vision.recognizer import FaceDatabase

FIXTURES = Path(__file__).parent / "data"

pytestmark = pytest.mark.skipif(
    not (models.find("yunet") and models.find("sface") and (FIXTURES / "lena.jpg").exists()),
    reason="нет моделей или тестовых изображений")


def wait(pred, timeout=15):
    t0 = time.time()
    while time.time() - t0 < timeout:
        if pred():
            return True
        time.sleep(0.05)
    return False


def test_engine_end_to_end(tmp_path):
    lena = canvas(cv2.imread(str(FIXTURES / "lena.jpg")))
    other = canvas(cv2.imread(str(FIXTURES / "face2.jpg")))

    cfg = Config()
    cfg.processing.fps = 20
    cfg.processing.idle_fps = 20
    cfg.processing.cpu_cores = ""
    cfg.presence.lock_on_absence = True
    cfg.presence.absence_timeout_s = 1.0
    cfg.presence.leave_debounce_s = 0.3
    cfg.stranger.lock_on_stranger = True
    cfg.stranger.confirm_s = 0.3
    cfg.gaze.enabled = True
    cfg.gaze.t1_s, cfg.gaze.t2_s, cfg.gaze.t3_s = 0.2, 0.4, 0.6
    # зона, в которую взгляд заведомо не попадает → должна дойти стадия «звук»
    cfg.gaze.zone_yaw_min, cfg.gaze.zone_yaw_max = 60, 80
    for r in cfg.notify.routes.values():
        r.log, r.email, r.digest = True, False, False

    db = FaceDatabase(tmp_path / "faces")
    store = EventStore(tmp_path / "e.db")
    disp = EventDispatcher(cfg, store, None)
    locker = FakeLocker()
    cams = []

    def factory(c):
        cams.append(FakeCamera(c))
        return cams[-1]

    eng = Engine(cfg, db, disp, locker=locker, allow_download=False, camera_factory=factory)
    stages = []
    eng.on_gaze_stage = stages.append
    eng.start()
    try:
        assert wait(lambda: cams)
        cam = cams[0]
        # регистрация «авторизованного» лица через очередь задач движка
        cam.frame = lena

        def enroll(e):
            dets = e.detector.detect(lena)
            return e.embedder.embed(lena, dets[0])

        emb = eng.submit(enroll).result(timeout=10)
        db.add_person("Лена", np.vstack([emb, emb]))

        assert wait(lambda: eng.status.authorized == ("Лена",)), eng.status
        assert wait(lambda: eng.roi_scans > 5)        # между полными просмотрами — поиск в окрестности
        assert eng.full_scans < eng.roi_scans
        assert wait(lambda: 3 in stages), (stages, eng.status)   # T3 → звук
        assert locker.calls == 0

        # посторонний человек → блокировка по п.5
        cam.frame = other
        assert wait(lambda: locker.calls >= 1), eng.status
        # экран заблокирован → предупреждения о взгляде снимаются
        assert wait(lambda: stages[-1] == 0), stages
        locker.locked = False
        types = [e.type for e in store.query()]
        assert "unknown_face" in types and "screen_locked" in types

        # никого нет → блокировка по п.3
        n = locker.calls
        cam.frame = np.zeros_like(lena)
        assert wait(lambda: locker.calls > n), eng.status
        cats = [e.category for e in store.query() if e.type == "screen_locked"]
        assert "lock_stranger" in cats and "lock_absence" in cats
        assert "person_left" in [e.type for e in store.query()]
    finally:
        eng.stop()
        store.close()
