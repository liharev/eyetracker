"""Интеграция с рабочим столом: автозапуск, пункт меню приложений, значки.

Пункт меню и значки проверяются при каждом запуске программы и при установке: если они
отсутствуют или устарели (например, после обновления программы), они перезаписываются,
а кэши меню и значков рабочего стола (KDE, GNOME и др.) обновляются.
"""
from __future__ import annotations

import logging
import os
import shlex
import shutil
import subprocess
import sys
import threading
from pathlib import Path

from . import icons, paths

log = logging.getLogger(__name__)

_COMMON = """Name=CAMAI vigilance{suffix_en}
Name[ru]=CAMAI бдительность{suffix_ru}
Comment=Presence, face recognition and gaze control in front of the screen
Comment[ru]=Контроль присутствия, распознавание лиц и контроль взгляда перед экраном
Exec={exec}
Icon={icon}
Terminal=false
"""

AUTOSTART = "[Desktop Entry]\nType=Application\n" + _COMMON + \
    "X-GNOME-Autostart-enabled=true\nX-GNOME-Autostart-Delay=5\n"
MENU = "[Desktop Entry]\nType=Application\n" + _COMMON + "Categories=Utility;Security;\n" \
    "StartupWMClass=eyetracker\n"
MENU_FILE = "eyetracker-settings.desktop"


def _data_home() -> Path:
    return Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share")


def icons_base() -> Path:
    return _data_home() / "icons"


def menu_file() -> Path:
    return _data_home() / "applications" / MENU_FILE


def icon_path(black: bool = False) -> Path:
    return icons_base() / "hicolor" / "scalable" / "apps" / f"{icons.icon_id(black)}.svg"


def icon_ref(black: bool = False) -> str:
    """Полный путь к значку (меню не зависит от кэша темы значков) или имя значка."""
    p = icon_path(black)
    return str(p) if p.exists() else icons.icon_id(black)


def exec_line(*args: str) -> str:
    return " ".join([shlex.quote(sys.executable), "-m", "eyetracker", *args])


def _write_if_changed(path: Path, content: str) -> bool:
    if path.exists() and path.read_text(encoding="utf-8", errors="replace") == content:
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return True


def ensure_icons() -> bool:
    """Значки в ~/.local/share/icons; True — если что-то было (пере)записано. Нужен QGuiApplication."""
    sizes = (16, 22, 24, 32, 48, 64, 128, 256)
    svg_ok = all(icon_path(b).exists() and icon_path(b).read_text(encoding="utf-8", errors="replace")
                 == icons.svg(ring=icons.ring_color(b)) for b in (False, True))
    pngs_ok = all((icons_base() / "hicolor" / f"{s}x{s}" / "apps" / f"{icons.icon_id(b)}.png").exists()
                  for s in sizes for b in (False, True))
    if svg_ok and pngs_ok:
        return False
    icons.install_desktop_icons(icons_base(), sizes)
    return True


def ensure_menu_entry(black: bool = False) -> bool:
    content = MENU.format(exec=exec_line("--settings"), icon=icon_ref(black),
                          suffix_en=" — settings", suffix_ru=" — настройки")
    return _write_if_changed(menu_file(), content)


def set_enabled(enabled: bool, black: bool = False) -> None:
    path = paths.autostart_file()
    if enabled:
        _write_if_changed(path, AUTOSTART.format(exec=exec_line(), icon=icon_ref(black), suffix_en="", suffix_ru=""))
    elif path.exists():
        path.unlink()


def refresh_caches(icons_changed: bool, wait: bool = False) -> None:
    """Обновить кэш меню приложений и значков рабочего стола."""
    cmds = []
    for tool in ("kbuildsycoca6", "kbuildsycoca5"):          # KDE Plasma 6 / 5
        if shutil.which(tool):
            cmds.append([tool])
            break
    if shutil.which("update-desktop-database"):
        cmds.append(["update-desktop-database", str(menu_file().parent)])
    if shutil.which("xdg-desktop-menu"):
        cmds.append(["xdg-desktop-menu", "forceupdate"])
    if icons_changed:
        kcache = Path(os.environ.get("XDG_CACHE_HOME") or Path.home() / ".cache") / "icon-cache.kcache"
        try:
            kcache.unlink()                                    # KDE пересоздаст кэш значков
        except OSError:
            pass
        try:
            os.utime(icons_base() / "hicolor")                 # признак изменения темы значков
        except OSError:
            pass

    def run():
        for cmd in cmds:
            try:
                subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=60)
            except (OSError, subprocess.SubprocessError) as exc:
                log.debug("%s: %s", cmd[0], exc)

    if wait:
        run()
    else:
        threading.Thread(target=run, name="desktop-cache", daemon=True).start()


def ensure_desktop_integration(autostart: bool, black: bool = False, wait: bool = False) -> bool:
    """Значки, пункт меню и автозапуск в актуальном состоянии; True — если что-то обновлено.
    black — чёрный вариант значка (для светлой темы оформления)."""
    changed_icons = False
    try:
        changed_icons = ensure_icons()
    except Exception as exc:  # noqa: BLE001
        log.warning("Не удалось установить значки: %s", exc)
    changed_menu = False
    try:
        changed_menu = ensure_menu_entry(black)
        set_enabled(autostart, black)
    except OSError as exc:
        log.warning("Не удалось обновить пункт меню/автозапуск: %s", exc)
    if changed_icons or changed_menu:
        log.info("Пункт меню и значки обновлены (%s)", menu_file())
        refresh_caches(changed_icons, wait)
    return changed_icons or changed_menu
