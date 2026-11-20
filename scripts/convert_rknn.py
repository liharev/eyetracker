#!/usr/bin/env python3
"""Конвертация моделей EyeTracker для NPU RK3588 (формат .rknn) с проверкой в симуляторе.

Запускается на ПК с Linux x86_64 (или aarch64) с установленным rknn-toolkit2 (Python 3.8–3.12):

    python3 -m venv rknn-venv && rknn-venv/bin/pip install rknn-toolkit2 "setuptools<70"
    rknn-venv/bin/python scripts/convert_rknn.py --models ~/.local/share/eyetracker/models --out models/rknn

Модели конвертируются в FP16 (без квантования — точность как у исходных, калибровочный набор не нужен).
После конвертации каждая модель прогоняется в симуляторе rknn-toolkit2 на тестовых фото
(tests/data, см. scripts/fetch_test_data.sh) и сравнивается с эталоном на CPU (OpenCV).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
import zipfile
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from eyetracker.vision.yunet_decode import OUTPUT_NAMES, decode, letterbox  # noqa: E402

# имя файла → (исходник, вход, параметры нормализации, описание)
SPECS = {
    "yunet_320x256.rknn": dict(src="face_detection_yunet_2023mar.onnx", kind="onnx", input="input",
                               shape=[1, 3, 256, 320], mean=[0, 0, 0], std=[1, 1, 1],
                               note="YuNet, полный кадр (BGR, 0..255)"),
    "yunet_128x128.rknn": dict(src="face_detection_yunet_2023mar.onnx", kind="onnx", input="input",
                               shape=[1, 3, 128, 128], mean=[0, 0, 0], std=[1, 1, 1],
                               note="YuNet, окрестность лица (BGR, 0..255)"),
    "sface_112.rknn": dict(src="face_recognition_sface_2021dec.onnx", kind="onnx", input="data",
                           shape=[1, 3, 112, 112], mean=[0, 0, 0], std=[1, 1, 1],
                           note="SFace, выровненное лицо 112×112 (RGB, 0..255)"),
    "face_landmarks_256.rknn": dict(src="face_landmarker.task", kind="tflite", input=None,
                                    shape=[1, 256, 256, 3], mean=[0, 0, 0], std=[255, 255, 255],
                                    note="478 точек лица, вырезка 256×256 (RGB, 0..255 → 0..1)"),
}


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def build(rknn_cls, spec: dict, models: Path, tmp: Path):
    r = rknn_cls(verbose=False)
    r.config(target_platform="rk3588", mean_values=[spec["mean"]], std_values=[spec["std"]])
    if spec["kind"] == "onnx":
        ret = r.load_onnx(str(models / spec["src"]), inputs=[spec["input"]], input_size_list=[spec["shape"]])
    else:
        tfl = tmp / "face_landmarks_detector.tflite"
        with zipfile.ZipFile(models / spec["src"]) as z:
            tfl.write_bytes(z.read("face_landmarks_detector.tflite"))
        ret = r.load_tflite(str(tfl))
    if ret != 0:
        raise RuntimeError(f"загрузка {spec['src']} не удалась ({ret})")
    if r.build(do_quantization=False) != 0:
        raise RuntimeError(f"сборка {spec['src']} не удалась")
    return r


def canvas(img: np.ndarray) -> np.ndarray:
    """Фото → кадр 640×480, как с камеры (лицо крупным планом у экрана)."""
    out = np.zeros((480, 640, 3), np.uint8)
    h, w = img.shape[:2]
    s = min(400 / h, 560 / w)
    img = cv2.resize(img, (int(w * s), int(h * s)))
    out[40:40 + img.shape[0], 40:40 + img.shape[1]] = img
    return out


def test_images():
    data = ROOT / "tests" / "data"
    return [canvas(cv2.imread(str(p))) for p in sorted(data.glob("*.jpg"))]


def check(name: str, r, models: Path, images) -> str:
    """Сравнение симулятора с эталоном на CPU; возвращает строку отчёта."""
    if r.init_runtime() != 0:
        return "симулятор недоступен"
    yunet = str(models / "face_detection_yunet_2023mar.onnx")
    det = cv2.FaceDetectorYN.create(yunet, "", (320, 256), 0.75, 0.3, 5000)
    lines = []
    for img in images:
        lb, _ = letterbox(img, 320, 256)
        det.setInputSize((320, 256))
        _, ref = det.detect(lb)
        row = ref[0]
        if name.startswith("yunet"):
            if name == "yunet_128x128.rknn":
                x, y, w, h = row[:4]
                side = int(max(w, h) * 2)
                x0, y0 = int(x + w / 2 - side / 2), int(y + h / 2 - side / 2)
                crop = cv2.copyMakeBorder(lb, side, side, side, side, cv2.BORDER_CONSTANT, value=0)
                inp = cv2.resize(crop[y0 + side:y0 + 2 * side, x0 + side:x0 + 2 * side], (128, 128))
                W = H = 128
                det.setInputSize((128, 128))
                _, ref2 = det.detect(inp)
            else:
                inp, W, H, ref2 = lb, 320, 256, ref
            outs = r.inference(inputs=[inp], data_format="nhwc")
            got = decode(dict(zip(OUTPUT_NAMES, outs)), W, H)
            if got.shape[0] != ref2.shape[0]:
                lines.append(f"лиц {got.shape[0]} вместо {ref2.shape[0]}")
            else:
                err = np.abs(got[:, :14] - ref2[:, :14]).max() / max(1.0, float(ref2[0, 2])) * 100
                lines.append(f"расхождение {err:.2f}% ширины лица")
        elif name.startswith("sface"):
            rec = cv2.FaceRecognizerSF.create(str(models / "face_recognition_sface_2021dec.onnx"), "")
            aligned = rec.alignCrop(lb, row)
            a = rec.feature(aligned).ravel()
            b = np.asarray(r.inference(inputs=[cv2.cvtColor(aligned, cv2.COLOR_BGR2RGB)], data_format="nhwc")[0]).ravel()
            cos = float(a @ b / np.linalg.norm(a) / np.linalg.norm(b))
            lines.append(f"сходство с CPU {cos:.4f}")
        else:
            sys.path.insert(0, str(ROOT))
            from eyetracker.vision.landmarks import INPUT, crop_transform
            m, _ = crop_transform(row)
            crop = cv2.warpAffine(lb, m, (INPUT, INPUT))
            rgb = cv2.cvtColor(crop, cv2.COLOR_BGR2RGB)
            with zipfile.ZipFile(models / "face_landmarker.task") as z:
                net = cv2.dnn.readNetFromTFLite(np.frombuffer(z.read("face_landmarks_detector.tflite"), np.uint8))
            net.setInput(np.ascontiguousarray((rgb.astype(np.float32) / 255).transpose(2, 0, 1)[None]))
            ref_lm = next(o for o in net.forward(net.getUnconnectedOutLayersNames()) if o.size == 1434)
            got = next(np.asarray(o) for o in r.inference(inputs=[rgb], data_format="nhwc") if np.asarray(o).size == 1434)
            err = np.abs(ref_lm.reshape(-1, 3)[:, :2] - got.reshape(-1, 3)[:, :2]).max()
            lines.append(f"макс. расхождение точек {err:.2f} px из 256")
    return "; ".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--models", type=Path, required=True, help="папка с исходными моделями")
    ap.add_argument("--out", type=Path, default=ROOT / "models" / "rknn")
    ap.add_argument("--no-check", action="store_true")
    args = ap.parse_args()
    from rknn.api import RKNN
    try:
        from importlib.metadata import version
        toolkit = version("rknn-toolkit2")
    except Exception:  # noqa: BLE001
        toolkit = "?"
    args.out.mkdir(parents=True, exist_ok=True)
    tmp = args.out / ".tmp"
    tmp.mkdir(exist_ok=True)
    images = [] if args.no_check else test_images()
    manifest = {"toolkit": toolkit, "target": "rk3588", "models": {}}
    for name, spec in SPECS.items():
        print(f"== {name}: {spec['note']}")
        r = build(RKNN, spec, args.models, tmp)
        path = args.out / name
        if r.export_rknn(str(path)) != 0:
            raise RuntimeError(f"экспорт {name} не удался")
        report = check(name, r, args.models, images) if images else "не проверялась"
        r.release()
        print(f"   {path.stat().st_size / 1e6:.1f} МБ; проверка: {report}")
        manifest["models"][name] = {"sha256": sha256(path), "source": spec["src"], "note": spec["note"],
                                    "check": report}
    (args.out / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    for p in tmp.iterdir():
        p.unlink()
    tmp.rmdir()
    print("Готово:", args.out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
