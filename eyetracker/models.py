"""Поиск и загрузка файлов нейросетевых моделей."""
from __future__ import annotations

import hashlib
import logging
import os
import shutil
import tempfile
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional

from . import paths

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class ModelSpec:
    key: str
    filename: str
    url: str
    sha256: str
    required: bool = True


MODELS = {
    "yunet": ModelSpec(
        "yunet",
        "face_detection_yunet_2023mar.onnx",
        "https://media.githubusercontent.com/media/opencv/opencv_zoo/main/models/"
        "face_detection_yunet/face_detection_yunet_2023mar.onnx",
        "8f2383e4dd3cfbb4553ea8718107fc0423210dc964f9f4280604804ed2552fa4",
    ),
    "sface": ModelSpec(
        "sface",
        "face_recognition_sface_2021dec.onnx",
        "https://media.githubusercontent.com/media/opencv/opencv_zoo/main/models/"
        "face_recognition_sface/face_recognition_sface_2021dec.onnx",
        "0ba9fbfa01b5270c96627c4ef784da859931e02f04419c829e83484087c34e79",
    ),
    "face_landmarker": ModelSpec(
        "face_landmarker",
        "face_landmarker.task",
        "https://storage.googleapis.com/mediapipe-models/face_landmarker/face_landmarker/float16/1/"
        "face_landmarker.task",
        "64184e229b263107bc2b804c6625db1341ff2bb731874b0bcc2fe6544e0bc9ff",
        required=False,
    ),
}


def search_dirs() -> List[Path]:
    dirs: List[Path] = []
    env = os.environ.get("EYETRACKER_MODELS")
    if env:
        dirs.append(Path(env))
    dirs.append(paths.models_dir())
    dirs.append(Path(__file__).resolve().parent.parent / "models")
    dirs.append(Path("/usr/share/eyetracker/models"))
    return dirs


def find(key: str) -> Optional[Path]:
    spec = MODELS[key]
    for d in search_dirs():
        candidate = d / spec.filename
        if candidate.is_file() and candidate.stat().st_size > 0:
            return candidate
    return None


def find_rknn(filename: str) -> Optional[Path]:
    """Модель для NPU (.rknn): models/rknn/ в каталоге данных или в исходниках."""
    for d in search_dirs():
        candidate = d / "rknn" / filename
        if candidate.is_file() and candidate.stat().st_size > 0:
            return candidate
    return None


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def download(key: str, target_dir: Optional[Path] = None, timeout: float = 60.0) -> Path:
    spec = MODELS[key]
    target_dir = Path(target_dir) if target_dir else paths.models_dir()
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / spec.filename
    log.info("Загрузка модели %s из %s", spec.filename, spec.url)
    fd, tmp_name = tempfile.mkstemp(dir=str(target_dir), suffix=".part")
    tmp = Path(tmp_name)
    try:
        with os.fdopen(fd, "wb") as out, urllib.request.urlopen(spec.url, timeout=timeout) as resp:
            shutil.copyfileobj(resp, out)
        if tmp.stat().st_size < 1024:
            raise IOError(f"Получен слишком маленький файл для {spec.filename} — проверьте доступ к сети")
        if spec.sha256:
            digest = _sha256(tmp)
            if digest != spec.sha256:
                raise IOError(f"Контрольная сумма {spec.filename} не совпадает ({digest})")
        os.replace(tmp, target)
    finally:
        if tmp.exists():
            tmp.unlink()
    return target


def ensure(key: str, allow_download: bool = True) -> Optional[Path]:
    path = find(key)
    if path or not allow_download:
        return path
    try:
        return download(key)
    except Exception as exc:  # noqa: BLE001
        level = logging.ERROR if MODELS[key].required else logging.WARNING
        log.log(level, "Не удалось загрузить модель %s: %s", key, exc)
        return None


def ensure_all(allow_download: bool = True) -> dict:
    return {key: ensure(key, allow_download) for key in MODELS}
