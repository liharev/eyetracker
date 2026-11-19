"""Оценка направления взгляда.

Основной метод — MediaPipe FaceLandmarker (478 точек, включая радужки):
    направление взгляда = поворот головы (из матрицы трансформации лица)
                         + поворот глаз (положение радужки относительно уголков глаз).
Резервный метод (если MediaPipe недоступен) — поворот головы по 5 точкам YuNet.

Все углы — в градусах относительно линии «лицо → камера»:
    yaw   > 0 — взгляд смещён вправо по изображению камеры;
    pitch > 0 — взгляд выше камеры (экран находится НИЖЕ камеры, т.е. pitch < 0).
Так как кадр для MediaPipe вырезается по центру лица, оценка почти не зависит
от того, где человек находится в кадре.
"""
from __future__ import annotations

import logging
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Tuple

import cv2
import numpy as np

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
            raise ValueError("Недостаточно точек калибровки")
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


class GazeEstimator:
    def __init__(self, landmarker_model: Optional[Path], use_mediapipe: bool = True, eye_gain: float = 2.5):
        self.eye_gain = eye_gain
        self._landmarker = None
        self.method = "head"
        if use_mediapipe and landmarker_model:
            try:
                import mediapipe as mp  # noqa: F401
                from mediapipe.tasks.python import BaseOptions, vision

                options = vision.FaceLandmarkerOptions(
                    base_options=BaseOptions(model_asset_path=str(landmarker_model)),
                    running_mode=vision.RunningMode.IMAGE,
                    num_faces=1,
                    min_face_detection_confidence=0.3,
                    min_face_presence_confidence=0.3,
                    output_face_blendshapes=False,
                    output_facial_transformation_matrixes=True,
                )
                self._landmarker = vision.FaceLandmarker.create_from_options(options)
                self._mp = mp
                self.method = "mediapipe"
                log.info("Оценка взгляда: MediaPipe FaceLandmarker (радужка + поворот головы)")
            except Exception as exc:  # noqa: BLE001
                log.warning("MediaPipe недоступен (%s) — используется оценка по повороту головы", exc)
                self._landmarker = None
        if self._landmarker is None:
            log.info("Оценка взгляда: поворот головы по 5 точкам YuNet")

    def close(self) -> None:
        if self._landmarker is not None:
            try:
                self._landmarker.close()
            except Exception:  # noqa: BLE001
                pass
            self._landmarker = None

    # ------------------------------------------------------------------
    def estimate(self, frame: np.ndarray, row: np.ndarray) -> Optional[GazeSample]:
        if self._landmarker is not None:
            sample = self._estimate_mediapipe(frame, row)
            if sample is not None:
                return sample
            return None  # лицо найдено детектором, но ориентиры нет — сильный поворот
        yaw, pitch = head_pose_from_yunet(row)
        return GazeSample(yaw, pitch, yaw, pitch, method="head")

    @staticmethod
    def _square_crop(frame: np.ndarray, row: np.ndarray, scale: float = 1.8, out: int = 256) -> np.ndarray:
        x, y, w, h = [float(v) for v in row[:4]]
        cx, cy = x + w / 2, y + h / 2
        side = max(w, h) * scale
        x0, y0 = int(round(cx - side / 2)), int(round(cy - side / 2))
        x1, y1 = int(round(cx + side / 2)), int(round(cy + side / 2))
        H, W = frame.shape[:2]
        pad = [max(0, -y0), max(0, y1 - H), max(0, -x0), max(0, x1 - W)]
        crop = frame[max(0, y0):min(H, y1), max(0, x0):min(W, x1)]
        if any(pad):
            crop = cv2.copyMakeBorder(crop, pad[0], pad[1], pad[2], pad[3], cv2.BORDER_CONSTANT, value=0)
        if crop.size == 0:
            return crop
        return cv2.resize(crop, (out, out), interpolation=cv2.INTER_AREA if crop.shape[0] > out else cv2.INTER_LINEAR)

    def _estimate_mediapipe(self, frame: np.ndarray, row: np.ndarray) -> Optional[GazeSample]:
        crop = self._square_crop(frame, row)
        if crop.size == 0:
            return None
        rgb = np.ascontiguousarray(cv2.cvtColor(crop, cv2.COLOR_BGR2RGB))
        result = self._landmarker.detect(self._mp.Image(image_format=self._mp.ImageFormat.SRGB, data=rgb))
        if not result.face_landmarks:
            return None
        pts = np.array([(p.x, p.y) for p in result.face_landmarks[0]], dtype=np.float64)
        if result.facial_transformation_matrixes:
            R = np.asarray(result.facial_transformation_matrixes[0], dtype=np.float64)[:3, :3]
            head_yaw = math.degrees(math.atan2(R[0, 2], R[2, 2]))
            head_pitch = _asin_deg(R[1, 2])
        else:
            head_yaw = head_pitch = 0.0
        return self.compose(pts, head_yaw, head_pitch, self.eye_gain)

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
            return GazeSample(head_yaw, head_pitch, head_yaw, head_pitch, method="mediapipe")
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
            method="mediapipe",
        )
