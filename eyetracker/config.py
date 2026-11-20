"""Настройки приложения: dataclass-структуры + сохранение в JSON."""
from __future__ import annotations

import copy
import json
import logging
import os
import threading
from dataclasses import asdict, dataclass, field, fields, is_dataclass
from pathlib import Path
from typing import Any, Dict, Optional

from . import paths

log = logging.getLogger(__name__)

# Категории событий (пункты 1–6 ТЗ + служебные)
EVENT_CATEGORIES: Dict[str, str] = {
    "presence": "1. Обнаружение человека перед экраном",
    "recognition": "2. Распознавание лиц",
    "lock_absence": "3. Блокировка: перед экраном никого нет",
    "lock_unauthorized": "4. Блокировка: нет авторизованного лица",
    "lock_stranger": "5. Блокировка: постороннее лицо",
    "gaze": "6. Контроль взгляда",
    "system": "Служебные (вход в настройки, ошибки, запуск)",
}


def category_title(key: str) -> str:
    from .i18n import tr

    return tr(EVENT_CATEGORIES.get(key, key))


@dataclass
class GeneralConfig:
    autostart: bool = True
    log_retention_days: int = 90
    language: str = "system"           # system | ru | en
    tray_icon_color: str = "auto"      # auto | light (белые значки) | dark (чёрные) — меню и трей


@dataclass
class CameraConfig:
    # Индекс камеры ("0"), путь к устройству ("/dev/video11")
    # или конвейер GStreamer (строка, содержащая "!").
    source: str = "0"
    backend: str = "auto"  # auto | v4l2 | gstreamer | ffmpeg
    width: int = 640
    height: int = 480
    fps: int = 15                      # частота захвата (меньше — меньше нагрузка USB/ISP)
    rotate: int = 0  # 0 / 90 / 180 / 270
    mirror: bool = False


@dataclass
class ProcessingConfig:
    fps: float = 5.0                   # частота анализа, когда в кадре есть люди
    idle_fps: float = 2.0              # частота анализа, когда перед экраном никого нет
    detect_width: int = 320            # ширина кадра для детектора (уменьшение = экономия CPU)
    detect_threshold: float = 0.75     # порог уверенности детектора лиц
    min_face_size: int = 48            # px; лица меньше — только «присутствие»
    recognition_threshold: float = 0.40  # косинусная близость SFace
    recognize_interval_s: float = 2.0  # повторное распознавание известных треков
    accelerator: str = "auto"          # auto | npu | cpu — где выполнять нейросети (NPU RK3588)
    npu_core: str = "auto"             # auto | 0 | 1 | 2 — ядро NPU
    precise_gaze: bool = True          # точная оценка взгляда (радужка); False — только поворот головы
    gaze_backend: str = "auto"         # auto | litert | opencv — чем выполнять модель точек лица
    full_scan_interval_s: float = 1.0  # полный просмотр кадра; между ними — поиск возле известных лиц
    gaze_fps: float = 2.5              # частота оценки взгляда, пока нет предупреждения (с рамкой — полная)
    # Ограничение ресурсов: ядра CPU ("auto" — энергоэффективные ядра, на RK3588 это A55 cpu0-3;
    # "" — без ограничений; либо список "0-3", "0,1") и приоритет процесса (nice 0..19).
    cpu_cores: str = "auto"
    nice: int = 10


@dataclass
class PresenceConfig:
    """Пункты 1 и 3."""
    leave_debounce_s: float = 2.0      # сколько лицо должно отсутствовать, чтобы считать «ушёл»
    lock_on_absence: bool = True       # п.3 вкл/выкл
    absence_timeout_s: float = 60.0    # п.3 таймаут


@dataclass
class AuthorizedConfig:
    """Пункт 4."""
    lock_if_no_authorized: bool = False
    timeout_s: float = 10.0


@dataclass
class StrangerConfig:
    """Пункт 5."""
    lock_on_stranger: bool = False
    confirm_s: float = 2.0             # постороннее лицо должно быть видно не менее N сек


@dataclass
class LockConfig:
    method: str = "auto"               # auto | custom
    custom_command: str = ""
    relock_interval_s: float = 15.0    # повторная блокировка, если условие сохраняется


@dataclass
class GazeConfig:
    """Пункт 6."""
    enabled: bool = False
    t1_s: float = 5.0     # красная рамка
    t2_s: float = 10.0    # мигающая рамка
    t3_s: float = 15.0    # звуковой сигнал
    t4_s: float = 60.0    # уведомление на e-mail (если включена отправка событий взгляда на почту)
    return_debounce_s: float = 0.4
    face_lost_is_away: bool = True
    eyes_closed_is_away: bool = True
    # Зона «взгляд на экран» в градусах (относительно направления на камеру).
    # yaw > 0 — вправо по изображению, pitch > 0 — вверх.
    zone_yaw_min: float = -28.0
    zone_yaw_max: float = 28.0
    zone_pitch_min: float = -42.0
    zone_pitch_max: float = 10.0
    zone_margin: float = 4.0
    calibrated: bool = False
    eye_gain: float = 2.5
    border_width: int = 14
    border_color: str = "#ff0000"
    blink_interval_ms: int = 450
    sound: str = "builtin:beep"
    sound_repeat_s: float = 1.5
    volume: int = 80


@dataclass
class EmailConfig:
    smtp_host: str = ""
    smtp_port: int = 587
    security: str = "starttls"  # starttls | ssl | none
    username: str = ""
    password: str = ""
    sender: str = ""
    recipients: str = ""        # через запятую
    subject_prefix: str = "[CAMAI]"
    attach_snapshot: bool = True
    timeout_s: float = 20.0


@dataclass
class ScheduleConfig:
    mode: str = "interval"      # interval | daily
    interval_min: int = 60
    daily_times: str = "09:00,18:00"
    send_empty: bool = False


@dataclass
class CategoryRoute:
    email: bool = False   # отправлять на e-mail сразу
    log: bool = True      # записывать в журнал
    digest: bool = False  # записывать в журнал и отправлять по расписанию


def _default_routes() -> Dict[str, CategoryRoute]:
    routes = {key: CategoryRoute() for key in EVENT_CATEGORIES}
    for key in ("lock_absence", "lock_unauthorized", "lock_stranger"):
        routes[key] = CategoryRoute(email=False, log=True, digest=True)
    return routes


@dataclass
class NotifyConfig:
    routes: Dict[str, CategoryRoute] = field(default_factory=_default_routes)
    save_snapshots: bool = True


@dataclass
class AuthConfig:
    username: str = ""
    password_hash: str = ""
    salt: str = ""
    iterations: int = 200_000


@dataclass
class Config:
    general: GeneralConfig = field(default_factory=GeneralConfig)
    camera: CameraConfig = field(default_factory=CameraConfig)
    processing: ProcessingConfig = field(default_factory=ProcessingConfig)
    presence: PresenceConfig = field(default_factory=PresenceConfig)
    authorized: AuthorizedConfig = field(default_factory=AuthorizedConfig)
    stranger: StrangerConfig = field(default_factory=StrangerConfig)
    lock: LockConfig = field(default_factory=LockConfig)
    gaze: GazeConfig = field(default_factory=GazeConfig)
    email: EmailConfig = field(default_factory=EmailConfig)
    schedule: ScheduleConfig = field(default_factory=ScheduleConfig)
    notify: NotifyConfig = field(default_factory=NotifyConfig)
    auth: AuthConfig = field(default_factory=AuthConfig)

    # ------------------------------------------------------------------
    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Config":
        cfg = cls()
        data = dict(data or {})
        proc = data.get("processing")
        if isinstance(proc, dict) and "use_mediapipe" in proc and "precise_gaze" not in proc:
            proc = dict(proc)  # настройки версии 1.0
            proc["precise_gaze"] = proc.pop("use_mediapipe")
            data["processing"] = proc
        _merge(cfg, data)
        cfg.validate()
        return cfg

    def copy(self) -> "Config":
        return copy.deepcopy(self)

    def validate(self) -> None:
        g = self.gaze
        g.t1_s = max(0.0, float(g.t1_s))
        g.t2_s = max(g.t1_s, float(g.t2_s))
        g.t3_s = max(g.t2_s, float(g.t3_s))
        g.t4_s = max(1.0, float(g.t4_s))
        if self.general.language not in ("system", "ru", "en"):
            self.general.language = "system"
        if self.general.tray_icon_color not in ("auto", "light", "dark"):
            self.general.tray_icon_color = "auto"
        if self.email.subject_prefix == "[EyeTracker]":
            self.email.subject_prefix = "[CAMAI]"   # переименование программы
        if g.zone_yaw_min > g.zone_yaw_max:
            g.zone_yaw_min, g.zone_yaw_max = g.zone_yaw_max, g.zone_yaw_min
        if g.zone_pitch_min > g.zone_pitch_max:
            g.zone_pitch_min, g.zone_pitch_max = g.zone_pitch_max, g.zone_pitch_min
        g.volume = min(100, max(0, int(g.volume)))
        self.processing.fps = min(30.0, max(0.5, float(self.processing.fps)))
        self.processing.idle_fps = min(self.processing.fps, max(0.2, float(self.processing.idle_fps)))
        self.processing.detect_width = max(160, int(self.processing.detect_width))
        self.processing.nice = min(19, max(0, int(self.processing.nice)))
        self.processing.gaze_fps = min(30.0, max(0.5, float(self.processing.gaze_fps)))
        self.processing.full_scan_interval_s = min(10.0, max(0.0, float(self.processing.full_scan_interval_s)))
        if self.processing.accelerator not in ("auto", "npu", "cpu"):
            self.processing.accelerator = "auto"
        if str(self.processing.npu_core) not in ("auto", "0", "1", "2"):
            self.processing.npu_core = "auto"
        if self.processing.gaze_backend not in ("auto", "litert", "opencv"):
            self.processing.gaze_backend = "auto"
        self.camera.rotate = int(self.camera.rotate) if int(self.camera.rotate) in (0, 90, 180, 270) else 0
        if self.email.security not in ("starttls", "ssl", "none"):
            self.email.security = "starttls"
        if self.schedule.mode not in ("interval", "daily"):
            self.schedule.mode = "interval"
        self.schedule.interval_min = max(1, int(self.schedule.interval_min))
        for key in EVENT_CATEGORIES:
            self.notify.routes.setdefault(key, CategoryRoute())
        for route in self.notify.routes.values():
            if route.digest:
                route.log = True  # отчёт по расписанию строится из журнала


def gaze_email_enabled(cfg: "Config") -> bool:
    """Включена ли отправка на e-mail для событий контроля взгляда (тогда действует таймаут
    уведомления на почту)."""
    route = cfg.notify.routes.get("gaze")
    return bool(route and route.email)


def _coerce(default: Any, value: Any) -> Any:
    if isinstance(default, bool):
        if isinstance(value, str):
            return value.strip().lower() in ("1", "true", "yes", "on", "да")
        return bool(value)
    if isinstance(default, int) and not isinstance(default, bool):
        return int(float(value))
    if isinstance(default, float):
        return float(value)
    if isinstance(default, str):
        return str(value)
    return value


def _merge(obj: Any, data: Dict[str, Any]) -> None:
    for f in fields(obj):
        if f.name not in data:
            continue
        current = getattr(obj, f.name)
        value = data[f.name]
        try:
            if is_dataclass(current) and isinstance(value, dict):
                _merge(current, value)
            elif f.name == "routes" and isinstance(value, dict):
                routes = _default_routes()
                for key, route_data in value.items():
                    route = CategoryRoute()
                    if isinstance(route_data, dict):
                        _merge(route, route_data)
                    routes[key] = route
                setattr(obj, f.name, routes)
            else:
                setattr(obj, f.name, _coerce(current, value))
        except (TypeError, ValueError):
            log.warning("Некорректное значение настройки %s=%r, оставлено по умолчанию", f.name, value)


class ConfigStore:
    """Загрузка/сохранение настроек с правами 0600 (там хранится пароль SMTP)."""

    def __init__(self, path: Optional[Path] = None):
        self.path = Path(path) if path else paths.config_file()
        self._lock = threading.Lock()

    def load(self) -> Config:
        if not self.path.exists():
            return Config()
        try:
            with self.path.open("r", encoding="utf-8") as fh:
                return Config.from_dict(json.load(fh))
        except (OSError, ValueError) as exc:
            log.error("Не удалось прочитать %s: %s — используются настройки по умолчанию", self.path, exc)
            return Config()

    def save(self, cfg: Config) -> None:
        cfg.validate()
        with self._lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_suffix(".tmp")
            fd = os.open(str(tmp), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                json.dump(cfg.to_dict(), fh, ensure_ascii=False, indent=2)
            os.chmod(tmp, 0o600)
            os.replace(tmp, self.path)
