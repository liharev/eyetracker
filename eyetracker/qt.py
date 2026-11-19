"""Тонкая прослойка совместимости PySide6 / PyQt5.

Предпочтение отдаётся системному PyQt5 (пакет python3-pyqt5): на Radxa OS/KDE
библиотеки Qt5 уже загружены рабочим столом, поэтому расход памяти минимален.
Если PyQt5 нет — используется PySide6. Выбор можно задать: EYETRACKER_QT=pyqt5|pyside6.
"""
from __future__ import annotations

import os

_forced = os.environ.get("EYETRACKER_QT", "").lower()

QT_API = ""
if _forced in ("", "pyqt5"):
    try:
        from PyQt5 import QtCore, QtGui, QtWidgets, QtNetwork  # noqa: F401
        from PyQt5.QtCore import pyqtSignal as Signal, pyqtSlot as Slot  # noqa: F401

        QT_API = "pyqt5"
    except ImportError:
        if _forced == "pyqt5":
            raise
if not QT_API:
    from PySide6 import QtCore, QtGui, QtWidgets, QtNetwork  # noqa: F401
    from PySide6.QtCore import Signal, Slot  # noqa: F401

    QT_API = "pyside6"

Qt = QtCore.Qt


def exec_(obj, *args):
    """exec() / exec_() в зависимости от привязки."""
    fn = getattr(obj, "exec", None) or getattr(obj, "exec_")
    return fn(*args)
