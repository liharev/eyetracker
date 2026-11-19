"""Вспомогательные виджеты."""
from __future__ import annotations

from typing import Optional

import numpy as np

from ..qt import Qt, QtCore, QtGui, QtWidgets


def bgr_to_pixmap(img: np.ndarray) -> QtGui.QPixmap:
    img = np.ascontiguousarray(img)
    h, w = img.shape[:2]
    qimg = QtGui.QImage(img.data, w, h, 3 * w, QtGui.QImage.Format.Format_BGR888)
    return QtGui.QPixmap.fromImage(qimg.copy())


class FrameView(QtWidgets.QLabel):
    def __init__(self, parent=None, min_w: int = 480, min_h: int = 360):
        super().__init__(parent)
        self.setMinimumSize(min_w, min_h)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setStyleSheet("background:#202020; color:#bbb;")
        self.setText("Нет изображения с камеры")

    def show_frame(self, img: Optional[np.ndarray]) -> None:
        if img is None:
            return
        pm = bgr_to_pixmap(img)
        self.setPixmap(pm.scaled(self.size(), Qt.AspectRatioMode.KeepAspectRatio,
                                 Qt.TransformationMode.SmoothTransformation))


def dspin(lo: float, hi: float, step: float = 1.0, decimals: int = 1, suffix: str = "") -> QtWidgets.QDoubleSpinBox:
    w = QtWidgets.QDoubleSpinBox()
    w.setRange(lo, hi)
    w.setSingleStep(step)
    w.setDecimals(decimals)
    if suffix:
        w.setSuffix(suffix)
    return w


def ispin(lo: int, hi: int, suffix: str = "") -> QtWidgets.QSpinBox:
    w = QtWidgets.QSpinBox()
    w.setRange(lo, hi)
    if suffix:
        w.setSuffix(suffix)
    return w


def hint(text: str) -> QtWidgets.QLabel:
    lbl = QtWidgets.QLabel(text)
    lbl.setWordWrap(True)
    lbl.setStyleSheet("color:#666;")
    return lbl


def make_icon(color: str, ring: Optional[str] = None, size: int = 64) -> QtGui.QIcon:
    """Иконка «глаз» заданного цвета (для трея)."""
    pm = QtGui.QPixmap(size, size)
    pm.fill(Qt.GlobalColor.transparent)
    p = QtGui.QPainter(pm)
    p.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)
    s = size
    path = QtGui.QPainterPath()
    path.moveTo(s * 0.04, s * 0.5)
    path.quadTo(s * 0.5, s * 0.02, s * 0.96, s * 0.5)
    path.quadTo(s * 0.5, s * 0.98, s * 0.04, s * 0.5)
    p.setPen(QtGui.QPen(QtGui.QColor("#202020"), s * 0.06))
    p.setBrush(QtGui.QColor("white"))
    p.drawPath(path)
    p.setBrush(QtGui.QColor(color))
    p.setPen(Qt.PenStyle.NoPen)
    p.drawEllipse(QtCore.QPointF(s * 0.5, s * 0.5), s * 0.2, s * 0.2)
    p.setBrush(QtGui.QColor("#101010"))
    p.drawEllipse(QtCore.QPointF(s * 0.5, s * 0.5), s * 0.08, s * 0.08)
    if ring:
        p.setPen(QtGui.QPen(QtGui.QColor(ring), s * 0.08))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawRoundedRect(int(s * 0.04), int(s * 0.04), int(s * 0.92), int(s * 0.92), s * 0.15, s * 0.15)
    p.end()
    return QtGui.QIcon(pm)
