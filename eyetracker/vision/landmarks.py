"""Прямой запуск модели 478 точек лица (из файла face_landmarker.task MediaPipe)
без самого MediaPipe.

Что даёт по сравнению с MediaPipe FaceLandmarker:
* не запускается собственный детектор лица MediaPipe — лицо уже найдено YuNet;
* нет фоновых потоков графа MediaPipe (поток «drishti»);
* модель выполняется в одном потоке: через LiteRT (бывший TFLite runtime, XNNPACK),
  а если его нет — через OpenCV DNN, который есть всегда.

Поворот головы вычисляется так же, как в MediaPipe: взвешенное совмещение
(Procrustes) эталонной 3D-модели лица с найденными точками.
"""
from __future__ import annotations

import logging
import math
import struct
import zipfile
from pathlib import Path
from typing import List, Tuple

import cv2
import numpy as np

log = logging.getLogger(__name__)

INPUT = 256
LANDMARKS_FILE = "face_landmarks_detector.tflite"
GEOMETRY_FILE = "geometry_pipeline_metadata_landmarks.binarypb"
CROP_SCALE = 1.5          # сторона вырезки относительно рамки YuNet
PRESENCE_MIN = 0.5        # минимальная уверенность модели, что в вырезке лицо


# ------------------------------------------------------------------ protobuf
def _varint(b: bytes, i: int) -> Tuple[int, int]:
    r = s = 0
    while True:
        c = b[i]
        i += 1
        r |= (c & 0x7F) << s
        s += 7
        if c < 0x80:
            return r, i


def _fields(b: bytes):
    i = 0
    while i < len(b):
        key, i = _varint(b, i)
        num, wt = key >> 3, key & 7
        if wt == 0:
            v, i = _varint(b, i)
        elif wt == 1:
            v, i = b[i:i + 8], i + 8
        elif wt == 5:
            v, i = b[i:i + 4], i + 4
        elif wt == 2:
            n, i = _varint(b, i)
            v, i = b[i:i + n], i + n
        else:
            raise ValueError(f"неподдерживаемый тип поля protobuf: {wt}")
        yield num, wt, v


def parse_geometry(data: bytes) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
    """GeometryPipelineMetadata → (вершины эталонной модели N×3, индексы опорных точек, веса)."""
    verts: List[float] = []
    ids: List[int] = []
    weights: List[float] = []
    for num, wt, v in _fields(data):
        if num == 1 and wt == 2:          # canonical_mesh
            for snum, swt, sv in _fields(v):
                if snum == 3:             # vertex_buffer (x, y, z, u, v)
                    if swt == 5:
                        verts.append(struct.unpack("<f", sv)[0])
                    elif swt == 2:
                        verts.extend(struct.unpack(f"<{len(sv) // 4}f", sv))
        elif num == 2 and wt == 2:        # procrustes_landmark_basis
            d = {snum: sv for snum, _, sv in _fields(v)}
            ids.append(int(d.get(1, 0)))
            weights.append(struct.unpack("<f", d[2])[0] if 2 in d else 1.0)
    mesh = np.asarray(verts, np.float64).reshape(-1, 5)[:, :3]
    return mesh, np.asarray(ids, np.int64), np.asarray(weights, np.float64)


def read_task(task_path: Path) -> Tuple[bytes, bytes]:
    with zipfile.ZipFile(task_path) as z:
        return z.read(LANDMARKS_FILE), z.read(GEOMETRY_FILE)


# ------------------------------------------------------------------ геометрия
def procrustes_rotation(src: np.ndarray, dst: np.ndarray, w: np.ndarray) -> np.ndarray:
    """Матрица поворота R (3×3), наилучшим образом совмещающая src с dst (с весами)."""
    w = w / w.sum()
    ps = (src * w[:, None]).sum(0)
    pd = (dst * w[:, None]).sum(0)
    h = ((src - ps) * w[:, None]).T @ (dst - pd)
    u, _, vt = np.linalg.svd(h)
    d = np.sign(np.linalg.det(vt.T @ u.T)) or 1.0
    return vt.T @ np.diag([1.0, 1.0, d]) @ u.T


def head_angles(rot: np.ndarray) -> Tuple[float, float]:
    """(yaw, pitch) направления «вперёд» лица: yaw > 0 — вправо по изображению, pitch > 0 — вверх."""
    yaw = math.degrees(math.atan2(rot[0, 2], rot[2, 2]))
    pitch = math.degrees(math.asin(max(-1.0, min(1.0, rot[1, 2]))))
    return yaw, pitch


def crop_transform(row: np.ndarray, scale: float = CROP_SCALE) -> Tuple[np.ndarray, float]:
    """Аффинное преобразование кадр → вырезка 256×256 с выравниванием глаз по горизонтали.

    Возвращает (матрица 2×3, угол наклона головы в радианах)."""
    x, y, w, h = (float(v) for v in row[:4])
    re, le = row[4:6].astype(np.float64), row[6:8].astype(np.float64)
    roll = math.atan2(le[1] - re[1], le[0] - re[0])
    cx, cy = x + w / 2, y + h / 2
    side = max(w, h) * scale
    k = INPUT / side
    c, s = math.cos(roll), math.sin(roll)
    # поворот на -roll вокруг центра лица, масштаб k, центр → (128, 128)
    m = np.array([[k * c, k * s, 0.0], [-k * s, k * c, 0.0]])
    m[:, 2] = np.array([INPUT / 2, INPUT / 2]) - m[:, :2] @ np.array([cx, cy])
    return m, roll


# ------------------------------------------------------------------ исполнители
class _LiteRT:
    name = "litert"

    def __init__(self, model: bytes):
        try:
            from ai_edge_litert.interpreter import Interpreter
        except ImportError:
            from tflite_runtime.interpreter import Interpreter  # type: ignore
        self._it = Interpreter(model_content=model, num_threads=1)
        self._it.allocate_tensors()
        self._in = self._it.get_input_details()[0]["index"]
        outs = self._it.get_output_details()
        self._lm = next(o["index"] for o in outs if int(np.prod(o["shape"])) == 1434)
        self._score = next(o["index"] for o in outs if int(np.prod(o["shape"])) == 1 and o["index"] != self._lm)

    def run(self, rgb01: np.ndarray) -> Tuple[np.ndarray, float]:
        self._it.set_tensor(self._in, rgb01[None])
        self._it.invoke()
        return (self._it.get_tensor(self._lm).reshape(-1, 3).copy(),
                float(self._it.get_tensor(self._score).ravel()[0]))


class _OpenCV:
    name = "opencv"

    def __init__(self, model: bytes):
        self._net = cv2.dnn.readNetFromTFLite(np.frombuffer(model, np.uint8))
        self._names = self._net.getUnconnectedOutLayersNames()

    def run(self, rgb01: np.ndarray) -> Tuple[np.ndarray, float]:
        self._net.setInput(np.ascontiguousarray(rgb01.transpose(2, 0, 1)[None]))
        outs = self._net.forward(self._names)
        lm = next(o for o in outs if o.size == 1434)
        score = next(o for o in outs if o.size == 1 and o is not lm)
        return lm.reshape(-1, 3).astype(np.float64), float(score.ravel()[0])


def make_runner(model: bytes, backend: str = "auto"):
    if backend in ("auto", "litert"):
        try:
            return _LiteRT(model)
        except Exception as exc:  # noqa: BLE001
            if backend == "litert":
                raise
            log.info("LiteRT недоступен (%s) — модель точек лица выполняется через OpenCV DNN", exc)
    return _OpenCV(model)


class FaceLandmarks:
    """Точки лица + поворот головы для лица, найденного YuNet."""

    def __init__(self, task_path: Path, backend: str = "auto"):
        model, geometry = read_task(Path(task_path))
        self._mesh, self._basis_ids, self._basis_w = parse_geometry(geometry)
        self._runner = make_runner(model, backend)
        self.backend = self._runner.name

    def detect(self, frame: np.ndarray, row: np.ndarray):
        """→ (точки 478×3 в координатах вырезки, поворот головы R, наклон roll) или None."""
        m, roll = crop_transform(row)
        crop = cv2.warpAffine(frame, m, (INPUT, INPUT), flags=cv2.INTER_LINEAR,
                              borderMode=cv2.BORDER_CONSTANT, borderValue=0)
        rgb01 = cv2.cvtColor(crop, cv2.COLOR_BGR2RGB).astype(np.float32) * (1.0 / 255.0)
        pts, logit = self._runner.run(rgb01)
        if 1.0 / (1.0 + math.exp(-logit)) < PRESENCE_MIN:
            return None
        # в правую систему координат эталонной модели: X вправо, Y вверх, Z к наблюдателю
        dst = np.stack([pts[self._basis_ids, 0], -pts[self._basis_ids, 1], -pts[self._basis_ids, 2]], 1)
        rot = procrustes_rotation(self._mesh[self._basis_ids], dst, self._basis_w)
        return pts, rot, roll
