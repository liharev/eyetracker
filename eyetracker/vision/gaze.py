"""Оценка направления взгляда.

Основной метод — модель 478 точек лица (включая радужки) из face_landmarker.task,
выполняемая напрямую, без MediaPipe (см. landmarks.py):
    направление взгляда = поворот головы (совмещение с эталонной 3D-моделью лица)
                         + поворот глаз (положение радужки относительно уголков глаз).
Резервный метод — поворот головы по 5 точкам YuNet (почти без затрат CPU).

Все углы — в градусах относительно линии «лицо → камера»:
    yaw   > 0 — взгляд смещён вправо по изображению камеры;
    pitch > 0 — взгляд выше камеры (экран находится НИЖЕ камеры, т.е. pitch < 0).
Вырезка лица выравнивается по линии глаз, а результат поворачивается обратно в
систему координат кадра, поэтому наклон головы набок не искажает оценку.
"""
from __future__ import annotations

import logging
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Tuple

import numpy as np

from ..i18n import tr

log = logging.getLogger(__name__)

# Индексы точек MediaPipe Face Mesh
_EYE_A = (33, 133, 159, 145, 468)   # глаз слева на изображении: внешн., внутр. угол, веко верх/низ, радужка
_EYE_B = (362, 263, 386, 374, 473)  # глаз справа на изображении: внутр., внешн. угол, веко верх/низ, радужка
EAR_CLOSED = 0.14


@dataclass
class GazeSample:
    yaw: float
    pitch: float
    head_yaw: float
    head_pitch: float
    eye_yaw: float = 0.0
    eye_pitch: float = 0.0
    eyes_closed: bool = False
    method: str = "head"


@dataclass
class GazeZone:
    yaw_min: float
    yaw_max: float
    pitch_min: float
    pitch_max: float
    margin: float = 0.0

    def contains(self, yaw: float, pitch: float) -> bool:
        m = self.margin
        return (self.yaw_min - m <= yaw <= self.yaw_max + m) and (self.pitch_min - m <= pitch <= self.pitch_max + m)

    @classmethod
    def from_points(cls, points, margin: float = 4.0, min_span: float = 6.0) -> "GazeZone":
        arr = np.asarray(points, dtype=np.float64)
        if arr.ndim != 2 or arr.shape[0] < 2:
            raise ValueError(tr("Недостаточно точек калибровки"))
        ymin, ymax = float(arr[:, 0].min()), float(arr[:, 0].max())
        pmin, pmax = float(arr[:, 1].min()), float(arr[:, 1].max())
        if ymax - ymin < min_span:
            c = (ymax + ymin) / 2
            ymin, ymax = c - min_span / 2, c + min_span / 2
        if pmax - pmin < min_span:
            c = (pmax + pmin) / 2
            pmin, pmax = c - min_span / 2, c + min_span / 2
        return cls(ymin, ymax, pmin, pmax, margin)


def _asin_deg(x: float) -> float:
    return math.degrees(math.asin(max(-1.0, min(1.0, x))))


def head_pose_from_yunet(row: np.ndarray) -> Tuple[float, float]:
    """Грубая оценка (yaw, pitch) головы по 5 точкам YuNet."""
    re = row[4:6].astype(np.float64)
    le = row[6:8].astype(np.float64)
    nose = row[8:10].astype(np.float64)
    mouth = (row[10:12].astype(np.float64) + row[12:14].astype(np.float64)) / 2
    eye_mid = (re + le) / 2
    eye_vec = le - re
    eye_dist = float(np.linalg.norm(eye_vec))
    if eye_dist < 1e-3:
        return 0.0, 0.0
    ex = eye_vec / eye_dist
    ey = np.array([-ex[1], ex[0]])  # «вниз» в системе координат глаз
    d = float(np.dot(nose - eye_mid, ex)) / eye_dist
    yaw = _asin_deg(d / 0.65)
    em = float(np.dot(mouth - eye_mid, ey))
    if em < 1e-3:
        return yaw, 0.0
    r = float(np.dot(nose - eye_mid, ey)) / em
    pitch = _asin_deg((0.55 - r) / 0.45)
    return yaw, pitch


def unroll(yaw: float, pitch: float, roll: float) -> Tuple[float, float]:
    """Переводит направление из выровненной по глазам вырезки в систему координат кадра."""
    y, p = math.radians(yaw), math.radians(pitch)
    d = np.array([math.sin(y) * math.cos(p), math.sin(p), math.cos(y) * math.cos(p)])
    c, s = math.cos(roll), math.sin(roll)
    d = np.array([[c, s, 0.0], [-s, c, 0.0], [0.0, 0.0, 1.0]]) @ d
    return math.degrees(math.atan2(d[0], d[2])), _asin_deg(d[1])


class GazeEstimator:
    """precise=True — модель точек лица (LiteRT или OpenCV DNN); иначе — поворот головы по YuNet."""

    def __init__(self, landmarker_model: Optional[Path], precise: bool = True, eye_gain: float = 2.5,
                 backend: str = "auto", rknn_path: Optional[Path] = None, core: str = "auto"):
        self.eye_gain = eye_gain
        self._landmarks = None
        self.method = "head"
        if precise and landmarker_model:
            try:
                from .landmarks import FaceLandmarks

                try:
                    self._landmarks = FaceLandmarks(landmarker_model, backend, rknn_path, core)
                except Exception as exc:  # noqa: BLE001
                    if backend != "npu":
                        raise
                    log.warning("Модель точек лица на NPU не запустилась (%s) — используется CPU", exc)
                    self._landmarks = FaceLandmarks(landmarker_model, "auto")
                self.method = tr("радужка") + "/" + self._landmarks.backend
                log.info("Оценка взгляда: модель точек лица (%s, 1 поток), радужка + поворот головы",
                         self._landmarks.backend)
            except Exception as exc:  # noqa: BLE001
                log.warning("Модель точек лица недоступна (%s) — оценка по повороту головы", exc)
                self._landmarks = None
        if self._landmarks is None:
            log.info("Оценка взгляда: поворот головы по 5 точкам YuNet")

    def close(self) -> None:
        self._landmarks = None

    def estimate(self, frame: np.ndarray, row: np.ndarray) -> Optional[GazeSample]:
        if self._landmarks is None:
            yaw, pitch = head_pose_from_yunet(row)
            return GazeSample(yaw, pitch, yaw, pitch, method="head")
        res = self._landmarks.detect(frame, row)
        if res is None:
            return None  # лицо найдено детектором, но точки — нет: сильный поворот
        pts, rot, roll = res
        from .landmarks import head_angles

        head_yaw, head_pitch = head_angles(rot)
        s = self.compose(pts[:, :2].astype(np.float64), head_yaw, head_pitch, self.eye_gain)
        s.yaw, s.pitch = unroll(s.yaw, s.pitch, roll)
        s.head_yaw, s.head_pitch = unroll(s.head_yaw, s.head_pitch, roll)
        s.method = self.method
        return s

    @staticmethod
    def eye_metrics(pts: np.ndarray, idx) -> Tuple[float, float, float, float]:
        """(горизонт. смещение радужки −0.5..0.5, вертик. смещение, EAR, ширина глаза)."""
        a, b, up, low, iris = (pts[i] for i in idx)
        v = b - a
        width2 = float(np.dot(v, v))
        if width2 < 1e-10:
            return 0.0, 0.0, 0.0, 0.0
        rel = iris - a
        horiz = float(np.dot(rel, v)) / width2 - 0.5
        vert = float(v[0] * rel[1] - v[1] * rel[0]) / width2   # > 0 — радужка ниже линии уголков
        ear = float(np.linalg.norm(up - low)) / math.sqrt(width2)
        return horiz, vert, ear, math.sqrt(width2)

    @classmethod
    def compose(cls, pts: np.ndarray, head_yaw: float, head_pitch: float, gain: float) -> GazeSample:
        ha, va, ear_a, wa = cls.eye_metrics(pts, _EYE_A)
        hb, vb, ear_b, wb = cls.eye_metrics(pts, _EYE_B)
        total_w = wa + wb
        if total_w <= 0:
            return GazeSample(head_yaw, head_pitch, head_yaw, head_pitch, method="landmarks")
        # при повороте головы ближний к камере глаз виден лучше — даём ему больший вес
        horiz = (ha * wa + hb * wb) / total_w
        vert = (va * wa + vb * wb) / total_w
        ear = (ear_a * wa + ear_b * wb) / total_w
        closed = ear < EAR_CLOSED
        if closed:
            eye_yaw = eye_pitch = 0.0
        else:
            eye_yaw = _asin_deg(horiz * gain)
            eye_pitch = -_asin_deg(vert * gain)
        return GazeSample(
            yaw=head_yaw + eye_yaw,
            pitch=head_pitch + eye_pitch,
            head_yaw=head_yaw,
            head_pitch=head_pitch,
            eye_yaw=eye_yaw,
            eye_pitch=eye_pitch,
            eyes_closed=closed,
            method="landmarks",
        )
