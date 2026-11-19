"""Основной цикл обработки: камера → лица → распознавание → взгляд → правила → действия."""
from __future__ import annotations

import concurrent.futures
import logging
import queue
import threading
import time
from dataclasses import dataclass
from typing import Callable, List, Optional, Tuple

import cv2
import numpy as np

from . import models
from .camera import Camera
from .config import Config
from .events import Event, EventDispatcher
from .locker import ScreenLocker
from .policy import AUTHORIZED, PENDING, UNKNOWN, FaceInfo, GazeStage, Observation, Policy
from .vision.detector import FaceDetector, face_size
from .vision.gaze import GazeEstimator, GazeSample, GazeZone
from .vision.recognizer import FaceDatabase, FaceEmbedder
from .vision.tracker import FaceTracker, Track

log = logging.getLogger(__name__)


def gaze_zone(cfg: Config) -> GazeZone:
    g = cfg.gaze
    return GazeZone(g.zone_yaw_min, g.zone_yaw_max, g.zone_pitch_min, g.zone_pitch_max, g.zone_margin)


@dataclass
class EngineStatus:
    state: str = "starting"         # starting | running | paused | camera_error | error
    message: str = ""
    faces: int = 0
    authorized: Tuple[str, ...] = ()
    unknown: int = 0
    gaze_stage: int = 0
    away_s: float = 0.0
    gaze: Optional[Tuple[float, float]] = None
    on_screen: Optional[bool] = None
    screen_locked: Optional[bool] = None
    fps: float = 0.0
    paused_until: float = 0.0
    db_size: int = 0
    gaze_method: str = ""


class Engine:
    def __init__(self, cfg: Config, db: FaceDatabase, dispatcher: EventDispatcher,
                 locker: Optional[ScreenLocker] = None, allow_download: bool = True,
                 camera_factory: Callable = Camera):
        self.cfg = cfg.copy()
        self.db = db
        self.dispatcher = dispatcher
        self.locker = locker or ScreenLocker(cfg.lock.method, cfg.lock.custom_command)
        self.allow_download = allow_download
        self.camera_factory = camera_factory

        self.on_status: Optional[Callable[[EngineStatus], None]] = None
        self.on_gaze_stage: Optional[Callable[[int], None]] = None

        self._cfg_lock = threading.Lock()
        self._pending_cfg: Optional[Config] = None
        self._tasks: "queue.Queue[Tuple[Callable, concurrent.futures.Future]]" = queue.Queue()
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None

        self.camera: Optional[Camera] = None
        self.detector: Optional[FaceDetector] = None
        self.embedder: Optional[FaceEmbedder] = None
        self.gaze: Optional[GazeEstimator] = None
        self.tracker = FaceTracker()
        self.policy = Policy(self._effective_cfg(), time.monotonic())

        self._paused_until = 0.0
        self._pause_lock = threading.Lock()
        self.preview_enabled = False
        self.calibration_mode = False
        self._preview: Optional[np.ndarray] = None
        self._last_frame: Optional[np.ndarray] = None
        self._latest_gaze: Optional[Tuple[float, GazeSample]] = None
        self._data_lock = threading.Lock()
        self._stage = GazeStage.NORMAL
        self._db_version = -1
        self.status = EngineStatus()
        self._target_on_screen: Optional[bool] = None
        self._locking = False

    # ------------------------------------------------------------ public API
    def start(self) -> None:
        self._thread = threading.Thread(target=self._run, name="engine", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=5)
        if self.camera:
            self.camera.stop()
        if self.gaze:
            self.gaze.close()

    def apply_config(self, cfg: Config) -> None:
        with self._cfg_lock:
            self._pending_cfg = cfg.copy()

    def submit(self, fn: Callable) -> concurrent.futures.Future:
        """Выполнить fn(engine) в потоке движка (доступ к нейросетям без гонок)."""
        fut: concurrent.futures.Future = concurrent.futures.Future()
        self._tasks.put((fn, fut))
        return fut

    def pause(self, seconds: float) -> None:
        with self._pause_lock:
            self._paused_until = time.monotonic() + seconds

    def resume(self) -> None:
        with self._pause_lock:
            self._paused_until = 0.0

    @property
    def paused(self) -> bool:
        return time.monotonic() < self._paused_until

    def pause_remaining(self) -> float:
        return max(0.0, self._paused_until - time.monotonic())

    def get_preview(self) -> Optional[np.ndarray]:
        with self._data_lock:
            return None if self._preview is None else self._preview.copy()

    def get_frame(self) -> Optional[np.ndarray]:
        with self._data_lock:
            return None if self._last_frame is None else self._last_frame.copy()

    def latest_gaze(self) -> Optional[Tuple[float, GazeSample]]:
        with self._data_lock:
            return self._latest_gaze

    # ---------------------------------------------------------------- setup
    def _effective_cfg(self) -> Config:
        """Без базы лиц правила 4 и 5 отключаются — иначе пользователь заблокирует сам себя."""
        eff = self.cfg.copy()
        if len(self.db) == 0:
            eff.authorized.lock_if_no_authorized = False
            eff.stranger.lock_on_stranger = False
        return eff

    def _init_models(self) -> bool:
        paths = {k: models.ensure(k, self.allow_download) for k in ("yunet", "sface")}
        if not paths["yunet"] or not paths["sface"]:
            self._set_status(state="error", message="Нет файлов моделей YuNet/SFace. Запустите: "
                                                    "python3 -m eyetracker --download-models")
            return False
        p = self.cfg.processing
        self.detector = FaceDetector(paths["yunet"], p.detect_threshold, detect_width=p.detect_width)
        self.embedder = FaceEmbedder(paths["sface"])
        # Оценщик взгляда (MediaPipe, ~50–100 МБ памяти) загружается лениво —
        # только когда контроль взгляда включён или открыта калибровка/просмотр.
        return True

    def _init_gaze(self) -> None:
        p = self.cfg.processing
        if self.gaze:
            self.gaze.close()
            self.gaze = None
        lm = models.ensure("face_landmarker", self.allow_download) if p.use_mediapipe else None
        self.gaze = GazeEstimator(lm, p.use_mediapipe, self.cfg.gaze.eye_gain)
        self.status.gaze_method = self.gaze.method

    def _apply_pending_config(self) -> None:
        with self._cfg_lock:
            new, self._pending_cfg = self._pending_cfg, None
        if new is None:
            return
        old = self.cfg
        self.cfg = new
        if new.camera != old.camera and self.camera:
            self.camera.stop()
            self.camera = self.camera_factory(new.camera)
            self.camera.start()
            self.tracker.clear()
        if self.detector and new.processing.detect_threshold != old.processing.detect_threshold:
            self.detector.set_threshold(new.processing.detect_threshold)
        if self.detector:
            self.detector.detect_width = new.processing.detect_width
        if self.gaze and (new.processing.use_mediapipe != old.processing.use_mediapipe or not new.gaze.enabled):
            self.gaze.close()
            self.gaze = None
        if self.gaze:
            self.gaze.eye_gain = new.gaze.eye_gain
        if new.processing.recognition_threshold != old.processing.recognition_threshold:
            self.tracker.reset_identities()
        self.locker.configure(new.lock.method, new.lock.custom_command)
        self.policy.set_config(self._effective_cfg())
        log.info("Настройки применены")

    # ------------------------------------------------------------- main loop
    def _run(self) -> None:
        try:
            if not self._init_models():
                while not self._stop.is_set():
                    self._process_tasks()
                    self._stop.wait(0.2)
                return
            self.camera = self.camera_factory(self.cfg.camera)
            self.camera.start()
            self._loop()
        except Exception as exc:  # noqa: BLE001
            log.exception("Критическая ошибка движка")
            self._set_status(state="error", message=str(exc))

    def _loop(self) -> None:
        last_seq = -1
        fps_t, fps_n = time.monotonic(), 0
        was_paused = False
        no_frame_since = time.monotonic()
        while not self._stop.is_set():
            loop_start = time.monotonic()
            self._apply_pending_config()
            self._process_tasks()
            if self.db.version != self._db_version:
                self._db_version = self.db.version
                self.tracker.reset_identities()
                self.policy.set_config(self._effective_cfg())

            frame, frame_t, seq = self.camera.read(timeout=1.0)
            if frame is None or seq == last_seq:
                if time.monotonic() - no_frame_since > 3.0:
                    self._set_status(state="camera_error", message=self.camera.last_error or "Нет кадров с камеры")
                    self._set_stage(GazeStage.NORMAL)
                    self._stop.wait(0.5)
                continue
            last_seq = seq
            no_frame_since = time.monotonic()
            now = time.monotonic()

            paused = self.paused
            if paused != was_paused:
                was_paused = paused
                if not paused:
                    self.policy.reset(now)
                    log.info("Контроль возобновлён")
                else:
                    log.info("Контроль приостановлен")
            self._process_frame(frame, now, paused)

            fps_n += 1
            if now - fps_t >= 2.0:
                self.status.fps = fps_n / (now - fps_t)
                fps_t, fps_n = now, 0
            period = 1.0 / self._target_fps(paused)
            self._stop.wait(max(0.0, period - (time.monotonic() - loop_start)))

    def _target_fps(self, paused: bool) -> float:
        """Адаптивная частота анализа: полная — только когда это действительно нужно."""
        p = self.cfg.processing
        if self.preview_enabled or self.calibration_mode or self._stage > GazeStage.NORMAL:
            return max(p.fps, 5.0) if (self.preview_enabled or self.calibration_mode) else p.fps
        if paused or not self.tracker.tracks:
            return p.idle_fps
        return p.fps

    def _process_tasks(self) -> None:
        while True:
            try:
                fn, fut = self._tasks.get_nowait()
            except queue.Empty:
                return
            if fut.set_running_or_notify_cancel():
                try:
                    fut.set_result(fn(self))
                except Exception as exc:  # noqa: BLE001
                    fut.set_exception(exc)

    # ------------------------------------------------------------ per frame
    def _process_frame(self, frame: np.ndarray, now: float, paused: bool) -> None:
        cfg = self.cfg
        dets = self.detector.detect(frame)
        tracks = self.tracker.update(dets, now)
        visible = FaceTracker.visible(tracks, now)
        db_empty = len(self.db) == 0

        # --- распознавание
        budget = 3
        for tr in sorted(visible, key=lambda x: -x.area):
            tr.recognizable = face_size(tr.row) >= cfg.processing.min_face_size
            if not tr.recognizable or db_empty or budget <= 0:
                continue
            interval = {PENDING: 0.0, UNKNOWN: 0.5}.get(tr.status, cfg.processing.recognize_interval_s)
            if now - tr.last_recog_t >= interval:
                budget -= 1
                emb = self.embedder.embed(frame, tr.row)
                m = self.db.match(emb, cfg.processing.recognition_threshold)
                tr.add_vote(m.person_id, m.name, m.score, now)

        # --- цель для контроля взгляда: самое крупное авторизованное лицо
        authorized_tracks = [tr for tr in tracks if tr.status == AUTHORIZED]
        target: Optional[Track] = max(authorized_tracks, key=lambda x: x.area) if authorized_tracks else None
        if target is None and self.calibration_mode and tracks:
            target = max(tracks, key=lambda x: x.area)
        need_gaze = (cfg.gaze.enabled or self.calibration_mode or self.preview_enabled) and not paused
        on_screen: Optional[bool] = None
        zone = gaze_zone(cfg)
        if need_gaze and self.gaze is None:
            self._init_gaze()
        if target is not None and need_gaze:
            if target.last_seen == now:
                sample = self.gaze.estimate(frame, target.row)
                target.gaze, target.gaze_t = sample, now
                if sample is None:
                    on_screen = False
                else:
                    with self._data_lock:
                        self._latest_gaze = (now, sample)
                    on_screen = zone.contains(sample.yaw, sample.pitch)
                    if sample.eyes_closed and cfg.gaze.eyes_closed_is_away:
                        on_screen = False
                self._target_on_screen = on_screen
            else:
                on_screen = self._target_on_screen

        faces = [FaceInfo(tr.id, tr.status if not db_empty else PENDING, tr.person_id, tr.name, tr.score, tr.area)
                 for tr in tracks]
        screen_locked = self.locker.is_locked(max_age_s=2.0)

        if paused:
            self._set_stage(GazeStage.NORMAL)
            result = None
        else:
            obs = Observation(now, faces, on_screen if target is not None and target.status == AUTHORIZED else None,
                              screen_locked)
            result = self.policy.update(obs)
            for pe in result.events:
                self._publish(pe.category, pe.type, pe.message, pe.details, frame)
            if result.lock_reason:
                self._do_lock()
            self._set_stage(result.gaze_stage)

        with self._data_lock:
            self._last_frame = frame
        if self.preview_enabled:
            preview = self._annotate(frame, tracks, target, on_screen, now)
            with self._data_lock:
                self._preview = preview

        auth_names = tuple(sorted({tr.name for tr in tracks if tr.status == AUTHORIZED and tr.name}))
        sample = target.gaze if target is not None else None
        self._set_status(
            state="paused" if paused else "running",
            message="" if not db_empty else "База авторизованных лиц пуста — правила 4, 5, 6 не работают",
            faces=len(tracks), authorized=auth_names,
            unknown=sum(1 for tr in tracks if tr.status == UNKNOWN and not db_empty),
            gaze_stage=int(self._stage), away_s=result.away_s if result else 0.0,
            gaze=(sample.yaw, sample.pitch) if sample is not None else None,
            on_screen=on_screen, screen_locked=screen_locked, paused_until=self.pause_remaining(),
            db_size=len(self.db))

    # -------------------------------------------------------------- actions
    def _publish(self, category: str, etype: str, message: str, details: dict, frame: Optional[np.ndarray]) -> None:
        snap = None
        if frame is not None and self.dispatcher.wants_snapshot(category):
            snap = encode_jpeg(frame)
        self.dispatcher.publish(Event(category, etype, message, dict(details), snapshot_jpeg=snap))

    def publish_system(self, etype: str, message: str, details: Optional[dict] = None) -> None:
        self.dispatcher.publish(Event("system", etype, message, details or {}))

    def _do_lock(self) -> None:
        if self._locking:
            return
        self._locking = True

        def worker():
            try:
                if not self.locker.lock():
                    self.publish_system("lock_failed", "Не удалось заблокировать экран: нет подходящей команды")
            finally:
                self._locking = False

        threading.Thread(target=worker, name="lock", daemon=True).start()

    def _set_stage(self, stage: GazeStage) -> None:
        if stage != self._stage:
            self._stage = stage
            if self.on_gaze_stage:
                self.on_gaze_stage(int(stage))

    def _set_status(self, **kw) -> None:
        for k, v in kw.items():
            setattr(self.status, k, v)
        if self.on_status:
            self.on_status(self.status)

    # -------------------------------------------------------------- preview
    def _annotate(self, frame, tracks: List[Track], target: Optional[Track], on_screen, now) -> np.ndarray:
        img = frame.copy()
        for tr in tracks:
            x, y, w, h = tr.bbox
            if tr.status == AUTHORIZED:
                color, label = (60, 200, 60), f"{tr.name} {tr.score:.2f}"
            elif tr.status == UNKNOWN:
                color, label = (40, 40, 230), f"Посторонний {tr.score:.2f}"
            else:
                color, label = (0, 200, 230), "?" if tr.recognizable else "далеко"
            thick = 3 if tr is target else 1
            cv2.rectangle(img, (x, y), (x + w, y + h), color, thick)
            put_text(img, label, (x, max(0, y - 22)), color)
            for i in range(5):
                cv2.circle(img, (int(tr.row[4 + 2 * i]), int(tr.row[5 + 2 * i])), 2, color, -1)
        if target is not None and target.gaze is not None:
            g: GazeSample = target.gaze
            state = "на экране" if on_screen else "МИМО"
            put_text(img, f"Взгляд: yaw {g.yaw:+.0f}° pitch {g.pitch:+.0f}° — {state}"
                          f"{' (глаза закрыты)' if g.eyes_closed else ''}", (8, 8),
                     (60, 200, 60) if on_screen else (40, 40, 230))
            x, y, w, h = target.bbox
            cx, cy = x + w // 2, y + h // 2
            dx = int(np.sin(np.radians(g.yaw)) * w)     # yaw > 0 — вправо по изображению
            dy = int(-np.sin(np.radians(g.pitch)) * h)  # pitch > 0 — вверх
            cv2.arrowedLine(img, (cx, cy), (cx + dx, cy + dy), (255, 200, 0), 2, tipLength=0.2)
        return img


def encode_jpeg(frame: np.ndarray, max_width: int = 800, quality: int = 80) -> Optional[bytes]:
    h, w = frame.shape[:2]
    if w > max_width:
        frame = cv2.resize(frame, (max_width, int(h * max_width / w)), interpolation=cv2.INTER_AREA)
    ok, buf = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, quality])
    return buf.tobytes() if ok else None


_font_cache = {}


def put_text(img: np.ndarray, text: str, org: Tuple[int, int], color) -> None:
    """Вывод текста с кириллицей: через Qt, если доступен, иначе транслитерация OpenCV."""
    try:
        from .qt import QtGui
        h, w = img.shape[:2]
        x, y = org
        rgb = np.ascontiguousarray(img)
        qimg = QtGui.QImage(rgb.data, w, h, 3 * w, QtGui.QImage.Format.Format_BGR888)
        painter = QtGui.QPainter(qimg)
        font = _font_cache.get("f")
        if font is None:
            font = QtGui.QFont()
            font.setPixelSize(16)
            font.setBold(True)
            _font_cache["f"] = font
        painter.setFont(font)
        metrics = QtGui.QFontMetrics(font)
        rect = metrics.boundingRect(text)
        painter.fillRect(x, y, rect.width() + 8, rect.height() + 4, QtGui.QColor(0, 0, 0, 160))
        painter.setPen(QtGui.QColor(int(color[2]), int(color[1]), int(color[0])))
        painter.drawText(x + 4, y + metrics.ascent() + 2, text)
        painter.end()
        if rgb is not img:
            img[:] = rgb
    except Exception:  # noqa: BLE001
        cv2.putText(img, text.encode("ascii", "replace").decode(), (org[0], org[1] + 16),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, color, 1, cv2.LINE_AA)
