"""Определение светлой/тёмной темы рабочего стола — для выбора цвета значков.

Меню приложений и трей рисуются панелью рабочего стола, поэтому в KDE в первую очередь
учитывается стиль Plasma (plasmarc), затем цветовая схема (kdeglobals). В GNOME —
настройка color-scheme / название темы GTK. Без Qt — можно вызывать из установщика.
"""
from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path
from typing import Dict, Optional


def _config_home() -> Path:
    return Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config")


def read_ini(path: Path) -> Dict[str, Dict[str, str]]:
    """Простой разбор INI-файлов KDE (ключи вида key[$e] тоже поддерживаются)."""
    out: Dict[str, Dict[str, str]] = {}
    section = None
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return out
    for line in text.splitlines():
        line = line.strip()
        if line.startswith("[") and line.endswith("]"):
            section = out.setdefault(line[1:-1], {})
        elif section is not None and "=" in line and not line.startswith("#"):
            k, _, v = line.partition("=")
            section[k.split("[")[0].strip()] = v.strip()
    return out


def is_light_rgb(value: str) -> Optional[bool]:
    try:
        r, g, b = (int(x) for x in value.split(",")[:3])
    except ValueError:
        return None
    return 0.299 * r + 0.587 * g + 0.114 * b >= 128


def _is_kde() -> bool:
    de = (os.environ.get("XDG_CURRENT_DESKTOP", "") + os.environ.get("DESKTOP_SESSION", "")).lower()
    return "kde" in de or "plasma" in de


def kde_light() -> Optional[bool]:
    cfg = _config_home()
    plasma = read_ini(cfg / "plasmarc").get("Theme", {}).get("name", "").lower()
    if "dark" in plasma or "twilight" in plasma:
        return False
    if "light" in plasma:
        return True
    colors = read_ini(cfg / "kdeglobals")
    bg = colors.get("Colors:Window", {}).get("BackgroundNormal")
    if bg:
        return is_light_rgb(bg)
    scheme = colors.get("General", {}).get("ColorScheme", "").lower()
    if scheme:
        return "dark" not in scheme
    if _is_kde() or (cfg / "kdeglobals").exists():
        return True        # Breeze по умолчанию — светлая
    return None


def gnome_light() -> Optional[bool]:
    if not shutil.which("gsettings"):
        return None

    def get(key: str) -> str:
        try:
            r = subprocess.run(["gsettings", "get", "org.gnome.desktop.interface", key],
                               capture_output=True, text=True, timeout=3)
            return r.stdout.strip().strip("'").lower() if r.returncode == 0 else ""
        except (OSError, subprocess.SubprocessError):
            return ""
    scheme = get("color-scheme")
    if scheme == "prefer-dark":
        return False
    gtk = get("gtk-theme")
    if gtk:
        return "dark" not in gtk
    if scheme in ("prefer-light", "default"):
        return True
    return None


def desktop_is_light() -> Optional[bool]:
    """True — светлая тема, False — тёмная, None — определить не удалось."""
    if _is_kde() or (_config_home() / "plasmarc").exists():
        v = kde_light()
        if v is not None:
            return v
    return gnome_light()


def use_black_icons(mode: str, palette_is_light: Optional[bool] = None) -> bool:
    """mode — настройка «Цвет значков»: light (белые), dark (чёрные), auto."""
    if mode == "light":
        return False
    if mode == "dark":
        return True
    light = desktop_is_light()
    if light is None:
        light = palette_is_light
    return bool(light)          # не удалось определить — исходный вариант (белый)
