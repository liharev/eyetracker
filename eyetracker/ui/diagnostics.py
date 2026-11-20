"""Вкладка «Диагностика»: ресурсы одноплатника, используемые программой, в реальном времени."""
from __future__ import annotations

from collections import deque
from typing import Deque, List

from ..i18n import tr
from ..qt import Qt, QtCore, QtGui, QtWidgets
from ..sysmon import CoreInfo, SystemMonitor, level

COLORS = ("#2e9d3a", "#e0a000", "#d42020")   # норма / повышенная / высокая


def level_name(lvl: int) -> str:
    return (tr("норма"), tr("повышенная нагрузка"), tr("высокая нагрузка"))[lvl]


class Gauge(QtWidgets.QWidget):
    """Горизонтальная шкала с цветом уровня и подписью значения."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumSize(220, 22)
        self.setSizePolicy(QtWidgets.QSizePolicy.Policy.Expanding, QtWidgets.QSizePolicy.Policy.Fixed)
        self._frac, self._text, self._lvl = 0.0, "—", 0

    def set(self, value: float, maximum: float, text: str, lvl: int) -> None:
        self._frac = max(0.0, min(1.0, value / maximum if maximum else 0.0))
        self._text, self._lvl = text, lvl
        self.update()

    def paintEvent(self, ev):  # noqa: N802
        p = QtGui.QPainter(self)
        p.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)
        r = QtCore.QRectF(self.rect()).adjusted(1, 3, -1, -3)
        pal = self.palette()
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(pal.color(QtGui.QPalette.ColorRole.Mid).lighter(150))
        p.drawRoundedRect(r, 4, 4)
        fill = QtCore.QRectF(r.left(), r.top(), max(6.0, r.width() * self._frac) if self._frac > 0 else 0,
                             r.height())
        if self._frac > 0:
            p.setBrush(QtGui.QColor(COLORS[self._lvl]))
            p.drawRoundedRect(fill, 4, 4)
        f = p.font()
        f.setBold(True)
        p.setFont(f)
        text_rect = r.adjusted(8, 0, -8, 0)
        align = Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft
        # подпись двухцветная: белая поверх заливки, обычная — на фоне шкалы
        p.save()
        p.setClipRect(QtCore.QRectF(fill.right(), r.top(), r.right() - fill.right() + 1, r.height()))
        p.setPen(pal.color(QtGui.QPalette.ColorRole.Text))
        p.drawText(text_rect, align, self._text)
        p.restore()
        if self._frac > 0:
            p.setClipRect(fill)
            p.setPen(QtGui.QColor("white"))
            p.drawText(text_rect, align, self._text)
        p.end()


class Sparkline(QtWidgets.QWidget):
    """График значений за последние N секунд."""

    def __init__(self, capacity: int = 120, parent=None):
        super().__init__(parent)
        self.values: Deque[float] = deque(maxlen=capacity)
        self.capacity = capacity
        self.floor = 10.0
        self._lvl = 0
        self.setMinimumSize(220, 46)
        self.setSizePolicy(QtWidgets.QSizePolicy.Policy.Expanding, QtWidgets.QSizePolicy.Policy.Fixed)

    def add(self, value: float, lvl: int) -> None:
        self.values.append(value)
        self._lvl = lvl
        self.update()

    def paintEvent(self, ev):  # noqa: N802
        p = QtGui.QPainter(self)
        p.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)
        r = QtCore.QRectF(self.rect()).adjusted(1, 2, -1, -2)
        pal = self.palette()
        p.setPen(QtGui.QPen(pal.color(QtGui.QPalette.ColorRole.Mid), 1))
        p.setBrush(pal.color(QtGui.QPalette.ColorRole.Base))
        p.drawRoundedRect(r, 4, 4)
        if len(self.values) >= 2:
            top = max(self.floor, max(self.values) * 1.2)
            step = r.width() / (self.capacity - 1)
            x0 = r.right() - step * (len(self.values) - 1)
            path = QtGui.QPainterPath()
            pts = [QtCore.QPointF(x0 + i * step, r.bottom() - r.height() * min(1.0, v / top))
                   for i, v in enumerate(self.values)]
            path.moveTo(pts[0])
            for pt in pts[1:]:
                path.lineTo(pt)
            area = QtGui.QPainterPath(path)
            area.lineTo(pts[-1].x(), r.bottom())
            area.lineTo(pts[0].x(), r.bottom())
            color = QtGui.QColor(COLORS[self._lvl])
            fill = QtGui.QColor(color)
            fill.setAlpha(60)
            p.setPen(Qt.PenStyle.NoPen)
            p.fillPath(area, fill)
            p.setPen(QtGui.QPen(color, 1.6))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawPath(path)
            p.setPen(pal.color(QtGui.QPalette.ColorRole.Text))
            p.drawText(r.adjusted(6, 2, -6, -2), Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft,
                       tr("макс. {value:.1f}", value=max(self.values)))
        p.end()


class CoreBars(QtWidgets.QWidget):
    """Загрузка каждого ядра CPU; ядра, на которых разрешено работать программе, выделены рамкой."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.cores: List[CoreInfo] = []
        self.setMinimumSize(220, 96)
        self.setSizePolicy(QtWidgets.QSizePolicy.Policy.Expanding, QtWidgets.QSizePolicy.Policy.Fixed)

    def set(self, cores: List[CoreInfo]) -> None:
        self.cores = cores
        tips = [f"cpu{c.index} {c.kind}: {c.load:.0f}%" + (f", {c.freq_mhz} MHz" if c.freq_mhz else "")
                + ("" if c.allowed else tr(" (программе не разрешено)")) for c in cores]
        self.setToolTip("\n".join(tips))
        self.update()

    def paintEvent(self, ev):  # noqa: N802
        if not self.cores:
            return
        p = QtGui.QPainter(self)
        p.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)
        pal = self.palette()
        n = len(self.cores)
        label_h = 30
        w = self.width() / n
        h = self.height() - label_h
        for i, c in enumerate(self.cores):
            x = i * w + 3
            bw = w - 6
            back = QtCore.QRectF(x, 2, bw, h - 2)
            p.setPen(QtGui.QPen(pal.color(QtGui.QPalette.ColorRole.Highlight), 2) if c.allowed else Qt.PenStyle.NoPen)
            p.setBrush(pal.color(QtGui.QPalette.ColorRole.Mid).lighter(150))
            p.drawRoundedRect(back, 3, 3)
            fh = (h - 4) * min(1.0, c.load / 100.0)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QtGui.QColor(COLORS[level("core", c.load)]))
            p.drawRoundedRect(QtCore.QRectF(x + 2, h - fh, bw - 4, fh), 2, 2)
            p.setPen(pal.color(QtGui.QPalette.ColorRole.Text))
            f = p.font()
            f.setPointSizeF(max(6.0, f.pointSizeF() * 0.8))
            p.setFont(f)
            p.drawText(QtCore.QRectF(i * w, h, w, label_h / 2), Qt.AlignmentFlag.AlignCenter, f"{c.load:.0f}%")
            p.drawText(QtCore.QRectF(i * w, h + label_h / 2, w, label_h / 2), Qt.AlignmentFlag.AlignCenter,
                       f"{c.index} {c.kind}".strip())
        p.end()


def _group(title: str):
    box = QtWidgets.QGroupBox(title)
    form = QtWidgets.QFormLayout(box)
    form.setFieldGrowthPolicy(QtWidgets.QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
    return box, form


class DiagnosticsTab(QtWidgets.QWidget):
    def __init__(self, app, parent=None):
        super().__init__(parent)
        self.app = app
        self.mon = SystemMonitor()
        v = QtWidgets.QVBoxLayout(self)

        self.summary = QtWidgets.QLabel()
        self.summary.setWordWrap(True)
        v.addWidget(self.summary)

        box, f = _group(tr("Процессор (CPU)"))
        self.cpu_prog, self.cpu_sys = Gauge(), Gauge()
        self.cpu_hist = Sparkline()
        self.cores = CoreBars()
        self.cpu_info = QtWidgets.QLabel()
        f.addRow(tr("Программа:"), self.cpu_prog)
        f.addRow(tr("Вся система:"), self.cpu_sys)
        f.addRow(tr("Программа, 2 мин:"), self.cpu_hist)
        f.addRow(tr("Ядра:"), self.cores)
        f.addRow("", self.cpu_info)
        v.addWidget(box)

        box, f = _group(tr("Нейропроцессор (NPU)"))
        self.npu_state = QtWidgets.QLabel()
        self.npu_state.setWordWrap(True)
        self.npu_prog = Gauge()
        self.npu_hist = Sparkline()
        self.npu_sys = Gauge()
        self.npu_sys_label = QtWidgets.QLabel(tr("Загрузка NPU (вся система):"))
        self.npu_info = QtWidgets.QLabel()
        self.npu_info.setWordWrap(True)
        f.addRow(tr("Состояние:"), self.npu_state)
        f.addRow(tr("Занятость NPU программой:"), self.npu_prog)
        f.addRow(tr("Программа, 2 мин:"), self.npu_hist)
        f.addRow(self.npu_sys_label, self.npu_sys)
        f.addRow("", self.npu_info)
        v.addWidget(box)

        box, f = _group(tr("Оперативная память (RAM)"))
        self.mem_prog, self.mem_sys, self.mem_swap = Gauge(), Gauge(), Gauge()
        self.swap_label = QtWidgets.QLabel(tr("Подкачка (swap):"))
        f.addRow(tr("Программа:"), self.mem_prog)
        f.addRow(tr("Вся система:"), self.mem_sys)
        f.addRow(self.swap_label, self.mem_swap)
        v.addWidget(box)

        box, self.temp_form = _group(tr("Температура"))
        self.temp_gauges = {}
        self.temp_none = QtWidgets.QLabel(tr("Датчики температуры недоступны"))
        self.temp_form.addRow(self.temp_none)
        v.addWidget(box)

        box, f = _group(tr("Камера и обработка"))
        self.cam_state = QtWidgets.QLabel()
        self.proc_gauge = Gauge()
        self.proc_info = QtWidgets.QLabel()
        self.proc_info.setWordWrap(True)
        f.addRow(tr("Камера:"), self.cam_state)
        f.addRow(tr("Время обработки кадра:"), self.proc_gauge)
        f.addRow("", self.proc_info)
        v.addWidget(box)

        box, f = _group(tr("Диск и почта"))
        self.disk = Gauge()
        self.disk_info = QtWidgets.QLabel()
        self.mail_info = QtWidgets.QLabel()
        self.mail_info.setWordWrap(True)
        f.addRow(tr("Свободно на диске:"), self.disk)
        f.addRow("", self.disk_info)
        f.addRow(tr("Почта:"), self.mail_info)
        v.addWidget(box)
        hint = QtWidgets.QLabel(tr("Цвет: зелёный — норма, жёлтый — повышенная нагрузка, красный — высокая. "
                                   "Данные обновляются раз в секунду, пока открыта эта вкладка."))
        hint.setWordWrap(True)
        hint.setStyleSheet("color:#666;")
        v.addWidget(hint)
        v.addStretch(1)

        self._timer = QtCore.QTimer(self)
        self._timer.setInterval(1000)
        self._timer.timeout.connect(self.refresh)

    def showEvent(self, ev):  # noqa: N802
        self.mon.sample()
        self._timer.start()
        QtCore.QTimer.singleShot(300, self.refresh)
        super().showEvent(ev)

    def hideEvent(self, ev):  # noqa: N802
        self._timer.stop()
        super().hideEvent(ev)

    def stop(self) -> None:
        self._timer.stop()

    # ------------------------------------------------------------------
    def refresh(self) -> None:
        s = self.mon.sample()
        eng = self.app.engine
        st = eng.status
        levels = []

        lvl = level("proc_cpu", s.proc_cpu)
        levels.append(lvl)
        self.cpu_prog.set(s.proc_cpu, 100, tr("{v:.1f}% одного ядра ({t:.1f}% всех ядер)", v=s.proc_cpu,
                                                t=s.proc_cpu_total), lvl)
        self.cpu_hist.add(s.proc_cpu, lvl)
        lvl = level("sys_cpu", s.sys_cpu)
        levels.append(lvl)
        self.cpu_sys.set(s.sys_cpu, 100, f"{s.sys_cpu:.0f}%", lvl)
        self.cores.set(s.cores)
        allowed = [str(c.index) for c in s.cores if c.allowed]
        self.cpu_info.setText(tr("Потоков: {threads}; приоритет (nice): {nice}; программе разрешены ядра: {cores}",
                                 threads=s.threads, nice=s.nice,
                                 cores=", ".join(allowed) if len(allowed) < len(s.cores) else tr("все")))

        if eng.npu_active:
            self.npu_state.setText(tr("используется — нейросети выполняются на NPU"))
        elif s.npu_available:
            self.npu_state.setText(tr("доступен, но не используется (в настройках выбран CPU или ошибка: {err})",
                                      err=eng.npu_error or "—"))
        else:
            self.npu_state.setText(tr("недоступен — нейросети выполняются на CPU ({why})",
                                      why=s.npu_note or eng.npu_error or tr("нет NPU")))
        lvl = level("npu", s.npu_prog_pct)
        levels.append(lvl)
        self.npu_prog.set(s.npu_prog_pct, 100, f"{s.npu_prog_pct:.1f}%", lvl)
        self.npu_hist.add(s.npu_prog_pct, lvl)
        if s.npu_sys_load:
            avg = sum(s.npu_sys_load) / len(s.npu_sys_load)
            self.npu_sys.set(avg, 100, " / ".join(f"{x}%" for x in s.npu_sys_load), level("npu", avg))
        else:
            self.npu_sys.set(0, 100, tr("недоступно без прав администратора"), 0)
        parts = []
        if s.npu_freq_mhz:
            parts.append(tr("частота NPU: {f} МГц", f=s.npu_freq_mhz))
        if s.npu_models:
            parts.append(tr("время вызова: {items}",
                            items="; ".join(f"{k.replace('.rknn', '')} {v:.1f} ms" for k, v in sorted(s.npu_models.items()))))
        self.npu_info.setText(" · ".join(parts))

        lvl = level("rss_mb", s.rss_mb)
        levels.append(lvl)
        self.mem_prog.set(s.rss_mb, max(1024.0, s.rss_mb), tr("{mb:.0f} МБ", mb=s.rss_mb), lvl)
        lvl = level("mem_pct", s.mem_used_pct)
        levels.append(lvl)
        self.mem_sys.set(s.mem_used_pct, 100, tr("{p:.0f}% из {gb:.1f} ГБ", p=s.mem_used_pct, gb=s.mem_total_mb / 1024),
                         lvl)
        show_swap = s.swap_total_mb > 0
        self.mem_swap.setVisible(show_swap)
        self.swap_label.setVisible(show_swap)
        if show_swap:
            pct = 100 * s.swap_used_mb / s.swap_total_mb
            self.mem_swap.set(pct, 100, tr("{used:.0f} из {total:.0f} МБ", used=s.swap_used_mb, total=s.swap_total_mb),
                              level("swap_pct", pct))

        self.temp_none.setVisible(not s.temps)
        for name, t in s.temps:
            g = self.temp_gauges.get(name)
            if g is None:
                g = self.temp_gauges[name] = Gauge()
                self.temp_form.addRow(name + ":", g)
            lvl = level("temp", t)
            levels.append(lvl)
            g.set(t, 100, f"{t:.1f} °C", lvl)

        if st.state == "camera_error":
            self.cam_state.setText(f"<span style='color:{COLORS[2]}'>{st.message}</span>")
            levels.append(2)
        else:
            self.cam_state.setText(tr("работает: {fps:.1f} кадр/с с камеры, анализ {afps:.1f} кадр/с",
                                      fps=st.camera_fps, afps=st.fps))
        lvl = level("proc_ms", st.proc_ms)
        levels.append(lvl)
        self.proc_gauge.set(st.proc_ms, 200, tr("{ms:.1f} мс", ms=st.proc_ms), lvl)
        self.proc_info.setText(tr("Нейросети: {acc}; оценка взгляда: {gaze}; лиц в кадре: {faces}",
                                  acc=st.accelerator or "—", gaze=st.gaze_method or "—", faces=st.faces))

        if s.disk_total_gb:
            free_pct = 100 * s.disk_free_gb / s.disk_total_gb
            lvl = level("disk_free_pct", free_pct)
            levels.append(lvl)
            self.disk.set(free_pct, 100, tr("{free:.1f} ГБ из {total:.1f} ГБ ({p:.0f}%)", free=s.disk_free_gb,
                                            total=s.disk_total_gb, p=free_pct), lvl)
        self.disk_info.setText(tr("Данные программы (модели, база лиц, журнал, снимки): {mb:.0f} МБ; "
                                  "работает {uptime}", mb=s.data_mb, uptime=_duration(s.uptime_s)))
        q = self.app.mailer._queue.qsize()
        err = self.app.mailer.last_error
        self.mail_info.setText(tr("в очереди писем: {n}; последняя ошибка: {err}", n=q, err=err or tr("нет")))

        worst = max(levels) if levels else 0
        self.summary.setText(f"<b>{tr('Общее состояние')}:</b> "
                             f"<span style='color:{COLORS[worst]}; font-weight:bold'>● {level_name(worst)}</span>")


def _duration(sec: float) -> str:
    sec = int(sec)
    h, m = sec // 3600, sec % 3600 // 60
    return tr("{h} ч {m} мин", h=h, m=m) if h else tr("{m} мин", m=m)

