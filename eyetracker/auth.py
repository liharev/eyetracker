"""Проверка логина/пароля для входа в настройки (PBKDF2-SHA256)."""
from __future__ import annotations

import hashlib
import hmac
import secrets
import threading
import time
from typing import Tuple

from .config import AuthConfig

MAX_FAILURES = 5
LOCKOUT_S = 60.0


def hash_password(password: str, salt_hex: str, iterations: int) -> str:
    dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), bytes.fromhex(salt_hex), iterations)
    return dk.hex()


def set_credentials(auth: AuthConfig, username: str, password: str) -> None:
    if not username.strip():
        raise ValueError("Логин не может быть пустым")
    if len(password) < 4:
        raise ValueError("Пароль должен содержать не менее 4 символов")
    auth.username = username.strip()
    auth.salt = secrets.token_hex(16)
    auth.iterations = max(auth.iterations, 100_000)
    auth.password_hash = hash_password(password, auth.salt, auth.iterations)


def is_configured(auth: AuthConfig) -> bool:
    return bool(auth.username and auth.password_hash and auth.salt)


def verify(auth: AuthConfig, username: str, password: str) -> bool:
    if not is_configured(auth):
        return False
    candidate = hash_password(password, auth.salt, auth.iterations)
    user_ok = hmac.compare_digest(username.strip().encode(), auth.username.encode())
    pass_ok = hmac.compare_digest(candidate, auth.password_hash)
    return user_ok and pass_ok


class LoginGuard:
    """Ограничение перебора: после MAX_FAILURES неудач — пауза LOCKOUT_S."""

    def __init__(self, max_failures: int = MAX_FAILURES, lockout_s: float = LOCKOUT_S, clock=time.monotonic):
        self.max_failures = max_failures
        self.lockout_s = lockout_s
        self._clock = clock
        self._failures = 0
        self._locked_until = 0.0
        self._lock = threading.Lock()

    def remaining_lockout(self) -> float:
        with self._lock:
            return max(0.0, self._locked_until - self._clock())

    def attempt(self, auth: AuthConfig, username: str, password: str) -> Tuple[bool, str]:
        wait = self.remaining_lockout()
        if wait > 0:
            return False, f"Слишком много неудачных попыток. Повторите через {int(wait) + 1} с."
        ok = verify(auth, username, password)
        with self._lock:
            if ok:
                self._failures = 0
                return True, ""
            self._failures += 1
            if self._failures >= self.max_failures:
                self._failures = 0
                self._locked_until = self._clock() + self.lockout_s
                return False, f"Неверный логин или пароль. Вход заблокирован на {int(self.lockout_s)} с."
        return False, "Неверный логин или пароль."
