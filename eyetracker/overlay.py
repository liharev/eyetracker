"""Красная рамка по периметру экрана(ов) поверх любых окон.

Реализована четырьмя узкими окнами-полосами на каждый монитор: не требует
композитора/прозрачности, не перехватывает мышь и почти не нагружает систему
(перерисовка только при смене состояния или мигании).
"""
from __future__ import annotations

from typing import List

from .qt import Qt, QtCore, QtGui, QtWidgets


class _Strip(QtWidgets.QWidget):
    def __init__(self, color: QtGui.QColor):
        flags = (Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint
                 | Qt.WindowType.Tool | Qt.WindowType.WindowTransparentForInput
                 | Qt.WindowType.WindowDoesNotAcceptFocus | Qt.WindowType.X11BypassWindowManagerHint)
        super().__init__(None, flags)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        self.setAttribute(Qt.WidgetAttribute.WA_X11DoNotAcceptFocus, True)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setAutoFillBackground(True)
        self.set_color(color)

    def set_color(self, color: QtGui.QColor) -> None:
        pal = self.palette()
        pal.setColor(QtGui.QPalette.ColorRole.Window, color)
        self.setPalette(pal)


class BorderOverlay(QtCore.QObject):
    def __init__(self, width: int = 14, color: str = "#ff0000", blink_ms: int = 450, parent=None):
        super().__init__(parent)
        self._width = width
        self._color = QtGui.QColor(color)
        self._strips: List[_Strip] = []
        self._blink = False
        self._visible = False
        self._phase = True
        self._timer = QtCore.QTimer(self)
        self._timer.setInterval(blink_ms)
        self._timer.timeout.connect(self._on_blink)
        self._raise_timer = QtCore.QTimer(self)
        self._raise_timer.setInterval(2000)
        self._raise_timer.timeout.connect(self._raise_all)
        app = QtWidgets.QApplication.instance()
        app.screenAdded.connect(lambda *_: self._rebuild())
        app.screenRemoved.connect(lambda *_: self._rebuild())

    def configure(self, width: int, color: str, blink_ms: int) -> None:
        self._width = max(2, int(width))
        self._color = QtGui.QColor(color) if QtGui.QColor(color).isValid() else QtGui.QColor("#ff0000")
        self._timer.setInterval(max(100, int(blink_ms)))
        if self._strips:
            self._rebuild()

    def _rebuild(self) -> None:
        for s in self._strips:
            s.hide()
            s.deleteLater()
        self._strips = []
        if not self._visible:
            return
        w = self._width
        for screen in QtGui.QGuiApplication.screens():
            g = screen.geometry()
            rects = [
                QtCore.QRect(g.left(), g.top(), g.width(), w),
                QtCore.QRect(g.left(), g.bottom() - w + 1, g.width(), w),
                QtCore.QRect(g.left(), g.top() + w, w, g.height() - 2 * w),
                QtCore.QRect(g.right() - w + 1, g.top() + w, w, g.height() - 2 * w),
            ]
            for r in rects:
                s = _Strip(self._color)
                s.setGeometry(r)
                self._strips.append(s)
        self._apply()

    def _apply(self) -> None:
        show = self._visible and (self._phase or not self._blink)
        for s in self._strips:
            if show:
                s.show()
                s.raise_()
            else:
                s.hide()

    def _on_blink(self) -> None:
        self._phase = not self._phase
        self._apply()

    def _raise_all(self) -> None:
        if self._visible:
            for s in self._strips:
                if s.isVisible():
                    s.raise_()

    def set_state(self, visible: bool, blink: bool) -> None:
        if (visible, blink) == (self._visible, self._blink):
            return
        was_visible = self._visible
        self._visible, self._blink = visible, blink
        self._phase = True
        if visible and not was_visible:
            self._rebuild()
            self._raise_timer.start()
        elif not visible:
            self._raise_timer.stop()
            self._rebuild()
        else:
            self._apply()
        if visible and blink:
            self._timer.start()
        else:
            self._timer.stop()
