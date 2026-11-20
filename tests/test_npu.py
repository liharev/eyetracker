"""Тесты NPU-кода без платы: структуры C-интерфейса и вся цепочка обработки
с эмуляцией librknnrt (модели выполняются через OpenCV с тем же вводом/выводом, что у .rknn)."""
import ctypes
import time
import zipfile
from pathlib import Path

import cv2
import numpy as np
import pytest

from eyetracker import models, npu
from eyetracker.vision.yunet_decode import OUTPUT_NAMES, decode, letterbox

DATA = Path(__file__).parent / "data"


def test_struct_layout_matches_rknn_api_h():
    # значения получены компиляцией rknn_api.h (v2.5.0) для LP64 (x86_64 / aarch64)
    assert ctypes.sizeof(npu._TensorAttr) == 376
    assert ctypes.sizeof(npu._Input) == 32
    assert ctypes.sizeof(npu._Output) == 24
    assert ctypes.sizeof(npu._SdkVersion) == 512
    offsets = {
        npu._TensorAttr: {"n_elems": 328, "fmt": 336, "fl": 348, "zp": 352, "scale": 356,
                          "pass_through": 368, "h_stride": 372},
        npu._Input: {"buf": 8, "size": 16, "pass_through": 20, "type": 24, "fmt": 28},
        npu._Output: {"index": 4, "buf": 8, "size": 16},
    }
    for cls, fields in offsets.items():
        for name, off in fields.items():
            assert getattr(cls, name).offset == off, (cls.__name__, name)
    assert (npu.RKNN_TENSOR_UINT8, npu.RKNN_TENSOR_NHWC) == (3, 1)


def test_availability_off_board(monkeypatch):
    monkeypatch.setattr(npu.os, "uname", lambda: type("U", (), {"machine": "x86_64"})())
    ok, why = npu.availability()
    assert not ok and "ARM64" in why


need_models = pytest.mark.skipif(
    not (models.find("yunet") and models.find("sface") and models.find("face_landmarker")
         and (DATA / "lena.jpg").exists() and models.find_rknn("yunet_320x256.rknn")),
    reason="нет моделей или тестовых изображений")


class EmulatedRknn:
    """Подмена npu.RknnModel: вход uint8 NHWC, выход float32 — как у librknnrt."""

    def __init__(self, path, core="auto", low_priority=True):
        name = Path(path).name
        self.name = name
        if name.startswith("yunet"):
            self.net = cv2.dnn.readNetFromONNX(str(models.find("yunet")))
            self.output_names = list(OUTPUT_NAMES)
        elif name.startswith("sface"):
            self.net = cv2.dnn.readNetFromONNX(str(models.find("sface")))
            self.output_names = ["fc1"]
        else:
            with zipfile.ZipFile(models.find("face_landmarker")) as z:
                self.net = cv2.dnn.readNetFromTFLite(np.frombuffer(z.read("face_landmarks_detector.tflite"),
                                                                   np.uint8))
            self.output_names = list(self.net.getUnconnectedOutLayersNames())

    def run(self, images):
        img = images[0]
        assert img.dtype == np.uint8 and img.ndim == 3
        if self.name.startswith("yunet"):
            if self.name == "yunet_320x256.rknn":
                assert img.shape == (256, 320, 3)
            else:
                assert img.shape == (128, 128, 3)
            self.net.setInput(cv2.dnn.blobFromImage(img))           # BGR 0..255
            outs = self.net.forward(OUTPUT_NAMES)
        elif self.name.startswith("sface"):
            assert img.shape == (112, 112, 3)
            self.net.setInput(cv2.dnn.blobFromImage(img))           # RGB уже подан
            outs = [self.net.forward()]
        else:
            assert img.shape == (256, 256, 3)
            self.net.setInput(np.ascontiguousarray((img.astype(np.float32) / 255).transpose(2, 0, 1)[None]))
            outs = self.net.forward(self.output_names)
        return [np.asarray(o, np.float32).ravel() for o in outs]

    def close(self):
        pass


@pytest.fixture
def emulated(monkeypatch):
    monkeypatch.setattr(npu, "RknnModel", EmulatedRknn)
    monkeypatch.setattr(npu, "availability", lambda: (True, "эмуляция"))


def frames():
    from eyetracker.devtools import canvas
    return [canvas(cv2.imread(str(DATA / n))) for n in ("lena.jpg", "face2.jpg")]


@need_models
def test_npu_pipeline_matches_cpu(emulated):
    from eyetracker.vision.detector import FaceDetector, NpuFaceDetector
    from eyetracker.vision.gaze import GazeEstimator
    from eyetracker.vision.recognizer import FaceEmbedder, NpuFaceEmbedder

    cpu_det = FaceDetector(models.find("yunet"), detect_width=320)
    npu_det = NpuFaceDetector(models.find_rknn("yunet_320x256.rknn"), models.find_rknn("yunet_128x128.rknn"))
    cpu_emb, npu_emb = FaceEmbedder(models.find("sface")), NpuFaceEmbedder(models.find_rknn("sface_112.rknn"))
    task = models.find("face_landmarker")
    g_cpu = GazeEstimator(task, True, backend="opencv")
    g_npu = GazeEstimator(task, True, backend="npu", rknn_path=models.find_rknn("face_landmarks_256.rknn"))
    assert "npu" in g_npu.method
    for img in frames():
        a, b = cpu_det.detect(img), npu_det.detect(img)
        assert a.shape == b.shape == (1, 15)
        # letterbox 320×256 против resize 320×240 — те же пиксели лица, расхождение мало
        assert np.abs(a[0, :14] - b[0, :14]).max() < 0.05 * a[0, 2]
        ra, rb = cpu_det.detect_rois(img, a), npu_det.detect_rois(img, a)
        assert np.abs(ra[0, :14] - rb[0, :14]).max() < 0.02 * ra[0, 2]
        assert float(cpu_emb.embed(img, a[0]) @ npu_emb.embed(img, a[0])) > 0.999
        sa, sb = g_cpu.estimate(img, a[0]), g_npu.estimate(img, a[0])
        assert abs(sa.yaw - sb.yaw) < 0.5 and abs(sa.pitch - sb.pitch) < 0.5


@need_models
def test_letterbox_and_decode_scale():
    img = frames()[0]
    lb, k = letterbox(img, 320, 256)
    assert lb.shape == (256, 320, 3) and k == pytest.approx(2.0)
    wide = np.zeros((360, 640, 3), np.uint8)
    lb2, k2 = letterbox(wide, 320, 256)
    assert lb2.shape == (256, 320, 3) and k2 == pytest.approx(2.0)
    empty = {f'{k}_{s}': np.zeros((32 // s) ** 2 * {'cls': 1, 'obj': 1, 'bbox': 4, 'kps': 10}[k])
             for k in ('cls', 'obj', 'bbox', 'kps') for s in (8, 16, 32)}
    assert decode(empty, 32, 32).shape == (0, 15)


@need_models
def test_engine_uses_npu_and_falls_back(emulated, monkeypatch, tmp_path):
    from eyetracker.config import Config
    from eyetracker.devtools import FakeCamera, FakeLocker
    from eyetracker.engine import Engine
    from eyetracker.events import EventDispatcher, EventStore
    from eyetracker.vision.recognizer import FaceDatabase

    def run(accel):
        cfg = Config()
        cfg.processing.accelerator = accel
        cfg.processing.fps = cfg.processing.idle_fps = 20
        cfg.processing.cpu_cores = ""
        cfg.gaze.enabled = True
        db = FaceDatabase(tmp_path / f"faces-{accel}")
        cams = []
        eng = Engine(cfg, db, EventDispatcher(cfg, EventStore(tmp_path / f"e-{accel}.db"), None),
                     locker=FakeLocker(), allow_download=False,
                     camera_factory=lambda c: cams.append(FakeCamera(c)) or cams[-1])
        eng.start()
        try:
            t0 = time.time()
            while not cams and time.time() - t0 < 10:
                time.sleep(0.02)
            img = frames()[0]
            cams[0].frame = img
            emb = eng.submit(lambda e: e.embedder.embed(img, e.detector.detect(img)[0])).result(20)
            db.add_person("Лена", np.vstack([emb, emb]))
            t0 = time.time()
            while time.time() - t0 < 15 and not (eng.status.authorized and eng.status.gaze_method):
                time.sleep(0.05)
            return eng.status.accelerator, eng.status.authorized, eng.status.gaze_method
        finally:
            eng.stop()

    assert run("auto") == ("NPU", ("Лена",), "радужка/npu")
    assert run("cpu")[0] == "CPU"
    # NPU недоступен → автоматически CPU, программа работает
    monkeypatch.setattr(npu, "availability", lambda: (False, "нет устройства"))
    acc, who, method = run("npu")
    assert acc == "CPU" and who == ("Лена",) and "npu" not in method
