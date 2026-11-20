"""Окно настроек (открывается из трея после ввода логина/пароля)."""
from __future__ import annotations

import glob
import threading
from datetime import datetime
from pathlib import Path

from .. import mailer as mailer_mod
from .. import sound as sound_mod
from ..config import EVENT_CATEGORIES, Config, category_title
from ..events import events_to_csv
from ..i18n import app_name, tr
from ..policy import stage_text
from ..qt import Qt, QtCore, QtGui, QtWidgets, Signal
from .calibration import CalibrationWindow
from .diagnostics import DiagnosticsTab
from .enroll import EnrollDialog
from .login import SetCredentialsDialog, run_dialog
from .widgets import FrameView, dspin, hint, ispin


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


def _yes(parent, title: str, text: str) -> bool:
    return QtWidgets.QMessageBox.question(parent, title, text) == QtWidgets.QMessageBox.StandardButton.Yes


class SettingsDialog(QtWidgets.QDialog):
    _async_done = Signal(str, bool, str)  # (операция, успех, текст)

    def __init__(self, app, parent=None, tab: int = 0):
        super().__init__(parent)
        self.app = app
        self.cfg: Config = app.cfg.copy()
        self.setWindowTitle(tr("{app} — настройки", app=app_name()))
        self.setWindowFlag(Qt.WindowType.WindowMinMaxButtonsHint, True)
        self.resize(940, 760)
        self._async_done.connect(self._on_async_done)

        lay = QtWidgets.QVBoxLayout(self)
        self.tabs = QtWidgets.QTabWidget()
        lay.addWidget(self.tabs)
        self.w_general = _scroll(self._tab_general())
        self.w_camera = self._tab_camera()
        self.w_lock = _scroll(self._tab_lock())
        self.w_gaze = _scroll(self._tab_gaze())
        self.w_notify = _scroll(self._tab_notify())
        self.w_journal = self._tab_journal()
        self.diag = DiagnosticsTab(app)
        self.w_diag = _scroll(self.diag)
        for widget, title in ((self.w_general, tr("Общие")), (self.w_camera, tr("Камера")),
                              (self._tab_faces(), tr("База лиц")), (self.w_lock, tr("Блокировка")),
                              (self.w_gaze, tr("Взгляд")), (self.w_notify, tr("Уведомления")),
                              (self.w_journal, tr("Журнал")), (self.w_diag, tr("Диагностика")),
                              (_scroll(self._tab_account()), tr("Учётная запись"))):
            self.tabs.addTab(widget, title)

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
        self.tabs.currentChanged.connect(
            lambda i: self._refresh_journal() if self.tabs.widget(i) is self.w_journal else None)
        self.tabs.setCurrentIndex(tab)

    # ================================================================ tabs
    def _tab_general(self) -> QtWidgets.QWidget:
        w = QtWidgets.QWidget()
        v = QtWidgets.QVBoxLayout(w)
        box, f = _group(tr("Интерфейс и запуск"))
        self.language = QtWidgets.QComboBox()
        for key, title in (("system", tr("Как в системе")), ("ru", "Русский"), ("en", "English")):
            self.language.addItem(title, key)
        self.tray_color = QtWidgets.QComboBox()
        for key, title in (("auto", tr("Автоматически (по теме оформления)")),
                           ("light", tr("Белые (для тёмной темы)")), ("dark", tr("Чёрные (для светлой темы)"))):
            self.tray_color.addItem(title, key)
        self.autostart = QtWidgets.QCheckBox(tr("Запускать автоматически при входе в систему"))
        f.addRow(tr("Язык интерфейса:"), self.language)
        f.addRow(tr("Цвет значков (меню, трей):"), self.tray_color)
        f.addRow(self.autostart)
        v.addWidget(box)

        box, f = _group(tr("Нагрузка на систему"))
        self.accel = QtWidgets.QComboBox()
        for key, title in (("auto", tr("Автоматически (NPU, если доступен)")), ("npu", "NPU RK3588"),
                           ("cpu", tr("Только процессор (CPU)"))):
            self.accel.addItem(title, key)
        self.npu_core = QtWidgets.QComboBox()
        for key, title in (("auto", tr("Автоматически")), ("0", tr("Ядро 0")), ("1", tr("Ядро 1")),
                           ("2", tr("Ядро 2"))):
            self.npu_core.addItem(title, key)
        self.fps = dspin(0.5, 30, 0.5, 1, tr(" кадр/с"))
        self.idle_fps = dspin(0.2, 30, 0.2, 1, tr(" кадр/с"))
        self.detect_width = QtWidgets.QComboBox()
        for wv in (240, 320, 480, 640):
            self.detect_width.addItem(f"{wv} px", wv)
        self.cpu_cores = QtWidgets.QLineEdit()
        self.nice = ispin(0, 19)
        self.full_scan = dspin(0.2, 10, 0.1, 1, tr(" с"))
        self.gaze_fps = dspin(0.5, 30, 0.5, 1, tr(" раз/с"))
        self.use_mp = QtWidgets.QCheckBox(tr("Точная оценка взгляда по радужке (модель точек лица)"))
        f.addRow(tr("Нейросети выполнять на:"), self.accel)
        f.addRow(tr("Ядро NPU:"), self.npu_core)
        f.addRow(tr("Частота анализа (есть люди):"), self.fps)
        f.addRow(tr("Частота анализа (никого нет):"), self.idle_fps)
        f.addRow(tr("Ширина кадра для детектора (CPU):"), self.detect_width)
        f.addRow(tr("Ядра CPU:"), self.cpu_cores)
        f.addRow(tr("Приоритет (nice):"), self.nice)
        f.addRow(tr("Полный просмотр кадра каждые:"), self.full_scan)
        f.addRow(tr("Оценка взгляда (без предупреждения):"), self.gaze_fps)
        f.addRow(self.use_mp)
        f.addRow(hint(tr("NPU — нейропроцессор RK3588: поиск, распознавание лиц и оценка взгляда выполняются "
                         "на нём, а не на процессоре. Если NPU недоступен, программа сама работает на CPU.")))
        f.addRow(hint(tr("«auto» — только энергоэффективные ядра (на RK3588: A55, cpu0-3), производительные "
                         "ядра A76 остаются другим программам. Пусто — без ограничения. Ядра и приоритет "
                         "применяются после перезапуска программы. Между полными просмотрами кадра лицо ищется "
                         "только возле уже найденных лиц; новое лицо будет замечено не позже, чем через этот "
                         "интервал. Пока рамки нет, взгляд оценивается реже; при появлении рамки — на каждом "
                         "кадре, чтобы она сразу исчезала при возврате взгляда.")))
        v.addWidget(box)

        box, f = _group(tr("Журнал"))
        self.retention = ispin(0, 3650, tr(" дн."))
        f.addRow(tr("Хранить события:"), self.retention)
        f.addRow(hint(tr("0 — хранить бессрочно.")))
        v.addWidget(box)

        self.status_lbl = QtWidgets.QLabel()
        self.status_lbl.setWordWrap(True)
        box, f = _group(tr("Состояние"))
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
        for key, title in (("auto", tr("Автоматически")), ("v4l2", "V4L2"), ("gstreamer", "GStreamer"),
                           ("ffmpeg", "FFmpeg")):
            self.cam_backend.addItem(title, key)
        self.cam_w = ispin(160, 3840)
        self.cam_h = ispin(120, 2160)
        self.cam_fps = ispin(1, 60, tr(" кадр/с"))
        self.cam_rotate = QtWidgets.QComboBox()
        for r in (0, 90, 180, 270):
            self.cam_rotate.addItem(f"{r}°", r)
        self.cam_mirror = QtWidgets.QCheckBox(tr("Зеркально"))
        f.addRow(tr("Источник:"), self.cam_source)
        f.addRow(tr("Драйвер:"), self.cam_backend)
        f.addRow(tr("Ширина:"), self.cam_w)
        f.addRow(tr("Высота:"), self.cam_h)
        f.addRow(tr("Частота захвата:"), self.cam_fps)
        f.addRow(tr("Поворот:"), self.cam_rotate)
        f.addRow(self.cam_mirror)
        f.addRow(hint(tr("Источник: номер камеры (0), устройство (/dev/video0) или конвейер GStreamer "
                         "(для MIPI-камеры RK3588). Изменения вступают в силу по кнопке «Применить».")))
        h.addWidget(left, 0)
        right = QtWidgets.QVBoxLayout()
        self.preview = FrameView()
        right.addWidget(self.preview, 1)
        self.preview_info = QtWidgets.QLabel()
        self.preview_info.setWordWrap(True)
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
        for text, slot in ((tr("Добавить лицо…"), self._face_add), (tr("Добавить образцы…"), self._face_more),
                           (tr("Переименовать…"), self._face_rename), (tr("Удалить"), self._face_remove)):
            b = QtWidgets.QPushButton(text)
            b.clicked.connect(slot)
            row.addWidget(b)
        v.addLayout(row)
        box, f = _group(tr("Распознавание"))
        self.rec_thr = dspin(0.2, 0.9, 0.01, 2)
        self.det_thr = dspin(0.3, 0.99, 0.01, 2)
        self.min_face = ispin(20, 400, " px")
        self.rec_interval = dspin(0.5, 30, 0.5, 1, tr(" с"))
        f.addRow(tr("Порог сходства лица:"), self.rec_thr)
        f.addRow(tr("Порог детектора лиц:"), self.det_thr)
        f.addRow(tr("Мин. размер лица для распознавания:"), self.min_face)
        f.addRow(tr("Перепроверка известных лиц каждые:"), self.rec_interval)
        f.addRow(hint(tr("Порог сходства: выше — строже (меньше ложных «своих», но чаще «посторонний»). "
                         "Рекомендуется 0.36–0.45. Лица мельче минимального размера учитываются только "
                         "как присутствие человека.")))
        v.addWidget(box)
        return w

    def _tab_lock(self) -> QtWidgets.QWidget:
        w = QtWidgets.QWidget()
        v = QtWidgets.QVBoxLayout(w)
        box, f = _group(tr("1. Обнаружение человека"))
        self.leave_debounce = dspin(0.5, 60, 0.5, 1, tr(" с"))
        f.addRow(tr("Человек считается ушедшим через:"), self.leave_debounce)
        v.addWidget(box)

        box, f = _group(tr("3. Блокировка, если перед экраном никого нет"))
        self.lock_abs = QtWidgets.QCheckBox(tr("Включено"))
        self.abs_timeout = dspin(1, 86400, 5, 0, tr(" с"))
        f.addRow(self.lock_abs)
        f.addRow(tr("Таймаут:"), self.abs_timeout)
        v.addWidget(box)

        box, f = _group(tr("4. Блокировка, если нет авторизованного лица (даже при наличии других)"))
        self.lock_unauth = QtWidgets.QCheckBox(tr("Включено"))
        self.unauth_timeout = dspin(1, 86400, 1, 0, tr(" с"))
        f.addRow(self.lock_unauth)
        f.addRow(tr("Таймаут:"), self.unauth_timeout)
        v.addWidget(box)

        box, f = _group(tr("5. Блокировка при появлении постороннего лица (даже рядом с авторизованным)"))
        self.lock_stranger = QtWidgets.QCheckBox(tr("Включено"))
        self.stranger_confirm = dspin(0, 60, 0.5, 1, tr(" с"))
        f.addRow(self.lock_stranger)
        f.addRow(tr("Время подтверждения:"), self.stranger_confirm)
        f.addRow(hint(tr("Постороннее лицо должно быть видно указанное время — это защищает от ложных "
                         "срабатываний. Пункты 4 и 5 работают, только если база лиц не пуста.")))
        v.addWidget(box)

        box, f = _group(tr("Способ блокировки"))
        self.lock_method = QtWidgets.QComboBox()
        self.lock_method.addItem(tr("Автоматически (loginctl / D-Bus / xflock4 / …)"), "auto")
        self.lock_method.addItem(tr("Своя команда"), "custom")
        self.lock_cmd = QtWidgets.QLineEdit()
        self.lock_cmd.setPlaceholderText(tr("например: loginctl lock-session"))
        self.relock = dspin(3, 3600, 1, 0, tr(" с"))
        test = QtWidgets.QPushButton(tr("Проверить блокировку сейчас"))
        test.clicked.connect(self._test_lock)
        f.addRow(tr("Метод:"), self.lock_method)
        f.addRow(tr("Команда:"), self.lock_cmd)
        f.addRow(tr("Повторная блокировка через:"), self.relock)
        f.addRow(test)
        f.addRow(hint(tr("Повторная блокировка выполняется, если после разблокировки условие "
                         "по-прежнему выполняется (и окружение сообщает состояние блокировки).")))
        v.addWidget(box)
        v.addStretch(1)
        return w

    def _tab_gaze(self) -> QtWidgets.QWidget:
        w = QtWidgets.QWidget()
        v = QtWidgets.QVBoxLayout(w)
        box, f = _group(tr("6. Контроль взгляда авторизованного лица"))
        self.gaze_on = QtWidgets.QCheckBox(tr("Включено"))
        self.t1 = dspin(0, 3600, 0.5, 1, tr(" с"))
        self.t2 = dspin(0, 3600, 0.5, 1, tr(" с"))
        self.t3 = dspin(0, 3600, 0.5, 1, tr(" с"))
        self.t4 = dspin(1, 86400, 5, 0, tr(" с"))
        self.t4_label = QtWidgets.QLabel(tr("Уведомление на e-mail через:"))
        self.t4_hint = hint("")
        self.ret_debounce = dspin(0, 5, 0.1, 1, tr(" с"))
        self.lost_away = QtWidgets.QCheckBox(tr("Пропажа лица из кадра (отвернулся) = взгляд не на экране"))
        self.closed_away = QtWidgets.QCheckBox(tr("Закрытые глаза = взгляд не на экране"))
        f.addRow(self.gaze_on)
        f.addRow(tr("Красная рамка через:"), self.t1)
        f.addRow(tr("Мигающая рамка через:"), self.t2)
        f.addRow(tr("Звуковой сигнал через:"), self.t3)
        f.addRow(self.t4_label, self.t4)
        f.addRow(self.t4_hint)
        f.addRow(hint(tr("Время отсчитывается с момента, когда взгляд ушёл с экрана; мигание включается не "
                         "раньше красной рамки, а звук — не раньше мигания. При возвращении взгляда таймеры "
                         "сбрасываются, рамка и звук отключаются.")))
        f.addRow(tr("Взгляд считается вернувшимся через:"), self.ret_debounce)
        f.addRow(self.lost_away)
        f.addRow(self.closed_away)
        v.addWidget(box)

        box, f = _group(tr("Зона экрана (градусы относительно направления на камеру)"))
        self.yaw_min = dspin(-90, 90, 1, 1, "°")
        self.yaw_max = dspin(-90, 90, 1, 1, "°")
        self.pitch_min = dspin(-90, 90, 1, 1, "°")
        self.pitch_max = dspin(-90, 90, 1, 1, "°")
        self.zone_margin = dspin(0, 30, 0.5, 1, "°")
        self.eye_gain = dspin(0.5, 5, 0.1, 1)
        f.addRow(tr("По горизонтали от:"), self.yaw_min)
        f.addRow(tr("По горизонтали до:"), self.yaw_max)
        f.addRow(tr("По вертикали от (вниз):"), self.pitch_min)
        f.addRow(tr("По вертикали до (вверх):"), self.pitch_max)
        f.addRow(tr("Допуск:"), self.zone_margin)
        f.addRow(tr("Коэффициент поворота глаз:"), self.eye_gain)
        self.calib_state = QtWidgets.QLabel()
        f.addRow(self.calib_state)
        row = QtWidgets.QHBoxLayout()
        b = QtWidgets.QPushButton(tr("Калибровать…"))
        b.clicked.connect(self._calibrate)
        row.addWidget(b)
        b = QtWidgets.QPushButton(tr("Сбросить к значениям по умолчанию"))
        b.clicked.connect(self._reset_zone)
        row.addWidget(b)
        f.addRow(row)
        self.gaze_live = QtWidgets.QLabel("—")
        f.addRow(tr("Сейчас:"), self.gaze_live)
        f.addRow(hint(tr("Камера расположена по центру верхней кромки, поэтому при взгляде на экран угол "
                         "по вертикали отрицательный. Калибровка (5 точек) настраивает зону под конкретного "
                         "пользователя и монитор — выполните её сидя в обычном рабочем положении.")))
        v.addWidget(box)

        box, f = _group(tr("Рамка"))
        self.border_w = ispin(2, 100, " px")
        self.border_color = QtWidgets.QPushButton()
        self.border_color.clicked.connect(self._pick_color)
        self.blink_ms = ispin(100, 3000, tr(" мс"))
        f.addRow(tr("Толщина:"), self.border_w)
        f.addRow(tr("Цвет:"), self.border_color)
        f.addRow(tr("Период мигания:"), self.blink_ms)
        row = QtWidgets.QHBoxLayout()
        for text, stage in ((tr("Показать рамку"), 1), (tr("Мигающая"), 2), (tr("Скрыть"), 0)):
            b = QtWidgets.QPushButton(text)
            b.clicked.connect(lambda _=False, s=stage: self._preview_border(s))
            row.addWidget(b)
        f.addRow(row)
        v.addWidget(box)

        box, f = _group(tr("Звуковой сигнал"))
        self.sound = QtWidgets.QComboBox()
        row = QtWidgets.QHBoxLayout()
        row.addWidget(self.sound, 1)
        for text, slot in (("▶", self._sound_play), ("■", self._sound_stop), (tr("Загрузить…"), self._sound_upload),
                           (tr("Удалить"), self._sound_delete)):
            b = QtWidgets.QPushButton(text)
            b.clicked.connect(slot)
            row.addWidget(b)
        f.addRow(tr("Сигнал:"), row)
        self.sound_repeat = dspin(0, 60, 0.5, 1, tr(" с"))
        self.volume = QtWidgets.QSlider(Qt.Orientation.Horizontal)
        self.volume.setRange(0, 100)
        f.addRow(tr("Пауза между повторами:"), self.sound_repeat)
        f.addRow(tr("Громкость:"), self.volume)
        f.addRow(hint(tr("Свои сигналы: WAV, OGG, MP3, FLAC (для MP3 нужен ffplay или mpv).")))
        v.addWidget(box)
        v.addStretch(1)
        return w

    def _tab_notify(self) -> QtWidgets.QWidget:
        w = QtWidgets.QWidget()
        v = QtWidgets.QVBoxLayout(w)
        box, f = _group(tr("Куда направлять события"))
        grid = QtWidgets.QGridLayout()
        columns = [("email", tr("E-mail сразу")), ("log", tr("В журнал")),
                   ("digest", tr("Журнал + e-mail по расписанию"))]
        grid.addWidget(QtWidgets.QLabel("<b>" + tr("Событие") + "</b>"), 0, 0)
        for c, (_, title) in enumerate(columns, 1):
            grid.addWidget(QtWidgets.QLabel(f"<b>{title}</b>"), 0, c)
        self.routes = {}
        for r, key in enumerate(EVENT_CATEGORIES, 1):
            grid.addWidget(QtWidgets.QLabel(category_title(key)), r, 0)
            boxes = {}
            for c, (col, _) in enumerate(columns, 1):
                cb = QtWidgets.QCheckBox()
                grid.addWidget(cb, r, c, Qt.AlignmentFlag.AlignCenter)
                boxes[col] = cb
            boxes["digest"].toggled.connect(lambda on, b=boxes: on and b["log"].setChecked(True))
            boxes["log"].toggled.connect(lambda on, b=boxes: (not on) and b["digest"].setChecked(False))
            self.routes[key] = boxes
        self.routes["gaze"]["email"].toggled.connect(self._update_t4)
        f.addRow(grid)
        f.addRow(hint(tr("Для контроля взгляда «E-mail сразу» означает одно письмо, если взгляд не на экране "
                         "дольше времени, заданного на вкладке «Взгляд» («Уведомление на e-mail через»).")))
        self.save_snaps = QtWidgets.QCheckBox(tr("Сохранять снимок с камеры для событий в журнале"))
        f.addRow(self.save_snaps)
        v.addWidget(box)

        box, f = _group(tr("Почтовый сервер (SMTP)"))
        self.smtp_host = QtWidgets.QLineEdit()
        self.smtp_port = ispin(1, 65535)
        self.smtp_sec = QtWidgets.QComboBox()
        for key, title in (("starttls", "STARTTLS"), ("ssl", "SSL/TLS"), ("none", tr("Без шифрования"))):
            self.smtp_sec.addItem(title, key)
        self.smtp_user = QtWidgets.QLineEdit()
        self.smtp_pass = QtWidgets.QLineEdit()
        self.smtp_pass.setEchoMode(QtWidgets.QLineEdit.EchoMode.Password)
        self.smtp_from = QtWidgets.QLineEdit()
        self.smtp_to = QtWidgets.QLineEdit()
        self.smtp_to.setPlaceholderText("security@example.com, admin@example.com")
        self.smtp_prefix = QtWidgets.QLineEdit()
        self.attach_snap = QtWidgets.QCheckBox(tr("Прикладывать снимок с камеры к письму"))
        f.addRow(tr("Сервер:"), self.smtp_host)
        f.addRow(tr("Порт:"), self.smtp_port)
        f.addRow(tr("Шифрование:"), self.smtp_sec)
        f.addRow(tr("Логин:"), self.smtp_user)
        f.addRow(tr("Пароль:"), self.smtp_pass)
        f.addRow(tr("Отправитель:"), self.smtp_from)
        f.addRow(tr("Получатель(и):"), self.smtp_to)
        f.addRow(tr("Префикс темы:"), self.smtp_prefix)
        f.addRow(self.attach_snap)
        b = QtWidgets.QPushButton(tr("Отправить тестовое письмо"))
        b.clicked.connect(self._test_mail)
        f.addRow(b)
        v.addWidget(box)

        box, f = _group(tr("Отчёт по расписанию"))
        self.sched_mode = QtWidgets.QComboBox()
        self.sched_mode.addItem(tr("Каждые N минут"), "interval")
        self.sched_mode.addItem(tr("Ежедневно в указанное время"), "daily")
        self.sched_interval = ispin(1, 100000, tr(" мин"))
        self.sched_times = QtWidgets.QLineEdit()
        self.sched_times.setPlaceholderText("09:00, 13:00, 18:00")
        self.sched_empty = QtWidgets.QCheckBox(tr("Отправлять отчёт, даже если новых событий нет"))
        f.addRow(tr("Расписание:"), self.sched_mode)
        f.addRow(tr("Интервал:"), self.sched_interval)
        f.addRow(tr("Время (ЧЧ:ММ через запятую):"), self.sched_times)
        f.addRow(self.sched_empty)
        self.sched_next = QtWidgets.QLabel()
        f.addRow(tr("Следующий отчёт:"), self.sched_next)
        b = QtWidgets.QPushButton(tr("Отправить отчёт сейчас"))
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
        self.j_filter.addItem(tr("Все события"), "")
        for key in EVENT_CATEGORIES:
            self.j_filter.addItem(category_title(key), key)
        self.j_filter.currentIndexChanged.connect(self._refresh_journal)
        row.addWidget(self.j_filter, 1)
        for text, slot in ((tr("Обновить"), self._refresh_journal), (tr("Экспорт CSV…"), self._export_journal),
                           (tr("Очистить…"), self._clear_journal)):
            b = QtWidgets.QPushButton(text)
            b.clicked.connect(slot)
            row.addWidget(b)
        v.addLayout(row)
        self.journal = QtWidgets.QTableWidget(0, 3)
        self.journal.setHorizontalHeaderLabels([tr("Время"), tr("Категория"), tr("Событие")])
        self.journal.horizontalHeader().setStretchLastSection(True)
        self.journal.setEditTriggers(QtWidgets.QAbstractItemView.EditTrigger.NoEditTriggers)
        self.journal.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectionBehavior.SelectRows)
        self.journal.cellDoubleClicked.connect(self._open_snapshot)
        v.addWidget(self.journal, 1)
        v.addWidget(hint(tr("Двойной щелчок — открыть снимок с камеры (если сохранён). "
                            "Показаны последние 2000 событий.")))
        self._journal_events = []
        return w

    def _tab_account(self) -> QtWidgets.QWidget:
        w = QtWidgets.QWidget()
        v = QtWidgets.QVBoxLayout(w)
        box, f = _group(tr("Администратор"))
        self.acc_label = QtWidgets.QLabel()
        f.addRow(tr("Логин:"), self.acc_label)
        b = QtWidgets.QPushButton(tr("Сменить логин/пароль…"))
        b.clicked.connect(self._change_password)
        f.addRow(b)
        f.addRow(hint(tr("Логин и пароль требуются для входа в настройки, приостановки контроля и выхода "
                         "из программы. Пароль хранится в виде хеша PBKDF2-SHA256.")))
        v.addWidget(box)
        v.addStretch(1)
        return w

    # ======================================================== load / save
    def _load(self) -> None:
        c = self.cfg
        self.language.setCurrentIndex(max(0, self.language.findData(c.general.language)))
        self.tray_color.setCurrentIndex(max(0, self.tray_color.findData(c.general.tray_icon_color)))
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
        self.accel.setCurrentIndex(max(0, self.accel.findData(p.accelerator)))
        self.npu_core.setCurrentIndex(max(0, self.npu_core.findData(str(p.npu_core))))
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
        self.t4.setValue(g.t4_s)
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
        self._update_t4()

    def _collect(self) -> Config:
        c = self.cfg.copy()
        c.general.language = self.language.currentData()
        c.general.tray_icon_color = self.tray_color.currentData()
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
        p.accelerator = self.accel.currentData()
        p.npu_core = self.npu_core.currentData()
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
        g.t4_s = self.t4.value()
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
            problems.append(tr("Мигающая рамка не может включаться раньше красной, а звуковой сигнал — "
                               "раньше мигающей рамки."))
        if c.schedule.mode == "daily":
            try:
                if not mailer_mod.parse_times(c.schedule.daily_times):
                    problems.append(tr("Не указано время отчёта."))
            except ValueError as exc:
                problems.append(str(exc))
        if c.lock.method == "custom" and not c.lock.custom_command:
            problems.append(tr("Не указана своя команда блокировки."))
        uses_mail = any(r.email or r.digest for r in c.notify.routes.values())
        if uses_mail and not mailer_mod.is_configured(c.email):
            problems.append(tr("Для отправки событий по e-mail укажите SMTP-сервер и получателя "
                               "(до этого события по расписанию будут накапливаться в журнале)."))
            if len(problems) == 1:
                QtWidgets.QMessageBox.information(self, tr("E-mail не настроен"), problems[0])
                return True
        if problems:
            QtWidgets.QMessageBox.warning(self, tr("Проверьте настройки"), "\n".join(problems))
            return False
        return True

    def _apply(self) -> bool:
        c = self._collect()
        if not self._validate(c):
            return False
        lang_changed = c.general.language != self.cfg.general.language
        self.cfg = c
        self.app.apply_config(c)
        if lang_changed:
            # интерфейс пересоздаётся на новом языке, открытая вкладка сохраняется
            QtCore.QTimer.singleShot(0, lambda i=self.tabs.currentIndex(): self.app.reopen_settings(i))
        return True

    def _ok(self) -> None:
        if self._apply():
            self.accept()

    def done(self, r):  # noqa: D401
        self._timer.stop()
        self.diag.stop()
        self.app.engine.preview_enabled = False
        self.app.sound.stop()
        self.app.refresh_gaze_outputs()
        super().done(r)

    # ============================================================ helpers
    def _update_t4(self) -> None:
        on = self.routes["gaze"]["email"].isChecked()
        self.t4.setEnabled(on)
        self.t4_label.setEnabled(on)
        self.t4_hint.setText("" if on else tr("Недоступно: включите «E-mail сразу» для событий контроля взгляда "
                                              "на вкладке «Уведомления»."))
        self.t4_hint.setVisible(not on)

    def _tick(self) -> None:
        eng = self.app.engine
        st = eng.status
        cur = self.tabs.currentWidget()
        if cur is self.w_camera:
            self.preview.show_frame(eng.get_preview())
            self.preview_info.setText(tr("Обработка: {fps:.1f} кадр/с · нейросети: {acc} · лиц: {faces} · "
                                         "оценка взгляда: {gaze}", fps=st.fps, acc=st.accelerator or "—",
                                         faces=st.faces, gaze=st.gaze_method or "—"))
        elif cur is self.w_gaze:
            lg = eng.latest_gaze()
            if lg is not None:
                s = lg[1]
                m = self.zone_margin.value()
                zone_ok = (self.yaw_min.value() - m <= s.yaw <= self.yaw_max.value() + m) and \
                          (self.pitch_min.value() - m <= s.pitch <= self.pitch_max.value() + m)
                self.gaze_live.setText(
                    tr("по горизонтали {yaw:+.1f}°, по вертикали {pitch:+.1f}° — {where}{closed}; стадия: {stage}",
                       yaw=s.yaw, pitch=s.pitch, where=tr("на экране") if zone_ok else tr("мимо экрана"),
                       closed=tr(" (глаза закрыты)") if s.eyes_closed else "", stage=stage_text(st.gaze_stage)))
        elif cur is self.w_general:
            self.status_lbl.setText(self.app.status_text())
        elif cur is self.w_notify and self.app.scheduler.next_run:
            self.sched_next.setText(self.app.scheduler.next_run.strftime("%Y-%m-%d %H:%M"))

    def _set_zone_widgets(self, ymin, ymax, pmin, pmax) -> None:
        self.yaw_min.setValue(ymin)
        self.yaw_max.setValue(ymax)
        self.pitch_min.setValue(pmin)
        self.pitch_max.setValue(pmax)

    def _update_calib_label(self) -> None:
        self.calib_state.setText(tr("Зона откалибрована") if self._calibrated
                                 else tr("Калибровка не выполнялась (используются значения по умолчанию)"))

    def _calibrate(self) -> None:
        if self.app.engine.status.state != "running":
            QtWidgets.QMessageBox.warning(self, tr("Калибровка"), tr("Камера не работает или контроль приостановлен."))
            return
        self.hide()
        self._calib = CalibrationWindow(self.app.engine, self.zone_margin.value())
        self._calib.calibrated.connect(self._calibrated_done)
        self._calib.start()

    def _calibrated_done(self, zone) -> None:
        self.show()
        self.raise_()
        if zone is None:
            QtWidgets.QMessageBox.warning(self, tr("Калибровка"), self._calib.error or tr("Калибровка не выполнена"))
            return
        self._set_zone_widgets(zone.yaw_min, zone.yaw_max, zone.pitch_min, zone.pitch_max)
        self._calibrated = True
        self._update_calib_label()
        QtWidgets.QMessageBox.information(
            self, tr("Калибровка"),
            tr("Зона экрана: по горизонтали {y1:+.0f}…{y2:+.0f}°, по вертикали {p1:+.0f}…{p2:+.0f}°.\n"
               "Нажмите «Применить».", y1=zone.yaw_min, y2=zone.yaw_max, p1=zone.pitch_min, p2=zone.pitch_max))

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
        col = QtWidgets.QColorDialog.getColor(QtGui.QColor(self._color), self, tr("Цвет рамки"))
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
        path, _ = QtWidgets.QFileDialog.getOpenFileName(self, tr("Звуковой файл"), "",
                                                        tr("Звук") + " (*.wav *.ogg *.oga *.mp3 *.flac)")
        if not path:
            return
        try:
            sid = sound_mod.import_sound(Path(path))
        except (OSError, ValueError) as exc:
            QtWidgets.QMessageBox.warning(self, tr("Ошибка"), str(exc))
            return
        self._reload_sounds(sid)

    def _sound_delete(self) -> None:
        sid = self.sound.currentData()
        try:
            sound_mod.delete_sound(sid)
        except (OSError, ValueError) as exc:
            QtWidgets.QMessageBox.warning(self, tr("Удаление"), str(exc))
            return
        self._reload_sounds("builtin:beep")

    # ------------------------------------------------------------- faces
    def _reload_faces(self) -> None:
        self.faces.clear()
        for p in self.app.db.persons():
            item = QtWidgets.QListWidgetItem(tr("{name}  (образцов: {n})", name=p.name, n=p.samples))
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
            QtWidgets.QMessageBox.warning(self, tr("База лиц"), tr("Модели распознавания не загружены."))
            return
        if run_dialog(EnrollDialog(self.app.engine, self.app.db, None, self)):
            self.app.publish_system("face_added", tr("В базу авторизованных лиц добавлено лицо"))
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
        name, ok = QtWidgets.QInputDialog.getText(self, tr("Переименовать"), tr("Имя:"), text=person.name)
        if ok and name.strip():
            self.app.db.rename(pid, name)
            self._reload_faces()

    def _face_remove(self) -> None:
        pid = self._selected_face()
        person = self.app.db.get(pid) if pid else None
        if not person:
            return
        if _yes(self, tr("Удаление"), tr("Удалить «{name}» из базы?", name=person.name)):
            self.app.db.remove(pid)
            self.app.publish_system("face_removed",
                                    tr("Из базы авторизованных лиц удалено лицо «{name}»", name=person.name))
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
            msg = mailer_mod.build_message(cfg, tr("Тестовое письмо"),
                                           tr("Это тестовое письмо программы {app}.", app=app_name()) + "\n"
                                           + mailer_mod.host_info())
            mailer_mod.send_message(cfg, msg)
            return True, tr("Письмо отправлено. Проверьте почтовый ящик.")
        self._run_async(tr("Тестовое письмо"), fn)

    def _digest_now(self) -> None:
        self._apply()
        self._run_async(tr("Отчёт"), lambda: self.app.scheduler.send_digest(force=True))

    def _test_lock(self) -> None:
        c = self._collect()
        if not _yes(self, tr("Проверка"), tr("Заблокировать экран сейчас?")):
            return
        from ..locker import ScreenLocker
        locker = ScreenLocker(c.lock.method, c.lock.custom_command)

        def fn():
            ok = locker.lock()
            return ok, (tr("Команда блокировки выполнена успешно.") if ok else
                        tr("Не найдено работающей команды блокировки — укажите свою команду."))
        self._run_async(tr("Блокировка"), fn)

    # ------------------------------------------------------------ journal
    def _refresh_journal(self) -> None:
        cat = self.j_filter.currentData() or None
        self._journal_events = self.app.store.query(limit=2000, category=cat)
        self.journal.setRowCount(len(self._journal_events))
        for r, ev in enumerate(self._journal_events):
            for c, text in enumerate((ev.time_str, ev.category_title, ev.message)):
                item = QtWidgets.QTableWidgetItem(text)
                if c == 2 and ev.snapshot_path:
                    item.setToolTip(tr("Есть снимок — двойной щелчок"))
                self.journal.setItem(r, c, item)
        self.journal.resizeColumnsToContents()

    def _export_journal(self) -> None:
        path, _ = QtWidgets.QFileDialog.getSaveFileName(
            self, tr("Экспорт журнала"), f"camai-{datetime.now():%Y%m%d-%H%M}.csv", "CSV (*.csv)")
        if path:
            cat = self.j_filter.currentData() or None
            Path(path).write_text(events_to_csv(self.app.store.query(limit=10 ** 9, category=cat)),
                                  encoding="utf-8-sig")

    def _clear_journal(self) -> None:
        if _yes(self, tr("Журнал"), tr("Удалить все события из журнала?")):
            self.app.store.clear()
            self.app.publish_system("journal_cleared", tr("Журнал событий очищен администратором"))
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
            self.app.publish_system("password_changed", tr("Учётные данные администратора изменены"))
            QtWidgets.QMessageBox.information(self, tr("Учётная запись"), tr("Логин и пароль изменены."))
