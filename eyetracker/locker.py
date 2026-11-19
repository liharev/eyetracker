"""Блокировка экрана и определение, заблокирован ли он, для разных окружений Linux."""
from __future__ import annotations

import logging
import os
import shlex
import shutil
import subprocess
import threading
import time
from typing import List, Optional, Sequence

log = logging.getLogger(__name__)

_DBUS_SS = ["org.freedesktop.ScreenSaver", "/org/freedesktop/ScreenSaver", "org.freedesktop.ScreenSaver"]
_DBUS_GNOME = ["org.gnome.ScreenSaver", "/org/gnome/ScreenSaver", "org.gnome.ScreenSaver"]


def _desktop() -> str:
    return (os.environ.get("XDG_CURRENT_DESKTOP", "") + ":" + os.environ.get("DESKTOP_SESSION", "")).lower()


def _gdbus_call(service, path, iface, method) -> List[str]:
    return ["gdbus", "call", "--session", "--dest", service, "--object-path", path, "--method", f"{iface}.{method}"]


def _dbus_send(service, path, iface, method) -> List[str]:
    return ["dbus-send", "--session", "--print-reply", f"--dest={service}", path, f"{iface}.{method}"]


def candidate_commands() -> List[List[str]]:
    """Команды блокировки в порядке предпочтения для текущего окружения."""
    de = _desktop()
    cmds: List[List[str]] = []
    if "xfce" in de:
        cmds.append(["xflock4"])
    if "gnome" in de or "unity" in de or "ubuntu" in de:
        cmds.append(_gdbus_call(*_DBUS_GNOME, "Lock"))
    if "kde" in de or "plasma" in de:
        cmds.append(["loginctl", "lock-session"])
    if "lxqt" in de:
        cmds.append(["lxqt-leave", "--lockscreen"])
    if "mate" in de:
        cmds.append(["mate-screensaver-command", "-l"])
    if "cinnamon" in de:
        cmds.append(["cinnamon-screensaver-command", "-l"])
    cmds += [
        _gdbus_call(*_DBUS_SS, "Lock"),
        _dbus_send(*_DBUS_SS, "Lock"),
        ["xflock4"],
        ["light-locker-command", "-l"],
        ["xscreensaver-command", "-lock"],
        ["dm-tool", "lock"],
        ["loginctl", "lock-session"],
        ["xdg-screensaver", "lock"],
    ]
    seen, result = set(), []
    for c in cmds:
        key = tuple(c)
        if key not in seen and shutil.which(c[0]):
            seen.add(key)
            result.append(c)
    return result


def _run(cmd: Sequence[str], timeout: float = 5.0) -> Optional[subprocess.CompletedProcess]:
    try:
        return subprocess.run(list(cmd), capture_output=True, text=True, timeout=timeout)
    except (OSError, subprocess.SubprocessError) as exc:
        log.debug("Команда %s не выполнена: %s", cmd, exc)
        return None


class ScreenLocker:
    def __init__(self, method: str = "auto", custom_command: str = ""):
        self.method = method
        self.custom_command = custom_command
        self._working: Optional[List[str]] = None
        self._state_cache: Optional[bool] = None
        self._state_t = 0.0
        self._lock = threading.Lock()

    def configure(self, method: str, custom_command: str) -> None:
        with self._lock:
            if (method, custom_command) != (self.method, self.custom_command):
                self.method, self.custom_command = method, custom_command
                self._working = None

    # ------------------------------------------------------------------
    def lock(self) -> bool:
        with self._lock:
            if self.method == "custom" and self.custom_command.strip():
                proc = _run(["/bin/sh", "-c", self.custom_command])
                ok = proc is not None and proc.returncode == 0
                if not ok:
                    log.error("Пользовательская команда блокировки завершилась с ошибкой: %s",
                              proc.stderr.strip() if proc else "не запущена")
                self._state_cache = True if ok else self._state_cache
                return ok
            commands = ([self._working] if self._working else []) + candidate_commands()
            for cmd in commands:
                proc = _run(cmd)
                if proc is not None and proc.returncode == 0:
                    if self._working != cmd:
                        log.info("Блокировка экрана командой: %s", shlex.join(cmd))
                    self._working = cmd
                    self._state_cache = True
                    self._state_t = time.monotonic()
                    return True
                log.debug("Не удалось заблокировать командой %s", cmd)
            log.error("Не найдено работающей команды блокировки экрана. Укажите свою в настройках.")
            return False

    # ------------------------------------------------------------------
    def is_locked(self, max_age_s: float = 1.0) -> Optional[bool]:
        """True/False, если состояние удалось определить; None — неизвестно."""
        now = time.monotonic()
        if now - self._state_t < max_age_s:
            return self._state_cache
        state = self._query()
        self._state_cache, self._state_t = state, now
        return state

    @staticmethod
    def _query() -> Optional[bool]:
        results: List[bool] = []
        if shutil.which("gdbus"):
            for spec in (_DBUS_SS, _DBUS_GNOME):
                proc = _run(_gdbus_call(*spec, "GetActive"), timeout=2.0)
                if proc is not None and proc.returncode == 0:
                    out = proc.stdout.strip().lower()
                    if "true" in out:
                        return True
                    if "false" in out:
                        results.append(False)
        sid = os.environ.get("XDG_SESSION_ID")
        if sid and shutil.which("loginctl"):
            proc = _run(["loginctl", "show-session", sid, "-p", "LockedHint", "--value"], timeout=2.0)
            if proc is not None and proc.returncode == 0:
                val = proc.stdout.strip().lower()
                if val == "yes":
                    return True
                # LockedHint=no не всегда достоверно (не все окружения его выставляют),
                # поэтому учитываем только вместе с ответом D-Bus
        if results:
            return False
        return None
