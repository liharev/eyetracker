"""Вспомогательные классы для тестов, замеров и проверки на плате (без камеры и блокировки)."""
from __future__ import annotations

import time
import urllib.request
from pathlib import Path
from typing import List

import cv2
import numpy as np

TEST_IMAGES = {
    "lena.jpg": "https://raw.githubusercontent.com/opencv/opencv/4.x/samples/data/lena.jpg",
    "face2.jpg": "https://storage.googleapis.com/mediapipe-assets/portrait.jpg",
}


class FakeCamera:
    """Подставляет заданный кадр вместо камеры."""

    def __init__(self, cfg=None, delay: float = 0.01):
        self.frame = None
        self.seq = 0
        self.last_error = ""
        self.delay = delay

    def start(self):
        pass

    def stop(self):
        pass

    def read(self, timeout=1.0):
        time.sleep(self.delay)
        if self.frame is None:
            return None, 0.0, self.seq
        self.seq += 1
        return self.frame.copy(), time.monotonic(), self.seq


class FakeLocker:
    def __init__(self):
        self.calls = 0
        self.locked = False

    def lock(self):
        self.calls += 1
        self.locked = True
        return True

    def is_locked(self, max_age_s=1.0):
        return self.locked

    def configure(self, *a):
        pass


def canvas(img: np.ndarray) -> np.ndarray:
    """Фото → кадр 640×480, как с камеры над экраном."""
    out = np.zeros((480, 640, 3), np.uint8)
    h, w = img.shape[:2]
    s = min(400 / h, 560 / w)
    img = cv2.resize(img, (int(w * s), int(h * s)))
    out[40:40 + img.shape[0], 40:40 + img.shape[1]] = img
    return out


def test_images(folder: Path, download: bool = True) -> List[Path]:
    """Тестовые фото (скачиваются при необходимости)."""
    folder.mkdir(parents=True, exist_ok=True)
    out = []
    for name, url in TEST_IMAGES.items():
        p = folder / name
        if not p.exists() and download:
            with urllib.request.urlopen(url, timeout=60) as resp:
                p.write_bytes(resp.read())
        if p.exists():
            out.append(p)
    return out
