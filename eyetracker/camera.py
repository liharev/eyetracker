"""Захват кадров с камеры в отдельном потоке (всегда отдаётся последний кадр)."""
from __future__ import annotations

import logging
import threading
import time
from typing import Optional, Tuple

import cv2
import numpy as np

from .config import CameraConfig
from .i18n import tr

log = logging.getLogger(__name__)

_BACKENDS = {
    "auto": cv2.CAP_ANY,
    "v4l2": getattr(cv2, "CAP_V4L2", cv2.CAP_ANY),
    "gstreamer": getattr(cv2, "CAP_GSTREAMER", cv2.CAP_ANY),
    "ffmpeg": getattr(cv2, "CAP_FFMPEG", cv2.CAP_ANY),
}


def open_capture(cfg: CameraConfig) -> cv2.VideoCapture:
    source = cfg.source.strip()
    backend = _BACKENDS.get(cfg.backend, cv2.CAP_ANY)
    if "!" in source:  # конвейер GStreamer
        cap = cv2.VideoCapture(source, _BACKENDS["gstreamer"])
        return cap
    target = int(source) if source.isdigit() else source
    if backend == cv2.CAP_ANY and isinstance(target, int):
        backend = _BACKENDS["v4l2"]
    cap = cv2.VideoCapture(target, backend)
    if cap.isOpened():
        if cfg.width and cfg.height:
            cap.set(cv2.CAP_PROP_FRAME_WIDTH, cfg.width)
            cap.set(cv2.CAP_PROP_FRAME_HEIGHT, cfg.height)
        if cfg.fps:
            cap.set(cv2.CAP_PROP_FPS, cfg.fps)
        cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
    return cap


def transform(frame: np.ndarray, cfg: CameraConfig) -> np.ndarray:
    if cfg.rotate == 90:
        frame = cv2.rotate(frame, cv2.ROTATE_90_CLOCKWISE)
    elif cfg.rotate == 180:
        frame = cv2.rotate(frame, cv2.ROTATE_180)
    elif cfg.rotate == 270:
        frame = cv2.rotate(frame, cv2.ROTATE_90_COUNTERCLOCKWISE)
    if cfg.mirror:
        frame = cv2.flip(frame, 1)
    return frame


class Camera:
    """Фоновый поток захвата с автоматическим переподключением.

    Для экономии CPU поток только «забирает» кадры из драйвера (grab — без
    декодирования/преобразования цвета), а декодирует (retrieve) лишь те кадры,
    которые реально запрошены движком (2–5 кадров/с вместо 15–30).
    """

    def __init__(self, cfg: CameraConfig):
        self.cfg = cfg
        self._cap: Optional[cv2.VideoCapture] = None
        self._cond = threading.Condition()
        self._want = False
        self._frame: Optional[np.ndarray] = None
        self._frame_t = 0.0
        self._seq = 0
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self.last_error = ""
        self.grabs = 0

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="camera", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        with self._cond:
            self._cond.notify_all()
        if self._thread:
            self._thread.join(timeout=3)
        self._release()

    def _release(self) -> None:
        if self._cap is not None:
            try:
                self._cap.release()
            except Exception:  # noqa: BLE001
                pass
            self._cap = None

    def _run(self) -> None:
        failures = 0
        while not self._stop.is_set():
            if self._cap is None or not self._cap.isOpened():
                self._release()
                self._cap = open_capture(self.cfg)
                if not self._cap.isOpened():
                    self.last_error = tr("Камера «{source}» недоступна", source=self.cfg.source)
                    if failures == 0:
                        log.error(self.last_error)
                    failures += 1
                    self._release()
                    self._stop.wait(min(5.0, 0.5 * failures))
                    continue
                log.info("Камера %s открыта", self.cfg.source)
                failures = 0
                self.last_error = ""
            ok = self._cap.grab()
            if ok:
                self.grabs += 1
            frame = None
            if ok and self._want:
                ok, frame = self._cap.retrieve()
            if not ok:
                failures += 1
                if failures > 30:
                    log.warning("Потерян сигнал камеры, переподключение")
                    self.last_error = tr("Нет кадров с камеры")
                    self._release()
                    failures = 0
                else:
                    self._stop.wait(0.05)
                continue
            failures = 0
            if frame is not None:
                frame = transform(frame, self.cfg)
                with self._cond:
                    self._frame = frame
                    self._frame_t = time.monotonic()
                    self._seq += 1
                    self._want = False
                    self._cond.notify_all()
        self._release()

    def read(self, timeout: float = 1.0) -> Tuple[Optional[np.ndarray], float, int]:
        """Запрашивает свежий кадр и ждёт его. Возвращает (кадр, время, номер)."""
        with self._cond:
            seq = self._seq
            self._want = True
            self._cond.wait_for(lambda: self._seq != seq or self._stop.is_set(), timeout=timeout)
            if self._seq == seq:
                return None, 0.0, seq
            return self._frame, self._frame_t, self._seq
