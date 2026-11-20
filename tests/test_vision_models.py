"""Тесты на реальных моделях (пропускаются, если нет моделей или тестовых фото)."""
import math
from pathlib import Path

import cv2
import numpy as np
import pytest

from eyetracker import models
from eyetracker.vision import landmarks as L
from eyetracker.vision.detector import FaceDetector
from eyetracker.vision.gaze import GazeEstimator, unroll

DATA = Path(__file__).parent / "data"
pytestmark = pytest.mark.skipif(
    not (models.find("yunet") and models.find("face_landmarker") and (DATA / "lena.jpg").exists()),
    reason="нет моделей или тестовых изображений")


def image(name="lena.jpg"):
    from eyetracker.devtools import canvas
    return canvas(cv2.imread(str(DATA / name)))


def rotate(img, deg):
    h, w = img.shape[:2]
    return cv2.warpAffine(img, cv2.getRotationMatrix2D((w / 2, h / 2), deg, 1.0), (w, h))


@pytest.fixture(scope="module")
def det():
    return FaceDetector(models.find("yunet"))


def test_roi_detection_matches_full(det):
    for name in ("lena.jpg", "face2.jpg"):
        img = image(name)
        full = det.detect(img)
        roi = det.detect_rois(img, full)
        assert roi.shape[0] == full.shape[0] == 1
        # расхождение — в пределах обычного разброса детектора
        assert np.abs(roi[0, :14] - full[0, :14]).max() < 0.15 * full[0, 2]
        # окрестность пустого места — лиц нет
        empty = full.copy()
        empty[0, :2] = (10, 10)
        empty[0, 2:4] = 40
        assert det.detect_rois(np.zeros_like(img), empty).shape[0] == 0


def test_geometry_metadata():
    _, geometry = L.read_task(models.find("face_landmarker"))
    mesh, ids, w = L.parse_geometry(geometry)
    assert mesh.shape == (468, 3) and len(ids) == len(w) > 20
    # эталонная модель: X вправо, Y вверх, Z к наблюдателю
    assert mesh[263, 0] > 0 > mesh[33, 0]
    assert mesh[10, 1] > 0 > mesh[152, 1]
    assert mesh[1, 2] > mesh[234, 2]


@pytest.mark.parametrize("backend", ["opencv", "litert"])
def test_landmarks_backends_and_pose(det, backend):
    if backend == "litert":
        pytest.importorskip("ai_edge_litert")
    g = GazeEstimator(models.find("face_landmarker"), True, backend=backend)
    assert backend in g.method
    img = image()
    s = g.estimate(img, det.detect(img)[0])
    f = cv2.flip(img, 1)
    sf = g.estimate(f, det.detect(f)[0])
    assert s is not None and sf is not None
    assert s.head_yaw > 10 and sf.head_yaw < -10          # зеркало меняет знак поворота
    assert abs(s.head_yaw + sf.head_yaw) < 5
    assert abs(s.head_pitch - sf.head_pitch) < 5
    # Лена смотрит почти в камеру: поворот глаз компенсирует поворот головы
    assert abs(s.yaw) < abs(s.head_yaw)
    # пустая вырезка — точек нет
    assert g.estimate(np.zeros_like(img), det.detect(img)[0]) is None


def test_backends_agree(det):
    pytest.importorskip("ai_edge_litert")
    img = image("face2.jpg")
    row = det.detect(img)[0]
    a = L.FaceLandmarks(models.find("face_landmarker"), "opencv").detect(img, row)
    b = L.FaceLandmarks(models.find("face_landmarker"), "litert").detect(img, row)
    assert np.abs(a[0][:, :2] - b[0][:, :2]).max() < 1.0      # px в вырезке 256×256


def test_roll_compensation(det):
    """Наклон кадра на ±20° поворачивает вектор взгляда, но не меняет его величину."""
    g = GazeEstimator(models.find("face_landmarker"), True, backend="opencv")
    base = None
    for deg in (0, 20, -20):
        img = rotate(image(), deg)
        s = g.estimate(img, det.detect(img)[0])
        v = np.array([s.head_yaw, s.head_pitch])
        if base is None:
            base = v
            continue
        a = math.radians(deg)
        expect = np.array([[math.cos(a), -math.sin(a)], [math.sin(a), math.cos(a)]]) @ base
        assert np.linalg.norm(v - expect) < 6, (deg, v, expect)


def test_unroll_identity():
    assert unroll(10.0, -5.0, 0.0) == pytest.approx((10.0, -5.0))
    y, p = unroll(0.0, 0.0, 0.5)
    assert abs(y) < 1e-9 and abs(p) < 1e-9
