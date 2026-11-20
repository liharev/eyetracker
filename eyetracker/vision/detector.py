"""Детектор лиц YuNet (OpenCV FaceDetectorYN).

Два режима поиска:
* detect()      — по всему кадру (уменьшенному до detect_width);
* detect_rois() — только в окрестностях уже известных лиц (маленькие квадратные
  вырезки roi_size×roi_size). Это в несколько раз дешевле и используется между
  периодическими полными просмотрами кадра.
"""
from __future__ import annotations

from pathlib import Path
from typing import Iterable, Tuple

import cv2
import numpy as np

# Строка результата YuNet (15 значений):
# x, y, w, h, правый глаз(x,y), левый глаз(x,y), нос(x,y),
# правый угол рта(x,y), левый угол рта(x,y), score
SCORE_IDX = 14
ROI_EXPAND = 2.0     # сторона окрестности относительно размера лица
ROI_SIZE = 128       # размер вырезки окрестности для детектора, px
_XS = [0, 4, 6, 8, 10, 12]
_YS = [1, 5, 7, 9, 11, 13]


def _clip(faces: np.ndarray, w: int, h: int) -> np.ndarray:
    faces[:, 0] = np.clip(faces[:, 0], 0, w - 1)
    faces[:, 1] = np.clip(faces[:, 1], 0, h - 1)
    faces[:, 2] = np.minimum(faces[:, 2], w - faces[:, 0])
    faces[:, 3] = np.minimum(faces[:, 3], h - faces[:, 1])
    return faces


def _iou(a: np.ndarray, b: np.ndarray) -> float:
    x1, y1 = max(a[0], b[0]), max(a[1], b[1])
    x2, y2 = min(a[0] + a[2], b[0] + b[2]), min(a[1] + a[3], b[1] + b[3])
    inter = max(0.0, x2 - x1) * max(0.0, y2 - y1)
    union = a[2] * a[3] + b[2] * b[3] - inter
    return float(inter / union) if union > 0 else 0.0


def dedupe(faces: np.ndarray, iou_threshold: float = 0.4) -> np.ndarray:
    """Убирает дубликаты (одно лицо, найденное в пересекающихся окрестностях)."""
    if faces.shape[0] < 2:
        return faces
    order = np.argsort(-faces[:, SCORE_IDX])
    keep = []
    for i in order:
        if all(_iou(faces[i], faces[j]) < iou_threshold for j in keep):
            keep.append(i)
    return faces[keep]


class FaceDetector:
    def __init__(self, model_path: Path, score_threshold: float = 0.75, nms_threshold: float = 0.3,
                 detect_width: int = 320, roi_size: int = ROI_SIZE):
        self.model_path = str(model_path)
        self.detect_width = detect_width
        self.roi_size = roi_size
        self.score_threshold = score_threshold
        self._size: Tuple[int, int] = (320, 240)
        self._net = cv2.FaceDetectorYN.create(self.model_path, "", self._size, score_threshold, nms_threshold, 5000)
        # отдельный экземпляр с постоянным размером входа — без пересчёта якорей на каждом кадре
        self._roi_net = cv2.FaceDetectorYN.create(self.model_path, "", (roi_size, roi_size), score_threshold,
                                                  nms_threshold, 5000)

    def set_threshold(self, value: float) -> None:
        self.score_threshold = value
        self._net.setScoreThreshold(float(value))
        self._roi_net.setScoreThreshold(float(value))

    def detect(self, frame: np.ndarray) -> np.ndarray:
        """Поиск по всему кадру. Возвращает массив N×15 (float32) в координатах кадра."""
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
        return _clip(faces, w, h)

    def detect_rois(self, frame: np.ndarray, rows: Iterable[np.ndarray]) -> np.ndarray:
        """Поиск только в окрестностях заданных лиц (строки YuNet из прошлых кадров)."""
        h, w = frame.shape[:2]
        found = []
        n = self.roi_size
        for row in rows:
            x, y, bw, bh = (float(v) for v in row[:4])
            side = max(bw, bh) * ROI_EXPAND
            x0 = int(round(x + bw / 2 - side / 2))
            y0 = int(round(y + bh / 2 - side / 2))
            s = int(round(side))
            if s < 8:
                continue
            crop = frame[max(0, y0):min(h, y0 + s), max(0, x0):min(w, x0 + s)]
            if crop.size == 0:
                continue
            pad = (max(0, -y0), max(0, y0 + s - h), max(0, -x0), max(0, x0 + s - w))
            if any(pad):
                crop = cv2.copyMakeBorder(crop, *pad, cv2.BORDER_CONSTANT, value=0)
            roi = cv2.resize(crop, (n, n), interpolation=cv2.INTER_AREA if s > n else cv2.INTER_LINEAR)
            faces = self._detect_roi_image(roi)
            if faces.shape[0] == 0:
                continue
            k = s / float(n)
            faces[:, :14] *= k
            faces[:, _XS] += x0      # ширину и высоту (индексы 2, 3) не сдвигаем
            faces[:, _YS] += y0
            found.append(faces)
        if not found:
            return np.zeros((0, 15), dtype=np.float32)
        return _clip(dedupe(np.vstack(found)), w, h)


    def _detect_roi_image(self, roi: np.ndarray) -> np.ndarray:
        _, faces = self._roi_net.detect(roi)
        return np.zeros((0, 15), np.float32) if faces is None else faces.astype(np.float32)


class NpuFaceDetector(FaceDetector):
    """YuNet на NPU RK3588: модели фиксированного размера 320×256 (кадр) и 128×128 (окрестность)."""

    FULL = (320, 256)

    def __init__(self, full_model: Path, roi_model: Path, score_threshold: float = 0.75,
                 nms_threshold: float = 0.3, core: str = "auto"):
        from ..npu import RknnModel

        self.score_threshold = score_threshold
        self.nms_threshold = nms_threshold
        self.detect_width = self.FULL[0]
        self.roi_size = ROI_SIZE
        self._full = RknnModel(full_model, core)
        self._roi = RknnModel(roi_model, core)

    def set_threshold(self, value: float) -> None:
        self.score_threshold = float(value)

    def _run(self, model, img: np.ndarray, w: int, h: int) -> np.ndarray:
        from .yunet_decode import OUTPUT_NAMES, decode

        outs = model.run([img])
        names = model.output_names
        named = dict(zip(names, outs)) if set(OUTPUT_NAMES) <= set(names) else dict(zip(OUTPUT_NAMES, outs))
        return decode(named, w, h, self.score_threshold, self.nms_threshold)

    def detect(self, frame: np.ndarray) -> np.ndarray:
        from .yunet_decode import letterbox

        h, w = frame.shape[:2]
        img, k = letterbox(frame, *self.FULL)
        faces = self._run(self._full, img, *self.FULL)
        if faces.shape[0]:
            faces[:, :14] *= k
        return _clip(faces, w, h)

    def _detect_roi_image(self, roi: np.ndarray) -> np.ndarray:
        return self._run(self._roi, roi, self.roi_size, self.roi_size)


def face_size(row: np.ndarray) -> float:
    return float(min(row[2], row[3]))
