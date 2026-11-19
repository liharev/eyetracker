"""Точка входа: python3 -m eyetracker [--settings | --download-models | --check]"""
from __future__ import annotations

import argparse
import logging
import logging.handlers
import os
import signal
import sys

from .resources import limit_threads_env

limit_threads_env(1)  # до импорта numpy/cv2/mediapipe

from . import APP_NAME, __version__, paths  # noqa: E402


def setup_logging(debug: bool) -> None:
    level = logging.DEBUG if debug else logging.INFO
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
    root = logging.getLogger()
    root.setLevel(level)
    fh = logging.handlers.RotatingFileHandler(paths.log_file(), maxBytes=2_000_000, backupCount=3,
                                              encoding="utf-8")
    fh.setFormatter(fmt)
    root.addHandler(fh)
    sh = logging.StreamHandler()
    sh.setFormatter(fmt)
    root.addHandler(sh)


def cmd_download() -> int:
    from . import models

    rc = 0
    for key in models.MODELS:
        path = models.find(key)
        if path:
            print(f"[есть]   {key}: {path}")
            continue
        try:
            print(f"[готово] {key}: {models.download(key)}")
        except Exception as exc:  # noqa: BLE001
            print(f"[ошибка] {key}: {exc}")
            rc = 1 if models.MODELS[key].required else rc
    return rc


def cmd_check() -> int:
    import glob
    import shutil

    from . import models
    from .locker import ScreenLocker, candidate_commands
    from .resources import efficiency_cores

    print(f"{APP_NAME} {__version__}, Python {sys.version.split()[0]}")
    try:
        import cv2
        print(f"OpenCV {cv2.__version__}: YuNet={'да' if hasattr(cv2, 'FaceDetectorYN') else 'НЕТ'}")
    except ImportError:
        print("OpenCV: НЕ УСТАНОВЛЕН")
    try:
        import mediapipe
        print(f"MediaPipe {mediapipe.__version__}")
    except Exception as exc:  # noqa: BLE001
        print(f"MediaPipe: нет ({exc}) — взгляд будет оцениваться по повороту головы")
    try:
        from .qt import QT_API
        print(f"Qt: {QT_API}")
    except ImportError:
        print("Qt: НЕ УСТАНОВЛЕН (нужен python3-pyqt5 или PySide6)")
    for key in models.MODELS:
        print(f"Модель {key}: {models.find(key) or 'нет (python3 -m eyetracker --download-models)'}")
    print("Камеры:", ", ".join(sorted(glob.glob("/dev/video*"))) or "не найдены")
    print("Команды блокировки:", "; ".join(" ".join(c) for c in candidate_commands()) or "не найдены")
    print("Состояние блокировки определяется:", "да" if ScreenLocker().is_locked() is not None else "нет")
    players = [p for p in ("paplay", "pw-play", "ffplay", "mpv", "aplay") if shutil.which(p)]
    print("Проигрыватели звука:", ", ".join(players) or "не найдены")
    print("Энергоэффективные ядра:", efficiency_cores() or "система однородная")
    print("Сеанс:", os.environ.get("XDG_SESSION_TYPE", "?"), os.environ.get("XDG_CURRENT_DESKTOP", "?"))
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="eyetracker", description=f"{APP_NAME} {__version__}")
    parser.add_argument("--settings", action="store_true", help="открыть настройки (в т.ч. у запущенного экземпляра)")
    parser.add_argument("--download-models", action="store_true", help="загрузить модели нейросетей и выйти")
    parser.add_argument("--check", action="store_true", help="проверить окружение и выйти")
    parser.add_argument("--no-download", action="store_true", help="не загружать модели автоматически")
    parser.add_argument("--debug", action="store_true", help="подробный журнал")
    parser.add_argument("--version", action="version", version=__version__)
    args = parser.parse_args(argv)

    if args.download_models:
        logging.basicConfig(level=logging.INFO)
        return cmd_download()
    if args.check:
        return cmd_check()

    setup_logging(args.debug)
    from .config import ConfigStore
    from .resources import apply_limits

    cfg = ConfigStore().load()
    # до создания потоков: дочерние потоки наследуют привязку к ядрам и приоритет
    apply_limits(cfg.processing.cpu_cores, cfg.processing.nice)

    if os.environ.get("XDG_SESSION_TYPE") == "wayland" and "QT_QPA_PLATFORM" not in os.environ:
        # рамка поверх всех окон и трей надёжнее работают через XWayland
        os.environ["QT_QPA_PLATFORM"] = "xcb"

    from .app import run
    from .qt import QtCore

    signal.signal(signal.SIGTERM, lambda *_: QtCore.QCoreApplication.quit())
    signal.signal(signal.SIGINT, lambda *_: QtCore.QCoreApplication.quit())
    return run(allow_download=not args.no_download, open_settings=args.settings)


if __name__ == "__main__":
    sys.exit(main())
