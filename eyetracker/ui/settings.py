"""Окно настроек (открывается из трея после ввода логина/пароля)."""
from __future__ import annotations

import glob
import threading
from datetime import datetime
from pathlib import Path

from .. import mailer as mailer_mod
from .. import sound as sound_mod
from ..config import EVENT_CATEGORIES, Config
from ..events import events_to_csv
from ..policy import GAZE_STAGE_TEXT, GazeStage
from ..qt import Qt, QtCore, QtGui, QtWidgets, Signal
from .calibration import CalibrationWindow
from .enroll import EnrollDialog
from .login import SetCredentialsDialog, run_dialog
from .widgets import FrameView, dspin, hint, ispin

ROUTE_COLUMNS = [("email", "E-mail сразу"), ("log", "В журнал"), ("digest", "Журнал + e-mail по расписанию")]


def _group(title: str) -> tuple:
    box = QtWidgets.QGroupBox(title)
    form = QtWidgets.QFormLayout(box)
    return box, form


def _scroll(widget: QtWidgets.QWidget) -> QtWidgets.QScrollArea:
    area = QtWidgets.QScrollArea()
    area.setWidgetResizable(True)
    area.setWidget(widget)
    area.setFrameShape(QtWidgets.QFrame.Shape.NoFrame)
    return area


class SettingsDialog(QtWidgets.QDialog):
    _async_done = Signal(str, bool, str)  # (операция, успех, текст)

    def __init__(self, app, parent=None):
        super().__init__(parent)
        self.app = app
        self.cfg: Config = app.cfg.copy()
        self.setWindowTitle("EyeTracker — настройки")
        self.setWindowFlag(Qt.WindowType.WindowMinMaxButtonsHint, True)
        self.resize(900, 720)
        self._async_done.connect(self._on_async_done)

        lay = QtWidgets.QVBoxLayout(self)
        self.tabs = QtWidgets.QTabWidget()
        lay.addWidget(self.tabs)
        self.tabs.addTab(_scroll(self._tab_general()), "Общие")
        self.tabs.addTab(self._tab_camera(), "Камера")
        self.tabs.addTab(self._tab_faces(), "База лиц")
        self.tabs.addTab(_scroll(self._tab_lock()), "Блокировка")
        self.tabs.addTab(_scroll(self._tab_gaze()), "Взгляд")
        self.tabs.addTab(_scroll(self._tab_notify()), "Уведомления")
        self.tabs.addTab(self._tab_journal(), "Журнал")
        self.tabs.addTab(_scroll(self._tab_account()), "Учётная запись")

        buttons = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.StandardButton.Ok
                                             | QtWidgets.QDialogButtonBox.StandardButton.Apply
                                             | QtWidgets.QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self._ok)
        buttons.rejected.connect(self.reject)
        buttons.button(QtWidgets.QDialogButtonBox.StandardButton.Apply).clicked.connect(self._apply)
        lay.addWidget(buttons)

        self._load()
        self.app.engine.preview_enabled = True
        self._timer = QtCore.QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._timer.start(200)
        self.tabs.currentChanged.connect(lambda i: self._refresh_journal() if self.tabs.tabText(i) == "Журнал" else None)

    # ================================================================ tabs
    def _tab_general(self) -> QtWidgets.QWidget:
        w = QtWidgets.QWidget()
        v = QtWidgets.QVBoxLayout(w)
        box, f = _group("Запуск")
        self.autostart = QtWidgets.QCheckBox("Запускать автоматически при входе в систему")
        f.addRow(self.autostart)
        v.addWidget(box)

        box, f = _group("Нагрузка на систему")
        self.fps = dspin(0.5, 30, 0.5, 1, " кадр/с")
        self.idle_fps = dspin(0.2, 30, 0.2, 1, " кадр/с")
        self.detect_width = QtWidgets.QComboBox()
        for wv in (240, 320, 480, 640):
            self.detect_width.addItem(f"{wv} px", wv)
        self.cpu_cores = QtWidgets.QLineEdit()
        self.nice = ispin(0, 19)
        self.use_mp = QtWidgets.QCheckBox("Точная оценка взгляда по радужке (модель точек лица)")
        self.full_scan = dspin(0.2, 10, 0.1, 1, " с")
        self.gaze_fps = dspin(0.5, 30, 0.5, 1, " раз/с")
        f.addRow("Частота анализа (есть люди):", self.fps)
        f.addRow("Частота анализа (никого нет):", self.idle_fps)
        f.addRow("Ширина кадра для детектора:", self.detect_width)
        f.addRow("Ядра CPU:", self.cpu_cores)
        f.addRow("Приоритет (nice):", self.nice)
        f.addRow("Полный просмотр кадра каждые:", self.full_scan)
        f.addRow("Оценка взгляда (без предупреждения):", self.gaze_fps)
        f.addRow(self.use_mp)
        f.addRow(hint("«auto» — только энергоэффективные ядра (на RK3588: A55, cpu0-3), производительные "
                      "ядра A76 остаются другим программам. Пусто — без ограничения. Ядра и приоритет "
                      "применяются после перезапуска программы. Между полными просмотрами кадра лицо ищется только возле "
                      "уже найденных лиц (в 3 раза дешевле); новое лицо будет замечено не позже, чем через "
                      "этот интервал. Пока рамки нет, взгляд оценивается реже; при появлении рамки — на "
                      "каждом кадре, чтобы она сразу исчезала при возврате взгляда. Без точной оценки взгляд оценивается только "
                      "по повороту головы (ещё меньше нагрузка)."))
        v.addWidget(box)

        box, f = _group("Журнал")
        self.retention = ispin(0, 3650, " дн.")
        f.addRow("Хранить события:", self.retention)
        f.addRow(hint("0 — хранить бессрочно."))
        v.addWidget(box)

        self.status_lbl = QtWidgets.QLabel()
        self.status_lbl.setWordWrap(True)
        box, f = _group("Состояние")
        f.addRow(self.status_lbl)
        v.addWidget(box)
        v.addStretch(1)
        return w

    def _tab_camera(self) -> QtWidgets.QWidget:
        w = QtWidgets.QWidget()
        h = QtWidgets.QHBoxLayout(w)
        left = QtWidgets.QWidget()
        f = QtWidgets.QFormLayout(left)
        self.cam_source = QtWidgets.QComboBox()
        self.cam_source.setEditable(True)
        for dev in sorted(glob.glob("/dev/video*")):
            self.cam_source.addItem(dev)
        self.cam_backend = QtWidgets.QComboBox()
        for key, title in (("auto", "Автоматически"), ("v4l2", "V4L2"), ("gstreamer", "GStreamer"),
                           ("ffmpeg", "FFmpeg")):
            self.cam_backend.addItem(title, key)
        self.cam_w = ispin(160, 3840)
        self.cam_h = ispin(120, 2160)
        self.cam_fps = ispin(1, 60, " кадр/с")
        self.cam_rotate = QtWidgets.QComboBox()
        for r in (0, 90, 180, 270):
            self.cam_rotate.addItem(f"{r}°", r)
        self.cam_mirror = QtWidgets.QCheckBox("Зеркально")
        f.addRow("Источник:", self.cam_source)
        f.addRow("Драйвер:", self.cam_backend)
        f.addRow("Ширина:", self.cam_w)
        f.addRow("Высота:", self.cam_h)
        f.addRow("Частота захвата:", self.cam_fps)
        f.addRow("Поворот:", self.cam_rotate)
        f.addRow(self.cam_mirror)
        f.addRow(hint("Источник: номер камеры (0), устройство (/dev/video0) или конвейер GStreamer "
                      "(для MIPI-камеры RK3588). Изменения вступают в силу по кнопке «Применить»."))
        h.addWidget(left, 0)
        right = QtWidgets.QVBoxLayout()
        self.preview = FrameView()
        right.addWidget(self.preview, 1)
        self.preview_info = QtWidgets.QLabel()
        right.addWidget(self.preview_info)
        h.addLayout(right, 1)
        return w

    def _tab_faces(self) -> QtWidgets.QWidget:
        w = QtWidgets.QWidget()
        v = QtWidgets.QVBoxLayout(w)
        self.faces = QtWidgets.QListWidget()
        self.faces.setIconSize(QtCore.QSize(64, 64))
        v.addWidget(self.faces, 1)
        row = QtWidgets.QHBoxLayout()
        for text, slot in (("Добавить лицо…", self._face_add), ("Добавить образцы…", self._face_more),
                           ("Переименовать…", self._face_rename), ("Удалить", self._face_remove)):
            b = QtWidgets.QPushButton(text)
            b.clicked.connect(slot)
            row.addWidget(b)
        v.addLayout(row)
        box, f = _group("Распознавание")
        self.rec_thr = dspin(0.2, 0.9, 0.01, 2)
        self.det_thr = dspin(0.3, 0.99, 0.01, 2)
        self.min_face = ispin(20, 400, " px")
        self.rec_interval = dspin(0.5, 30, 0.5, 1, " с")
        f.addRow("Порог сходства лица:", self.rec_thr)
        f.addRow("Порог детектора лиц:", self.det_thr)
        f.addRow("Мин. размер лица для распознавания:", self.min_face)
        f.addRow("Перепроверка известных лиц каждые:", self.rec_interval)
        f.addRow(hint("Порог сходства: выше — строже (меньше ложных «своих», но чаще «посторонний»). "
                      "Рекомендуется 0.36–0.45. Лица мельче минимального размера учитываются только "
                      "как присутствие человека."))
        v.addWidget(box)
        return w

    def _tab_lock(self) -> QtWidgets.QWidget:
        w = QtWidgets.QWidget()
        v = QtWidgets.QVBoxLayout(w)
        box, f = _group("1. Обнаружение человека")
        self.leave_debounce = dspin(0.5, 60, 0.5, 1, " с")
        f.addRow("Человек считается ушедшим через:", self.leave_debounce)
        v.addWidget(box)

        box, f = _group("3. Блокировка, если перед экраном никого нет")
        self.lock_abs = QtWidgets.QCheckBox("Включено")
        self.abs_timeout = dspin(1, 86400, 5, 0, " с")
        f.addRow(self.lock_abs)
        f.addRow("Таймаут:", self.abs_timeout)
        v.addWidget(box)

        box, f = _group("4. Блокировка, если нет авторизованного лица (даже при наличии других)")
        self.lock_unauth = QtWidgets.QCheckBox("Включено")
        self.unauth_timeout = dspin(1, 86400, 1, 0, " с")
        f.addRow(self.lock_unauth)
        f.addRow("Таймаут:", self.unauth_timeout)
        v.addWidget(box)

        box, f = _group("5. Блокировка при появлении постороннего лица (даже рядом с авторизованным)")
        self.lock_stranger = QtWidgets.QCheckBox("Включено")
        self.stranger_confirm = dspin(0, 60, 0.5, 1, " с")
        f.addRow(self.lock_stranger)
        f.addRow("Время подтверждения:", self.stranger_confirm)
        f.addRow(hint("Постороннее лицо должно быть видно указанное время — это защищает от ложных "
                      "срабатываний. Пункты 4 и 5 работают, только если база лиц не пуста."))
        v.addWidget(box)

        box, f = _group("Способ блокировки")
        self.lock_method = QtWidgets.QComboBox()
        self.lock_method.addItem("Автоматически (loginctl / D-Bus / xflock4 / …)", "auto")
        self.lock_method.addItem("Своя команда", "custom")
        self.lock_cmd = QtWidgets.QLineEdit()
        self.lock_cmd.setPlaceholderText("например: loginctl lock-session")
        self.relock = dspin(3, 3600, 1, 0, " с")
        test = QtWidgets.QPushButton("Проверить блокировку сейчас")
        test.clicked.connect(self._test_lock)
        f.addRow("Метод:", self.lock_method)
        f.addRow("Команда:", self.lock_cmd)
        f.addRow("Повторная блокировка через:", self.relock)
        f.addRow(test)
        f.addRow(hint("Повторная блокировка выполняется, если после разблокировки условие "
                      "по-прежнему выполняется (и окружение сообщает состояние блокировки)."))
        v.addWidget(box)
        v.addStretch(1)
        return w

    def _tab_gaze(self) -> QtWidgets.QWidget:
        w = QtWidgets.QWidget()
        v = QtWidgets.QVBoxLayout(w)
        box, f = _group("6. Контроль взгляда авторизованного лица")
        self.gaze_on = QtWidgets.QCheckBox("Включено")
        self.t1 = dspin(0, 3600, 0.5, 1, " с")
        self.t2 = dspin(0, 3600, 0.5, 1, " с")
        self.t3 = dspin(0, 3600, 0.5, 1, " с")
        self.ret_debounce = dspin(0, 5, 0.1, 1, " с")
        self.lost_away = QtWidgets.QCheckBox("Пропажа лица из кадра (отвернулся) = взгляд не на экране")
        self.closed_away = QtWidgets.QCheckBox("Закрытые глаза = взгляд не на экране")
        f.addRow(self.gaze_on)
        f.addRow("T1 — красная рамка через:", self.t1)
        f.addRow("T2 — мигающая рамка через:", self.t2)
        f.addRow("T3 — звуковой сигнал через:", self.t3)
        f.addRow(hint("Время отсчитывается с момента, когда взгляд ушёл с экрана (T1 ≤ T2 ≤ T3). "
                      "При возвращении взгляда таймеры сбрасываются, рамка и звук отключаются."))
        f.addRow("Взгляд считается вернувшимся через:", self.ret_debounce)
        f.addRow(self.lost_away)
        f.addRow(self.closed_away)
        v.addWidget(box)

        box, f = _group("Зона экрана (градусы относительно направления на камеру)")
        self.yaw_min = dspin(-90, 90, 1, 1, "°")
        self.yaw_max = dspin(-90, 90, 1, 1, "°")
        self.pitch_min = dspin(-90, 90, 1, 1, "°")
        self.pitch_max = dspin(-90, 90, 1, 1, "°")
        self.zone_margin = dspin(0, 30, 0.5, 1, "°")
        self.eye_gain = dspin(0.5, 5, 0.1, 1)
        f.addRow("По горизонтали от:", self.yaw_min)
        f.addRow("По горизонтали до:", self.yaw_max)
        f.addRow("По вертикали от (вниз):", self.pitch_min)
        f.addRow("По вертикали до (вверх):", self.pitch_max)
        f.addRow("Допуск:", self.zone_margin)
        f.addRow("Коэффициент поворота глаз:", self.eye_gain)
        self.calib_state = QtWidgets.QLabel()
        f.addRow(self.calib_state)
        row = QtWidgets.QHBoxLayout()
        b = QtWidgets.QPushButton("Калибровать…")
        b.clicked.connect(self._calibrate)
        row.addWidget(b)
        b = QtWidgets.QPushButton("Сбросить к значениям по умолчанию")
        b.clicked.connect(self._reset_zone)
        row.addWidget(b)
        f.addRow(row)
        self.gaze_live = QtWidgets.QLabel("—")
        f.addRow("Сейчас:", self.gaze_live)
        f.addRow(hint("Камера расположена по центру верхней кромки, поэтому при взгляде на экран угол "
                      "по вертикали отрицательный. Калибровка (5 точек) настраивает зону под конкретного "
                      "пользователя и монитор — выполните её сидя в обычном рабочем положении."))
        v.addWidget(box)

        box, f = _group("Рамка")
        self.border_w = ispin(2, 100, " px")
        self.border_color = QtWidgets.QPushButton()
        self.border_color.clicked.connect(self._pick_color)
        self.blink_ms = ispin(100, 3000, " мс")
        f.addRow("Толщина:", self.border_w)
        f.addRow("Цвет:", self.border_color)
        f.addRow("Период мигания:", self.blink_ms)
        row = QtWidgets.QHBoxLayout()
        for text, stage in (("Показать рамку", 1), ("Мигающая", 2), ("Скрыть", 0)):
            b = QtWidgets.QPushButton(text)
            b.clicked.connect(lambda _=False, s=stage: self._preview_border(s))
            row.addWidget(b)
        f.addRow(row)
        v.addWidget(box)

        box, f = _group("Звуковой сигнал")
        self.sound = QtWidgets.QComboBox()
        row = QtWidgets.QHBoxLayout()
        row.addWidget(self.sound, 1)
        for text, slot in (("▶", self._sound_play), ("■", self._sound_stop), ("Загрузить…", self._sound_upload),
                           ("Удалить", self._sound_delete)):
            b = QtWidgets.QPushButton(text)
            b.clicked.connect(slot)
            row.addWidget(b)
        f.addRow("Сигнал:", row)
        self.sound_repeat = dspin(0, 60, 0.5, 1, " с")
        self.volume = QtWidgets.QSlider(Qt.Orientation.Horizontal)
        self.volume.setRange(0, 100)
        f.addRow("Пауза между повторами:", self.sound_repeat)
        f.addRow("Громкость:", self.volume)
        f.addRow(hint("Свои сигналы: WAV, OGG, MP3, FLAC (для MP3 нужен ffplay или mpv)."))
        v.addWidget(box)
        v.addStretch(1)
        return w

    def _tab_notify(self) -> QtWidgets.QWidget:
        w = QtWidgets.QWidget()
        v = QtWidgets.QVBoxLayout(w)
        box, f = _group("Куда направлять события")
        grid = QtWidgets.QGridLayout()
        grid.addWidget(QtWidgets.QLabel("<b>Событие</b>"), 0, 0)
        for c, (_, title) in enumerate(ROUTE_COLUMNS, 1):
            grid.addWidget(QtWidgets.QLabel(f"<b>{title}</b>"), 0, c)
        self.routes = {}
        for r, (key, title) in enumerate(EVENT_CATEGORIES.items(), 1):
            grid.addWidget(QtWidgets.QLabel(title), r, 0)
            boxes = {}
            for c, (col, _) in enumerate(ROUTE_COLUMNS, 1):
                cb = QtWidgets.QCheckBox()
                grid.addWidget(cb, r, c, Qt.AlignmentFlag.AlignCenter)
                boxes[col] = cb
            boxes["digest"].toggled.connect(lambda on, b=boxes: on and b["log"].setChecked(True))
            boxes["log"].toggled.connect(lambda on, b=boxes: (not on) and b["digest"].setChecked(False))
            self.routes[key] = boxes
        f.addRow(grid)
        self.save_snaps = QtWidgets.QCheckBox("Сохранять снимок с камеры для событий в журнале")
        f.addRow(self.save_snaps)
        v.addWidget(box)

        box, f = _group("Почтовый сервер (SMTP)")
        self.smtp_host = QtWidgets.QLineEdit()
        self.smtp_port = ispin(1, 65535)
        self.smtp_sec = QtWidgets.QComboBox()
        for key, title in (("starttls", "STARTTLS"), ("ssl", "SSL/TLS"), ("none", "Без шифрования")):
            self.smtp_sec.addItem(title, key)
        self.smtp_user = QtWidgets.QLineEdit()
        self.smtp_pass = QtWidgets.QLineEdit()
        self.smtp_pass.setEchoMode(QtWidgets.QLineEdit.EchoMode.Password)
        self.smtp_from = QtWidgets.QLineEdit()
        self.smtp_to = QtWidgets.QLineEdit()
        self.smtp_to.setPlaceholderText("security@example.com, admin@example.com")
        self.smtp_prefix = QtWidgets.QLineEdit()
        self.attach_snap = QtWidgets.QCheckBox("Прикладывать снимок с камеры к письму")
        f.addRow("Сервер:", self.smtp_host)
        f.addRow("Порт:", self.smtp_port)
        f.addRow("Шифрование:", self.smtp_sec)
        f.addRow("Логин:", self.smtp_user)
        f.addRow("Пароль:", self.smtp_pass)
        f.addRow("Отправитель:", self.smtp_from)
        f.addRow("Получатель(и):", self.smtp_to)
        f.addRow("Префикс темы:", self.smtp_prefix)
        f.addRow(self.attach_snap)
        b = QtWidgets.QPushButton("Отправить тестовое письмо")
        b.clicked.connect(self._test_mail)
        f.addRow(b)
        v.addWidget(box)

        box, f = _group("Отчёт по расписанию")
        self.sched_mode = QtWidgets.QComboBox()
        self.sched_mode.addItem("Каждые N минут", "interval")
        self.sched_mode.addItem("Ежедневно в указанное время", "daily")
        self.sched_interval = ispin(1, 100000, " мин")
        self.sched_times = QtWidgets.QLineEdit()
        self.sched_times.setPlaceholderText("09:00, 13:00, 18:00")
        self.sched_empty = QtWidgets.QCheckBox("Отправлять отчёт, даже если новых событий нет")
        f.addRow("Расписание:", self.sched_mode)
        f.addRow("Интервал:", self.sched_interval)
        f.addRow("Время (ЧЧ:ММ через запятую):", self.sched_times)
        f.addRow(self.sched_empty)
        self.sched_next = QtWidgets.QLabel()
        f.addRow("Следующий отчёт:", self.sched_next)
        b = QtWidgets.QPushButton("Отправить отчёт сейчас")
        b.clicked.connect(self._digest_now)
        f.addRow(b)
        v.addWidget(box)
        v.addStretch(1)
        return w

    def _tab_journal(self) -> QtWidgets.QWidget:
        w = QtWidgets.QWidget()
        v = QtWidgets.QVBoxLayout(w)
        row = QtWidgets.QHBoxLayout()
        self.j_filter = QtWidgets.QComboBox()
        self.j_filter.addItem("Все события", "")
        for key, title in EVENT_CATEGORIES.items():
            self.j_filter.addItem(title, key)
        self.j_filter.currentIndexChanged.connect(self._refresh_journal)
        row.addWidget(self.j_filter, 1)
        for text, slot in (("Обновить", self._refresh_journal), ("Экспорт CSV…", self._export_journal),
                           ("Очистить…", self._clear_journal)):
            b = QtWidgets.QPushButton(text)
            b.clicked.connect(slot)
            row.addWidget(b)
        v.addLayout(row)
        self.journal = QtWidgets.QTableWidget(0, 3)
        self.journal.setHorizontalHeaderLabels(["Время", "Категория", "Событие"])
        self.journal.horizontalHeader().setStretchLastSection(True)
        self.journal.setEditTriggers(QtWidgets.QAbstractItemView.EditTrigger.NoEditTriggers)
        self.journal.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectionBehavior.SelectRows)
        self.journal.cellDoubleClicked.connect(self._open_snapshot)
        v.addWidget(self.journal, 1)
        v.addWidget(hint("Двойной щелчок — открыть снимок с камеры (если сохранён). Показаны последние 2000 событий."))
        self._journal_events = []
        return w

    def _tab_account(self) -> QtWidgets.QWidget:
        w = QtWidgets.QWidget()
        v = QtWidgets.QVBoxLayout(w)
        box, f = _group("Администратор")
        self.acc_label = QtWidgets.QLabel()
        f.addRow("Логин:", self.acc_label)
        b = QtWidgets.QPushButton("Сменить логин/пароль…")
        b.clicked.connect(self._change_password)
        f.addRow(b)
        f.addRow(hint("Логин и пароль требуются для входа в настройки, приостановки контроля и выхода "
                      "из программы. Пароль хранится в виде хеша PBKDF2-SHA256."))
        v.addWidget(box)
        v.addStretch(1)
        return w

    # ======================================================== load / save
    def _load(self) -> None:
        c = self.cfg
        self.autostart.setChecked(c.general.autostart)
        self.retention.setValue(c.general.log_retention_days)
        p = c.processing
        self.fps.setValue(p.fps)
        self.idle_fps.setValue(p.idle_fps)
        idx = self.detect_width.findData(p.detect_width)
        if idx < 0:
            self.detect_width.addItem(f"{p.detect_width} px", p.detect_width)
            idx = self.detect_width.count() - 1
        self.detect_width.setCurrentIndex(idx)
        self.cpu_cores.setText(p.cpu_cores)
        self.nice.setValue(p.nice)
        self.use_mp.setChecked(p.precise_gaze)
        self.full_scan.setValue(p.full_scan_interval_s)
        self.gaze_fps.setValue(p.gaze_fps)
        self.rec_thr.setValue(p.recognition_threshold)
        self.det_thr.setValue(p.detect_threshold)
        self.min_face.setValue(p.min_face_size)
        self.rec_interval.setValue(p.recognize_interval_s)

        cam = c.camera
        self.cam_source.setCurrentText(cam.source)
        self.cam_backend.setCurrentIndex(max(0, self.cam_backend.findData(cam.backend)))
        self.cam_w.setValue(cam.width)
        self.cam_h.setValue(cam.height)
        self.cam_fps.setValue(cam.fps)
        self.cam_rotate.setCurrentIndex(max(0, self.cam_rotate.findData(cam.rotate)))
        self.cam_mirror.setChecked(cam.mirror)

        self.leave_debounce.setValue(c.presence.leave_debounce_s)
        self.lock_abs.setChecked(c.presence.lock_on_absence)
        self.abs_timeout.setValue(c.presence.absence_timeout_s)
        self.lock_unauth.setChecked(c.authorized.lock_if_no_authorized)
        self.unauth_timeout.setValue(c.authorized.timeout_s)
        self.lock_stranger.setChecked(c.stranger.lock_on_stranger)
        self.stranger_confirm.setValue(c.stranger.confirm_s)
        self.lock_method.setCurrentIndex(max(0, self.lock_method.findData(c.lock.method)))
        self.lock_cmd.setText(c.lock.custom_command)
        self.relock.setValue(c.lock.relock_interval_s)

        g = c.gaze
        self.gaze_on.setChecked(g.enabled)
        self.t1.setValue(g.t1_s)
        self.t2.setValue(g.t2_s)
        self.t3.setValue(g.t3_s)
        self.ret_debounce.setValue(g.return_debounce_s)
        self.lost_away.setChecked(g.face_lost_is_away)
        self.closed_away.setChecked(g.eyes_closed_is_away)
        self._set_zone_widgets(g.zone_yaw_min, g.zone_yaw_max, g.zone_pitch_min, g.zone_pitch_max)
        self.zone_margin.setValue(g.zone_margin)
        self.eye_gain.setValue(g.eye_gain)
        self._calibrated = g.calibrated
        self._update_calib_label()
        self.border_w.setValue(g.border_width)
        self._color = g.border_color
        self._update_color_button()
        self.blink_ms.setValue(g.blink_interval_ms)
        self._reload_sounds(g.sound)
        self.sound_repeat.setValue(g.sound_repeat_s)
        self.volume.setValue(g.volume)

        e = c.email
        self.smtp_host.setText(e.smtp_host)
        self.smtp_port.setValue(e.smtp_port)
        self.smtp_sec.setCurrentIndex(max(0, self.smtp_sec.findData(e.security)))
        self.smtp_user.setText(e.username)
        self.smtp_pass.setText(e.password)
        self.smtp_from.setText(e.sender)
        self.smtp_to.setText(e.recipients)
        self.smtp_prefix.setText(e.subject_prefix)
        self.attach_snap.setChecked(e.attach_snapshot)
        for key, boxes in self.routes.items():
            route = c.notify.routes[key]
            boxes["email"].setChecked(route.email)
            boxes["log"].setChecked(route.log)
            boxes["digest"].setChecked(route.digest)
        self.save_snaps.setChecked(c.notify.save_snapshots)
        s = c.schedule
        self.sched_mode.setCurrentIndex(max(0, self.sched_mode.findData(s.mode)))
        self.sched_interval.setValue(s.interval_min)
        self.sched_times.setText(s.daily_times)
        self.sched_empty.setChecked(s.send_empty)
        self.acc_label.setText(c.auth.username)
        self._reload_faces()

    def _collect(self) -> Config:
        c = self.cfg.copy()
        c.general.autostart = self.autostart.isChecked()
        c.general.log_retention_days = self.retention.value()
        p = c.processing
        p.fps = self.fps.value()
        p.idle_fps = self.idle_fps.value()
        p.detect_width = int(self.detect_width.currentData())
        p.cpu_cores = self.cpu_cores.text().strip()
        p.nice = self.nice.value()
        p.precise_gaze = self.use_mp.isChecked()
        p.full_scan_interval_s = self.full_scan.value()
        p.gaze_fps = self.gaze_fps.value()
        p.recognition_threshold = self.rec_thr.value()
        p.detect_threshold = self.det_thr.value()
        p.min_face_size = self.min_face.value()
        p.recognize_interval_s = self.rec_interval.value()
        cam = c.camera
        cam.source = self.cam_source.currentText().strip() or "0"
        cam.backend = self.cam_backend.currentData()
        cam.width, cam.height, cam.fps = self.cam_w.value(), self.cam_h.value(), self.cam_fps.value()
        cam.rotate = int(self.cam_rotate.currentData())
        cam.mirror = self.cam_mirror.isChecked()
        c.presence.leave_debounce_s = self.leave_debounce.value()
        c.presence.lock_on_absence = self.lock_abs.isChecked()
        c.presence.absence_timeout_s = self.abs_timeout.value()
        c.authorized.lock_if_no_authorized = self.lock_unauth.isChecked()
        c.authorized.timeout_s = self.unauth_timeout.value()
        c.stranger.lock_on_stranger = self.lock_stranger.isChecked()
        c.stranger.confirm_s = self.stranger_confirm.value()
        c.lock.method = self.lock_method.currentData()
        c.lock.custom_command = self.lock_cmd.text().strip()
        c.lock.relock_interval_s = self.relock.value()
        g = c.gaze
        g.enabled = self.gaze_on.isChecked()
        g.t1_s, g.t2_s, g.t3_s = self.t1.value(), self.t2.value(), self.t3.value()
        g.return_debounce_s = self.ret_debounce.value()
        g.face_lost_is_away = self.lost_away.isChecked()
        g.eyes_closed_is_away = self.closed_away.isChecked()
        g.zone_yaw_min, g.zone_yaw_max = self.yaw_min.value(), self.yaw_max.value()
        g.zone_pitch_min, g.zone_pitch_max = self.pitch_min.value(), self.pitch_max.value()
        g.zone_margin = self.zone_margin.value()
        g.eye_gain = self.eye_gain.value()
        g.calibrated = self._calibrated
        g.border_width = self.border_w.value()
        g.border_color = self._color
        g.blink_interval_ms = self.blink_ms.value()
        g.sound = self.sound.currentData() or "builtin:beep"
        g.sound_repeat_s = self.sound_repeat.value()
        g.volume = self.volume.value()
        e = c.email
        e.smtp_host = self.smtp_host.text().strip()
        e.smtp_port = self.smtp_port.value()
        e.security = self.smtp_sec.currentData()
        e.username = self.smtp_user.text().strip()
        e.password = self.smtp_pass.text()
        e.sender = self.smtp_from.text().strip()
        e.recipients = self.smtp_to.text().strip()
        e.subject_prefix = self.smtp_prefix.text()
        e.attach_snapshot = self.attach_snap.isChecked()
        for key, boxes in self.routes.items():
            r = c.notify.routes[key]
            r.email, r.log, r.digest = (boxes[k].isChecked() for k in ("email", "log", "digest"))
        c.notify.save_snapshots = self.save_snaps.isChecked()
        s = c.schedule
        s.mode = self.sched_mode.currentData()
        s.interval_min = self.sched_interval.value()
        s.daily_times = self.sched_times.text().strip()
        s.send_empty = self.sched_empty.isChecked()
        c.validate()
        return c

    def _validate(self, c: Config) -> bool:
        problems = []
        if not (self.t1.value() <= self.t2.value() <= self.t3.value()):
            problems.append("Должно выполняться T1 ≤ T2 ≤ T3.")
        if c.schedule.mode == "daily":
            try:
                if not mailer_mod.parse_times(c.schedule.daily_times):
                    problems.append("Не указано время отчёта.")
            except ValueError as exc:
                problems.append(str(exc))
        if c.lock.method == "custom" and not c.lock.custom_command:
            problems.append("Не указана своя команда блокировки.")
        uses_mail = any(r.email or r.digest for r in c.notify.routes.values())
        if uses_mail and not mailer_mod.is_configured(c.email):
            problems.append("Для отправки событий по e-mail укажите SMTP-сервер и получателя "
                            "(до этого события по расписанию будут накапливаться в журнале).")
            if len(problems) == 1:
                QtWidgets.QMessageBox.information(self, "E-mail не настроен", problems[0])
                return True
        if problems:
            QtWidgets.QMessageBox.warning(self, "Проверьте настройки", "\n".join(problems))
            return False
        return True

    def _apply(self) -> bool:
        c = self._collect()
        if not self._validate(c):
            return False
        self.cfg = c
        self.app.apply_config(c)
        return True

    def _ok(self) -> None:
        if self._apply():
            self.accept()

    def done(self, r):  # noqa: D401
        self._timer.stop()
        self.app.engine.preview_enabled = False
        self.app.sound.stop()
        self.app.refresh_gaze_outputs()
        super().done(r)

    # ============================================================ helpers
    def _tick(self) -> None:
        eng = self.app.engine
        st = eng.status
        tab = self.tabs.tabText(self.tabs.currentIndex())
        if tab == "Камера":
            self.preview.show_frame(eng.get_preview())
            self.preview_info.setText(f"Обработка: {st.fps:.1f} кадр/с · лиц: {st.faces} · "
                                      f"оценка взгляда: {st.gaze_method or '—'}")
        if tab == "Взгляд":
            lg = eng.latest_gaze()
            if lg is not None:
                s = lg[1]
                zone_ok = (self.yaw_min.value() - self.zone_margin.value() <= s.yaw <= self.yaw_max.value()
                           + self.zone_margin.value()) and (self.pitch_min.value() - self.zone_margin.value()
                                                            <= s.pitch <= self.pitch_max.value()
                                                            + self.zone_margin.value())
                self.gaze_live.setText(
                    f"по горизонтали {s.yaw:+.1f}°, по вертикали {s.pitch:+.1f}° — "
                    f"{'на экране' if zone_ok else 'мимо экрана'}"
                    f"{' (глаза закрыты)' if s.eyes_closed else ''}; стадия: "
                    f"{GAZE_STAGE_TEXT[GazeStage(st.gaze_stage)]}")
        if tab == "Общие":
            self.status_lbl.setText(self.app.status_text())
        if tab == "Уведомления" and self.app.scheduler.next_run:
            self.sched_next.setText(self.app.scheduler.next_run.strftime("%Y-%m-%d %H:%M"))

    def _set_zone_widgets(self, ymin, ymax, pmin, pmax) -> None:
        self.yaw_min.setValue(ymin)
        self.yaw_max.setValue(ymax)
        self.pitch_min.setValue(pmin)
        self.pitch_max.setValue(pmax)

    def _update_calib_label(self) -> None:
        self.calib_state.setText("Зона откалибрована" if self._calibrated
                                 else "Калибровка не выполнялась (используются значения по умолчанию)")

    def _calibrate(self) -> None:
        if self.app.engine.status.state != "running":
            QtWidgets.QMessageBox.warning(self, "Калибровка", "Камера не работает или контроль приостановлен.")
            return
        self.hide()
        self._calib = CalibrationWindow(self.app.engine, self.zone_margin.value())
        self._calib.calibrated.connect(self._calibrated_done)
        self._calib.start()

    def _calibrated_done(self, zone) -> None:
        self.show()
        self.raise_()
        if zone is None:
            QtWidgets.QMessageBox.warning(self, "Калибровка", self._calib.error or "Калибровка не выполнена")
            return
        self._set_zone_widgets(zone.yaw_min, zone.yaw_max, zone.pitch_min, zone.pitch_max)
        self._calibrated = True
        self._update_calib_label()
        QtWidgets.QMessageBox.information(
            self, "Калибровка",
            f"Зона экрана: по горизонтали {zone.yaw_min:+.0f}…{zone.yaw_max:+.0f}°, "
            f"по вертикали {zone.pitch_min:+.0f}…{zone.pitch_max:+.0f}°.\nНажмите «Применить».")

    def _reset_zone(self) -> None:
        d = Config().gaze
        self._set_zone_widgets(d.zone_yaw_min, d.zone_yaw_max, d.zone_pitch_min, d.zone_pitch_max)
        self.zone_margin.setValue(d.zone_margin)
        self._calibrated = False
        self._update_calib_label()

    def _update_color_button(self) -> None:
        self.border_color.setText(self._color)
        self.border_color.setStyleSheet(f"background:{self._color}; color:white;")

    def _pick_color(self) -> None:
        col = QtWidgets.QColorDialog.getColor(QtGui.QColor(self._color), self, "Цвет рамки")
        if col.isValid():
            self._color = col.name()
            self._update_color_button()

    def _preview_border(self, stage: int) -> None:
        self.app.overlay.configure(self.border_w.value(), self._color, self.blink_ms.value())
        self.app.overlay.set_state(stage > 0, stage > 1)

    def _reload_sounds(self, current: str) -> None:
        self.sound.clear()
        for sid, title in sound_mod.list_sounds():
            self.sound.addItem(title, sid)
        self.sound.setCurrentIndex(max(0, self.sound.findData(current)))

    def _sound_play(self) -> None:
        self.app.sound.play_once(self.sound.currentData(), self.volume.value())

    def _sound_stop(self) -> None:
        self.app.sound.stop()

    def _sound_upload(self) -> None:
        path, _ = QtWidgets.QFileDialog.getOpenFileName(self, "Звуковой файл", "",
                                                        "Звук (*.wav *.ogg *.oga *.mp3 *.flac)")
        if not path:
            return
        try:
            sid = sound_mod.import_sound(Path(path))
        except (OSError, ValueError) as exc:
            QtWidgets.QMessageBox.warning(self, "Ошибка", str(exc))
            return
        self._reload_sounds(sid)

    def _sound_delete(self) -> None:
        sid = self.sound.currentData()
        try:
            sound_mod.delete_sound(sid)
        except (OSError, ValueError) as exc:
            QtWidgets.QMessageBox.warning(self, "Удаление", str(exc))
            return
        self._reload_sounds("builtin:beep")

    # ------------------------------------------------------------- faces
    def _reload_faces(self) -> None:
        self.faces.clear()
        for p in self.app.db.persons():
            item = QtWidgets.QListWidgetItem(f"{p.name}  (образцов: {p.samples})")
            item.setData(Qt.ItemDataRole.UserRole, p.id)
            photo = self.app.db.photo_path(p.id)
            if photo.exists():
                item.setIcon(QtGui.QIcon(str(photo)))
            self.faces.addItem(item)

    def _selected_face(self):
        item = self.faces.currentItem()
        return item.data(Qt.ItemDataRole.UserRole) if item else None

    def _face_add(self) -> None:
        if self.app.engine.detector is None:
            QtWidgets.QMessageBox.warning(self, "База лиц", "Модели распознавания не загружены.")
            return
        if run_dialog(EnrollDialog(self.app.engine, self.app.db, None, self)):
            self.app.publish_system("face_added", "В базу авторизованных лиц добавлено лицо")
        self.app.engine.preview_enabled = True
        self._reload_faces()

    def _face_more(self) -> None:
        pid = self._selected_face()
        if pid and self.app.engine.detector is not None:
            run_dialog(EnrollDialog(self.app.engine, self.app.db, pid, self))
            self.app.engine.preview_enabled = True
            self._reload_faces()

    def _face_rename(self) -> None:
        pid = self._selected_face()
        person = self.app.db.get(pid) if pid else None
        if not person:
            return
        name, ok = QtWidgets.QInputDialog.getText(self, "Переименовать", "Имя:", text=person.name)
        if ok and name.strip():
            self.app.db.rename(pid, name)
            self._reload_faces()

    def _face_remove(self) -> None:
        pid = self._selected_face()
        person = self.app.db.get(pid) if pid else None
        if not person:
            return
        if QtWidgets.QMessageBox.question(self, "Удаление", f"Удалить «{person.name}» из базы?") \
                == QtWidgets.QMessageBox.StandardButton.Yes:
            self.app.db.remove(pid)
            self.app.publish_system("face_removed", f"Из базы авторизованных лиц удалено лицо «{person.name}»")
            self._reload_faces()

    # ------------------------------------------------------- async tests
    def _run_async(self, op: str, fn) -> None:
        def worker():
            try:
                ok, text = fn()
            except Exception as exc:  # noqa: BLE001
                ok, text = False, str(exc)
            self._async_done.emit(op, ok, text)
        threading.Thread(target=worker, daemon=True).start()

    def _on_async_done(self, op: str, ok: bool, text: str) -> None:
        box = QtWidgets.QMessageBox.information if ok else QtWidgets.QMessageBox.warning
        box(self, op, text)

    def _test_mail(self) -> None:
        cfg = self._collect().email

        def fn():
            msg = mailer_mod.build_message(cfg, "Тестовое письмо",
                                           "Это тестовое письмо EyeTracker.\n" + mailer_mod.host_info())
            mailer_mod.send_message(cfg, msg)
            return True, "Письмо отправлено. Проверьте почтовый ящик."
        self._run_async("Тестовое письмо", fn)

    def _digest_now(self) -> None:
        self._apply()
        self._run_async("Отчёт", lambda: self.app.scheduler.send_digest(force=True))

    def _test_lock(self) -> None:
        c = self._collect()
        if QtWidgets.QMessageBox.question(self, "Проверка", "Заблокировать экран сейчас?") \
                != QtWidgets.QMessageBox.StandardButton.Yes:
            return
        from ..locker import ScreenLocker
        locker = ScreenLocker(c.lock.method, c.lock.custom_command)

        def fn():
            ok = locker.lock()
            return ok, ("Команда блокировки выполнена успешно." if ok else
                        "Не найдено работающей команды блокировки — укажите свою команду.")
        self._run_async("Блокировка", fn)

    # ------------------------------------------------------------ journal
    def _refresh_journal(self) -> None:
        cat = self.j_filter.currentData() or None
        self._journal_events = self.app.store.query(limit=2000, category=cat)
        self.journal.setRowCount(len(self._journal_events))
        for r, ev in enumerate(self._journal_events):
            for c, text in enumerate((ev.time_str, ev.category_title, ev.message)):
                item = QtWidgets.QTableWidgetItem(text)
                if c == 2 and ev.snapshot_path:
                    item.setToolTip("Есть снимок — двойной щелчок")
                self.journal.setItem(r, c, item)
        self.journal.resizeColumnsToContents()

    def _export_journal(self) -> None:
        path, _ = QtWidgets.QFileDialog.getSaveFileName(
            self, "Экспорт журнала", f"eyetracker-{datetime.now():%Y%m%d-%H%M}.csv", "CSV (*.csv)")
        if path:
            cat = self.j_filter.currentData() or None
            Path(path).write_text(events_to_csv(self.app.store.query(limit=10 ** 9, category=cat)),
                                  encoding="utf-8-sig")

    def _clear_journal(self) -> None:
        if QtWidgets.QMessageBox.question(self, "Журнал", "Удалить все события из журнала?") \
                == QtWidgets.QMessageBox.StandardButton.Yes:
            self.app.store.clear()
            self.app.publish_system("journal_cleared", "Журнал событий очищен администратором")
            self._refresh_journal()

    def _open_snapshot(self, row: int, _col: int) -> None:
        if 0 <= row < len(self._journal_events):
            snap = self._journal_events[row].snapshot_path
            if snap and Path(snap).exists():
                dlg = QtWidgets.QDialog(self)
                dlg.setWindowTitle(self._journal_events[row].message)
                lay = QtWidgets.QVBoxLayout(dlg)
                lbl = QtWidgets.QLabel()
                lbl.setPixmap(QtGui.QPixmap(snap))
                lay.addWidget(lbl)
                dlg.show()

    # ------------------------------------------------------------ account
    def _change_password(self) -> None:
        auth_copy = self.cfg.auth.__class__(**vars(self.cfg.auth))
        if run_dialog(SetCredentialsDialog(auth_copy, False, self)):
            self.cfg.auth = auth_copy
            self.app.cfg.auth = auth_copy
            self.app.save_config()
            self.acc_label.setText(auth_copy.username)
            self.app.publish_system("password_changed", "Учётные данные администратора изменены")
            QtWidgets.QMessageBox.information(self, "Учётная запись", "Логин и пароль изменены.")

