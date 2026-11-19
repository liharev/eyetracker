"""Детектор лиц YuNet (OpenCV FaceDetectorYN)."""
from __future__ import annotations

from pathlib import Path
from typing import Tuple

import cv2
import numpy as np

# Строка результата YuNet (15 значений):
# x, y, w, h, правый глаз(x,y), левый глаз(x,y), нос(x,y),
# правый угол рта(x,y), левый угол рта(x,y), score
SCORE_IDX = 14


class FaceDetector:
    def __init__(self, model_path: Path, score_threshold: float = 0.75, nms_threshold: float = 0.3,
                 detect_width: int = 320):
        self.model_path = str(model_path)
        self.detect_width = detect_width
        self.score_threshold = score_threshold
        self._size: Tuple[int, int] = (320, 240)
        self._net = cv2.FaceDetectorYN.create(self.model_path, "", self._size, score_threshold, nms_threshold, 5000)

    def set_threshold(self, value: float) -> None:
        self.score_threshold = value
        self._net.setScoreThreshold(float(value))

    def detect(self, frame: np.ndarray) -> np.ndarray:
        """Возвращает массив N×15 (float32) в координатах исходного кадра.

        Детекция выполняется на уменьшенной копии кадра (detect_width) — это
        в 4 раза дешевле, чем на 640×480, при достаточной точности для лиц у экрана.
        """
        h, w = frame.shape[:2]
        scale = 1.0
        small = frame
        if self.detect_width and w > self.detect_width:
            scale = w / float(self.detect_width)
            small = cv2.resize(frame, (self.detect_width, int(round(h / scale))), interpolation=cv2.INTER_AREA)
        sh, sw = small.shape[:2]
        if (sw, sh) != self._size:
            self._size = (sw, sh)
            self._net.setInputSize(self._size)
        _, faces = self._net.detect(small)
        if faces is None:
            return np.zeros((0, 15), dtype=np.float32)
        faces = faces.astype(np.float32)
        if scale != 1.0:
            faces[:, :14] *= scale
        # обрезаем рамки по границам кадра
        faces[:, 0] = np.clip(faces[:, 0], 0, w - 1)
        faces[:, 1] = np.clip(faces[:, 1], 0, h - 1)
        faces[:, 2] = np.minimum(faces[:, 2], w - faces[:, 0])
        faces[:, 3] = np.minimum(faces[:, 3], h - faces[:, 1])
        return faces


def face_size(row: np.ndarray) -> float:
    return float(min(row[2], row[3]))
