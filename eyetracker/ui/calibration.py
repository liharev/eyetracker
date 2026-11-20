"""Калибровка зоны «взгляд на экран»: пользователь по очереди смотрит на 5 точек экрана."""
from __future__ import annotations

import statistics
from typing import List, Optional, Tuple

from ..i18n import tr
from ..qt import Qt, QtCore, QtGui, QtWidgets, Signal
from ..vision.gaze import GazeZone

# Доли ширины/высоты экрана
POINTS = [(0.5, 0.5), (0.06, 0.06), (0.94, 0.06), (0.94, 0.94), (0.06, 0.94)]
SETTLE_MS = 1300
COLLECT_MS = 2000
MIN_SAMPLES = 3


class CalibrationWindow(QtWidgets.QWidget):
    calibrated = Signal(object)

    def __init__(self, engine, margin: float):
        super().__init__(None, Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint)
        self.engine = engine
        self.margin = margin
        self.setCursor(Qt.CursorShape.BlankCursor)
        self.idx = -1
        self.phase = "intro"
        self.samples: List[Tuple[float, float]] = []
        self.results: List[Tuple[float, float]] = []
        self.error = ""
        self._collect_from = 0.0
        self._timer = QtCore.QTimer(self)
        self._timer.timeout.connect(self._poll)

    def start(self) -> None:
        self.engine.calibration_mode = True
        screen = QtGui.QGuiApplication.primaryScreen()
        self.setGeometry(screen.geometry())
        self.showFullScreen()
        self.raise_()
        self.activateWindow()
        QtCore.QTimer.singleShot(2500, self._next_point)

    def keyPressEvent(self, ev):  # noqa: N802
        if ev.key() == Qt.Key.Key_Escape:
            self._finish(None, tr("Калибровка отменена"))

    def _next_point(self) -> None:
        if self.phase == "done":
            return
        self.idx += 1
        if self.idx >= len(POINTS):
            try:
                zone = GazeZone.from_points(self.results, self.margin)
                self._finish(zone, "")
            except ValueError as exc:
                self._finish(None, str(exc))
            return
        self.phase = "settle"
        self.samples = []
        self.update()
        QtCore.QTimer.singleShot(SETTLE_MS, self._begin_collect)

    def _begin_collect(self) -> None:
        if self.phase == "done":
            return
        self.phase = "collect"
        self._collect_from = QtCore.QDateTime.currentMSecsSinceEpoch()
        latest = self.engine.latest_gaze()
        self._last_t = latest[0] if latest else -1.0
        self._timer.start(50)
        QtCore.QTimer.singleShot(COLLECT_MS, self._end_collect)
        self.update()

    def _poll(self) -> None:
        latest = self.engine.latest_gaze()
        if latest and latest[0] != self._last_t:
            self._last_t = latest[0]
            s = latest[1]
            if not s.eyes_closed:
                self.samples.append((s.yaw, s.pitch))

    def _end_collect(self) -> None:
        if self.phase == "done":
            return
        self._timer.stop()
        if len(self.samples) < MIN_SAMPLES:
            self._finish(None, tr("Не удалось определить взгляд: лицо не найдено или плохо освещено. "
                                  "Сядьте перед камерой и повторите."))
            return
        self.results.append((statistics.median(s[0] for s in self.samples),
                             statistics.median(s[1] for s in self.samples)))
        self._next_point()

    def _finish(self, zone: Optional[GazeZone], error: str) -> None:
        self.phase = "done"
        self._timer.stop()
        self.engine.calibration_mode = False
        self.error = error
        self.close()
        self.calibrated.emit(zone)

    def paintEvent(self, ev):  # noqa: N802
        p = QtGui.QPainter(self)
        p.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)
        p.fillRect(self.rect(), QtGui.QColor("#101418"))
        p.setPen(QtGui.QColor("#dddddd"))
        f = p.font()
        f.setPixelSize(max(18, self.height() // 40))
        p.setFont(f)
        if self.phase == "intro":
            p.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter,
                       tr("Калибровка взгляда\n\nСядьте в обычное рабочее положение.\n"
                          "Смотрите на появляющиеся точки (только глазами и головой — как при работе).\n"
                          "Esc — отмена."))
            return
        if 0 <= self.idx < len(POINTS):
            fx, fy = POINTS[self.idx]
            c = QtCore.QPointF(fx * self.width(), fy * self.height())
            r = max(14, self.height() // 45)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QtGui.QColor("#ff3b30" if self.phase == "collect" else "#ffcc00"))
            p.drawEllipse(c, r, r)
            p.setBrush(QtGui.QColor("white"))
            p.drawEllipse(c, r / 3, r / 3)
            p.setPen(QtGui.QColor("#888888"))
            p.drawText(self.rect().adjusted(0, 0, 0, -40), Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignBottom,
                       tr("Точка {i} из {n}", i=self.idx + 1, n=len(POINTS)))
