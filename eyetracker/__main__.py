"""Точка входа: python3 -m eyetracker [--settings | --download-models | --check]"""
from __future__ import annotations

import argparse
import logging
import logging.handlers
import os
import signal
import sys

from .resources import limit_threads_env

limit_threads_env(1)  # до импорта numpy/cv2/LiteRT

from . import __version__, paths  # noqa: E402


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
    from .i18n import tr

    rc = 0
    for key in models.MODELS:
        path = models.find(key)
        if path:
            print(tr("[есть]   {key}: {path}", key=key, path=path))
            continue
        try:
            print(tr("[готово] {key}: {path}", key=key, path=models.download(key)))
        except Exception as exc:  # noqa: BLE001
            print(tr("[ошибка] {key}: {error}", key=key, error=exc))
            rc = 1 if models.MODELS[key].required else rc
    return rc


def cmd_check() -> int:
    import glob
    import importlib.util
    import shutil
    from importlib.metadata import PackageNotFoundError, version

    from . import models, npu
    from .i18n import app_name, tr
    from .locker import ScreenLocker, candidate_commands
    from .resources import efficiency_cores

    yes, no = tr("да"), tr("нет")
    print(f"{app_name()} {__version__}, Python {sys.version.split()[0]}")
    try:
        import cv2
        print(f"OpenCV {cv2.__version__}: YuNet={yes if hasattr(cv2, 'FaceDetectorYN') else no.upper()}")
    except ImportError:
        print(tr("OpenCV: НЕ УСТАНОВЛЕН"))
    try:
        if importlib.util.find_spec("ai_edge_litert") is None:
            raise PackageNotFoundError
        print(tr("LiteRT {v}: модель точек лица выполняется через LiteRT (быстрее)", v=version("ai-edge-litert")))
    except (PackageNotFoundError, ValueError):
        print(tr("LiteRT: нет — модель точек лица будет выполняться через OpenCV DNN (медленнее, но работает)"))
    try:
        from .qt import QT_API
        print(f"Qt: {QT_API}")
    except ImportError:
        print(tr("Qt: НЕ УСТАНОВЛЕН (нужен python3-pyqt5 или PySide6)"))
    for key in models.MODELS:
        print(tr("Модель {key}: {path}", key=key,
                 path=models.find(key) or tr("нет (python3 -m eyetracker --download-models)")))
    ok, why = npu.availability()
    rknn = [n for n in ("yunet_320x256.rknn", "yunet_128x128.rknn", "sface_112.rknn", "face_landmarks_256.rknn")
            if models.find_rknn(n)]
    print(tr("NPU RK3588: {why}; модели .rknn: {n} из 4", why=why, n=len(rknn))
          + (tr(" — нейросети будут выполняться на NPU") if ok and len(rknn) == 4 else ""))
    print(tr("Камеры:"), ", ".join(sorted(glob.glob("/dev/video*"))) or tr("не найдены"))
    print(tr("Команды блокировки:"), "; ".join(" ".join(c) for c in candidate_commands()) or tr("не найдены"))
    print(tr("Состояние блокировки определяется:"), yes if ScreenLocker().is_locked() is not None else no)
    players = [p for p in ("paplay", "pw-play", "ffplay", "mpv", "aplay") if shutil.which(p)]
    print(tr("Проигрыватели звука:"), ", ".join(players) or tr("не найдены"))
    print(tr("Энергоэффективные ядра:"), efficiency_cores() or tr("система однородная"))
    print(tr("Сеанс:"), os.environ.get("XDG_SESSION_TYPE", "?"), os.environ.get("XDG_CURRENT_DESKTOP", "?"))
    return 0


def cmd_install_icons() -> int:
    """Значки, пункт меню приложений и автозапуск; обновление кэшей меню и значков."""
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from . import autostart, theme
    from .config import ConfigStore
    from .qt import QtGui

    app = QtGui.QGuiApplication([sys.argv[0]])  # нужен для отрисовки значков
    general = ConfigStore().load().general
    black = theme.use_black_icons(general.tray_icon_color)
    autostart.ensure_desktop_integration(general.autostart, black, wait=True)
    print(autostart.menu_file())
    print(autostart.icon_path(black))
    del app
    return 0


def main(argv=None) -> int:
    from . import i18n
    from .config import ConfigStore
    from .i18n import app_name, tr

    i18n.set_language(ConfigStore().load().general.language)
    parser = argparse.ArgumentParser(prog="eyetracker", description=f"{app_name()} {__version__}")
    parser.add_argument("--settings", action="store_true", help=tr("открыть настройки (в т.ч. у запущенного экземпляра)"))
    parser.add_argument("--download-models", action="store_true", help=tr("загрузить модели нейросетей и выйти"))
    parser.add_argument("--check", action="store_true", help=tr("проверить окружение и выйти"))
    parser.add_argument("--install-icons", action="store_true", help=tr("обновить значки и пункт меню и выйти"))
    parser.add_argument("--no-download", action="store_true", help=tr("не загружать модели автоматически"))
    parser.add_argument("--debug", action="store_true", help=tr("подробный журнал"))
    parser.add_argument("--version", action="version", version=__version__)
    args = parser.parse_args(argv)

    if args.download_models:
        logging.basicConfig(level=logging.INFO)
        return cmd_download()
    if args.check:
        return cmd_check()
    if args.install_icons:
        return cmd_install_icons()

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
