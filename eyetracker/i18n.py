"""Язык интерфейса: русский (исходный текст) и английский (словарь i18n_en.EN).

    tr("Перед экраном никого нет")                    → строка на текущем языке
    tr("Лиц в кадре: {n}", n=3)                       → с подстановкой значений
"""
from __future__ import annotations

import os
from typing import Dict

LANGUAGES = ("system", "ru", "en")
_lang = "ru"
_en: Dict[str, str] = {}


def system_language() -> str:
    """ru, если язык системы русский, иначе en."""
    for var in ("LANGUAGE", "LC_ALL", "LC_MESSAGES", "LANG"):
        value = os.environ.get(var, "")
        if value and value not in ("C", "POSIX", "C.UTF-8"):
            return "ru" if value.lower().startswith("ru") else "en"
    try:
        from .qt import QtCore

        return "ru" if QtCore.QLocale.system().name().lower().startswith("ru") else "en"
    except Exception:  # noqa: BLE001
        return "en"


def resolve(setting: str) -> str:
    return setting if setting in ("ru", "en") else system_language()


def set_language(code: str) -> str:
    global _lang, _en
    _lang = resolve(code)
    if _lang == "en" and not _en:
        from .i18n_en import EN

        _en = EN
    return _lang


def language() -> str:
    return _lang


def tr(text: str, /, **values) -> str:
    s = _en.get(text, text) if _lang == "en" else text
    return s.format(**values) if values else s


def app_name() -> str:
    return tr("CAMAI бдительность")
