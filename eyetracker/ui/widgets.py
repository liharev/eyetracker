"""Вспомогательные виджеты."""
from __future__ import annotations

from typing import Optional

import numpy as np

from ..i18n import tr
from ..qt import Qt, QtGui, QtWidgets


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
        self.setText(tr("Нет изображения с камеры"))

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
