"""Расположение файлов приложения (по стандарту XDG)."""
from __future__ import annotations

import os
from pathlib import Path

from . import APP_ID


def _xdg(var: str, default: str) -> Path:
    value = os.environ.get(var)
    return Path(value) if value else Path.home() / default


def config_dir() -> Path:
    override = os.environ.get("EYETRACKER_CONFIG_DIR")
    path = Path(override) if override else _xdg("XDG_CONFIG_HOME", ".config") / APP_ID
    path.mkdir(parents=True, exist_ok=True)
    return path


def data_dir() -> Path:
    override = os.environ.get("EYETRACKER_DATA_DIR")
    path = Path(override) if override else _xdg("XDG_DATA_HOME", ".local/share") / APP_ID
    path.mkdir(parents=True, exist_ok=True)
    return path


def sub_dir(name: str) -> Path:
    path = data_dir() / name
    path.mkdir(parents=True, exist_ok=True)
    return path


def config_file() -> Path:
    return config_dir() / "config.json"


def models_dir() -> Path:
    return sub_dir("models")


def faces_dir() -> Path:
    return sub_dir("faces")


def sounds_dir() -> Path:
    return sub_dir("sounds")


def snapshots_dir() -> Path:
    return sub_dir("snapshots")


def events_db() -> Path:
    return data_dir() / "events.db"


def log_file() -> Path:
    return data_dir() / "eyetracker.log"


def autostart_file() -> Path:
    return _xdg("XDG_CONFIG_HOME", ".config") / "autostart" / f"{APP_ID}.desktop"
