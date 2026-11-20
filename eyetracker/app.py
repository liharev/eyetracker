"""Фоновое приложение: значок в трее, рамка, звук, связь движка с интерфейсом."""
from __future__ import annotations

import getpass
import logging
import time
from typing import Optional

from . import APP_ID, auth, autostart, i18n, icons, paths
from . import sound as sound_mod
from .config import Config, ConfigStore
from .engine import Engine, EngineStatus
from .events import Event, EventDispatcher, EventStore
from .mailer import DigestScheduler, Mailer
from .overlay import BorderOverlay
from .i18n import app_name, tr
from .policy import GazeStage, stage_text
from .qt import QT_API, QtCore, QtGui, QtNetwork, QtWidgets, Signal, exec_
from .ui.login import LoginDialog, SetCredentialsDialog, run_dialog
from .vision.recognizer import FaceDatabase

log = logging.getLogger(__name__)

SERVER_NAME = f"{APP_ID}-{getpass.getuser()}"


class _Bridge(QtCore.QObject):
    """Передача сигналов из потока движка в GUI-поток."""
    status = Signal(object)
    stage = Signal(int)
    event = Signal(object)


class TrayApp(QtCore.QObject):
    def __init__(self, qapp: QtWidgets.QApplication, store: ConfigStore, cfg: Config,
                 allow_download: bool = True):
        super().__init__()
        self.qapp = qapp
        self.config_store = store
        self.cfg = cfg
        self.guard = auth.LoginGuard()
        self._settings = None
        self._busy_dialog = False

        sound_mod.ensure_builtin_sounds()
        self.db = FaceDatabase(paths.faces_dir())
        self.store = EventStore(paths.events_db(), paths.snapshots_dir())
        self.mailer = Mailer(cfg.email)
        self.dispatcher = EventDispatcher(cfg, self.store, self.mailer)
        self.scheduler = DigestScheduler(lambda: self.cfg, self.store, self.mailer,
                                         paths.data_dir() / "state.json")
        self.engine = Engine(cfg, self.db, self.dispatcher, allow_download=allow_download)
        self.sound = sound_mod.SoundPlayer()
        g = cfg.gaze
        self.overlay = BorderOverlay(g.border_width, g.border_color, g.blink_interval_ms, self)

        self.bridge = _Bridge()
        self.bridge.status.connect(self._on_status)
        self.bridge.stage.connect(self._on_stage)
        self.engine.on_status = self.bridge.status.emit
        self.engine.on_gaze_stage = self.bridge.stage.emit
        self._stage = GazeStage.NORMAL
        self._last_icon_key = None

        self._icons = {}
        self._build_tray_icons()
        self._blink_on = True
        self._blink = QtCore.QTimer(self)
        self._blink.setInterval(600)
        self._blink.timeout.connect(self._blink_tick)
        self.tray = QtWidgets.QSystemTrayIcon(self._icons["idle"], self)
        self.tray.setToolTip(app_name())
        self._build_menu()
        self.tray.activated.connect(self._on_tray_activated)
        if not QtWidgets.QSystemTrayIcon.isSystemTrayAvailable():
            log.warning("Системный трей недоступен: настройки можно открыть командой "
                        "«python3 -m eyetracker --settings»")
        self.tray.show()

        self._housekeeping = QtCore.QTimer(self)
        self._housekeeping.timeout.connect(self._daily)
        self._housekeeping.start(6 * 3600 * 1000)

        self._server = QtNetwork.QLocalServer(self)
        QtNetwork.QLocalServer.removeServer(SERVER_NAME)
        self._server.listen(SERVER_NAME)
        self._server.newConnection.connect(self._on_ipc)

    # ------------------------------------------------------------ lifecycle
    def start(self) -> None:
        # пункт меню, значки и автозапуск — в актуальном состоянии (в т.ч. после обновления программы)
        autostart.ensure_desktop_integration(self.cfg.general.autostart)
        self.engine.start()
        self.scheduler.start()
        self._daily()
        self.publish_system("app_started", tr("{app} запущен (Qt: {qt})", app=app_name(), qt=QT_API))

    def shutdown(self) -> None:
        self.publish_system("app_stopped", tr("{app} остановлен", app=app_name()))
        self.sound.stop()
        self.overlay.set_state(False, False)
        self.engine.stop()
        self.scheduler.stop()
        self.mailer.stop()
        self.store.close()
        self.tray.hide()

    def _daily(self) -> None:
        n = self.store.purge(self.cfg.general.log_retention_days)
        if n:
            log.info("Удалено устаревших событий: %d", n)

    # ---------------------------------------------------------------- config
    def save_config(self) -> None:
        self.config_store.save(self.cfg)

    def apply_config(self, cfg: Config) -> None:
        old = self.cfg
        self.cfg = cfg.copy()
        self.save_config()
        if old.general.language != self.cfg.general.language:
            set_language(self.qapp, self.cfg.general.language)
            self._build_menu()
            self._last_icon_key = None
        if old.general.tray_icon_color != self.cfg.general.tray_icon_color:
            self._build_tray_icons()
            self._last_icon_key = None
        self.engine.apply_config(self.cfg)
        self.dispatcher.set_config(self.cfg)
        self.mailer.set_config(self.cfg.email)
        if old.schedule != self.cfg.schedule:
            self.scheduler.reschedule()
        g = self.cfg.gaze
        self.overlay.configure(g.border_width, g.border_color, g.blink_interval_ms)
        try:
            autostart.set_enabled(self.cfg.general.autostart)
        except OSError as exc:
            log.warning("Автозапуск: %s", exc)
        self.publish_system("settings_changed", tr("Настройки изменены администратором"))
        self.refresh_gaze_outputs()

    def publish_system(self, etype: str, message: str, details: Optional[dict] = None) -> None:
        self.dispatcher.publish(Event("system", etype, message, details or {}))

    # ----------------------------------------------------------------- tray
    def _tray_color(self) -> str:
        mode = self.cfg.general.tray_icon_color
        if mode == "light":
            return "#fcfcfc"
        if mode == "dark":
            return "#232629"
        return self.qapp.palette().color(QtGui.QPalette.ColorRole.WindowText).name()

    def _build_tray_icons(self) -> None:
        """Монохромный логотип; состояние — видом центральной точки."""
        color = self._tray_color()
        filled, hollow = icons.tray_icon(color, "filled"), icons.tray_icon(color, "hollow")
        self._icons = {
            "ok": filled,                                   # авторизованный пользователь у экрана
            "idle": hollow,                                 # перед экраном никого нет
            "warn": hollow,                                 # лицо ещё не распознано
            "alert": filled, "alert_off": hollow,           # посторонний / взгляд не на экране — мигает
            "paused": icons.tray_icon(color, "pause"),
            "error": icons.tray_icon(color, "cross"),
        }

    def _blink_tick(self) -> None:
        self._blink_on = not self._blink_on
        self.tray.setIcon(self._icons["alert" if self._blink_on else "alert_off"])

    def _build_menu(self) -> None:
        menu = QtWidgets.QMenu()
        self._status_action = menu.addAction(tr("Запуск…"))
        self._status_action.setEnabled(False)
        menu.addSeparator()
        menu.addAction(tr("Настройки…"), self.open_settings)
        pause_menu = menu.addMenu(tr("Приостановить контроль"))
        for minutes in (5, 15, 30, 60):
            pause_menu.addAction(tr("на {n} мин", n=minutes), lambda m=minutes: self._pause(m))
        self._resume_action = menu.addAction(tr("Возобновить контроль"), self._resume)
        self._resume_action.setVisible(self.engine.paused)
        menu.addSeparator()
        menu.addAction(tr("Выход"), self._quit)
        old = getattr(self, "_menu", None)
        self._menu = menu
        if hasattr(self, "tray"):
            self.tray.setContextMenu(menu)
        if old is not None:
            old.deleteLater()

    def _on_tray_activated(self, reason) -> None:
        if reason == QtWidgets.QSystemTrayIcon.ActivationReason.DoubleClick:
            self.open_settings()

    def _authorize(self, purpose: str) -> bool:
        if self._busy_dialog:
            return False
        self._busy_dialog = True
        try:
            if not auth.is_configured(self.cfg.auth):
                dlg = SetCredentialsDialog(self.cfg.auth.__class__(), True)
                if not run_dialog(dlg):
                    return False
                self.cfg.auth = dlg.auth_cfg
                self.save_config()
                self.publish_system("credentials_created", tr("Заданы учётные данные администратора"))
                return True
            dlg = LoginDialog(self.cfg.auth, self.guard, purpose)
            ok = run_dialog(dlg)
            if dlg.failures:
                self.publish_system("login_failed",
                                    tr("Неудачные попытки входа ({purpose}): {n}", purpose=purpose, n=dlg.failures),
                                    {"username": dlg.failed_user})
            if ok:
                self.publish_system("login_ok", tr("Вход администратора: {purpose}", purpose=purpose))
            return ok
        finally:
            self._busy_dialog = False

    def open_settings(self, tab: int = 0, authorized: bool = False) -> None:
        if self._settings is not None:
            self._settings.show()
            self._settings.raise_()
            self._settings.activateWindow()
            return
        if not authorized and not self._authorize(tr("Вход в настройки")):
            return
        from .ui.settings import SettingsDialog

        self._settings = SettingsDialog(self, tab=tab)
        self._settings.finished.connect(self._settings_closed)
        self._settings.show()
        self._settings.raise_()
        self._settings.activateWindow()

    def _settings_closed(self, *_):
        if self._settings is not None:
            self._settings.deleteLater()
        self._settings = None

    def reopen_settings(self, tab: int = 0) -> None:
        """Пересоздать окно настроек (после смены языка) без повторного ввода пароля."""
        if self._settings is not None:
            dlg, self._settings = self._settings, None
            dlg.finished.disconnect(self._settings_closed)
            dlg.close()
            dlg.deleteLater()
        self.open_settings(tab, authorized=True)

    def _pause(self, minutes: int) -> None:
        if self._authorize(tr("Приостановка контроля на {n} мин", n=minutes)):
            self.engine.pause(minutes * 60)
            self.publish_system("paused", tr("Контроль приостановлен на {n} мин", n=minutes))

    def _resume(self) -> None:
        self.engine.resume()
        self.publish_system("resumed", tr("Контроль возобновлён"))

    def _quit(self) -> None:
        if self._authorize(tr("Выход из программы")):
            self.qapp.quit()

    def _on_ipc(self) -> None:
        conn = self._server.nextPendingConnection()
        if conn is None:
            return
        conn.waitForReadyRead(500)
        cmd = bytes(conn.readAll()).decode(errors="ignore").strip()
        conn.disconnectFromServer()
        if cmd == "settings":
            QtCore.QTimer.singleShot(0, self.open_settings)

    # ------------------------------------------------------------ feedback
    def status_text(self, st: Optional[EngineStatus] = None) -> str:
        st = st or self.engine.status
        if st.state == "error":
            return tr("Ошибка: {msg}", msg=st.message)
        if st.state == "camera_error":
            return tr("Камера: {msg}", msg=st.message)
        if st.state == "starting":
            return tr("Запуск…")
        parts = []
        if st.state == "paused":
            parts.append(tr("Пауза ({n} мин)", n=int(st.paused_until // 60) + 1))
        if st.faces == 0:
            parts.append(tr("перед экраном никого нет"))
        else:
            parts.append(tr("лиц: {n}", n=st.faces))
            if st.authorized:
                parts.append(tr("авторизованы: {names}", names=", ".join(st.authorized)))
            if st.unknown:
                parts.append(tr("посторонних: {n}", n=st.unknown))
        if self.cfg.gaze.enabled and st.authorized:
            parts.append(tr("взгляд: {state}", state=tr("на экране") if st.on_screen else tr("не на экране")))
        if st.message:
            parts.append(st.message)
        return "; ".join(parts)

    def _on_status(self, st: EngineStatus) -> None:
        text = self.status_text(st)
        self._status_action.setText(text if len(text) < 90 else text[:87] + "…")
        self._resume_action.setVisible(st.state == "paused")
        if st.state in ("error", "camera_error"):
            key = "error"
        elif st.state == "paused":
            key = "paused"
        elif st.unknown or st.gaze_stage > 0:
            key = "alert"
        elif st.authorized:
            key = "ok"
        elif st.faces:
            key = "warn"
        else:
            key = "idle"
        tooltip = f"{app_name()}: {text}"
        if key != self._last_icon_key:
            self.tray.setIcon(self._icons[key])
            self._last_icon_key = key
            if key == "alert":
                self._blink_on = True
                self._blink.start()
            else:
                self._blink.stop()
        if self.tray.toolTip() != tooltip:
            self.tray.setToolTip(tooltip)

    def _on_stage(self, stage: int) -> None:
        self._stage = GazeStage(stage)
        log.debug("Стадия взгляда: %s", stage_text(self._stage))
        self.refresh_gaze_outputs()

    def refresh_gaze_outputs(self) -> None:
        stage = self._stage
        g = self.cfg.gaze
        self.overlay.set_state(stage >= GazeStage.RED, stage >= GazeStage.BLINK)
        if stage >= GazeStage.SOUND:
            self.sound.start_loop(g.sound, g.sound_repeat_s, g.volume)
        elif self.sound.looping or self._settings is None:
            self.sound.stop()


def send_ipc(command: str) -> bool:
    """Передать команду уже запущенному экземпляру. True — экземпляр найден."""
    sock = QtNetwork.QLocalSocket()
    sock.connectToServer(SERVER_NAME)
    if not sock.waitForConnected(500):
        return False
    sock.write(command.encode())
    sock.flush()
    sock.waitForBytesWritten(500)
    sock.disconnectFromServer()
    return True


def install_translator(qapp, lang: str = "ru") -> None:
    """Подписи стандартных кнопок Qt (OK/Отмена/Применить) на языке интерфейса."""
    old = getattr(qapp, "_qt_translator", None)
    if old is not None:
        qapp.removeTranslator(old)
        qapp._qt_translator = None
    if lang != "ru":
        return
    info = QtCore.QLibraryInfo
    try:
        path = info.path(info.LibraryPath.TranslationsPath)
    except AttributeError:
        path = info.location(info.TranslationsPath)
    translator = QtCore.QTranslator(qapp)
    if translator.load(QtCore.QLocale("ru_RU"), "qtbase", "_", path):
        qapp.installTranslator(translator)
        qapp._qt_translator = translator


def set_language(qapp, setting: str) -> str:
    lang = i18n.set_language(setting)
    install_translator(qapp, lang)
    qapp.setApplicationDisplayName(app_name())
    return lang


def run(allow_download: bool = True, open_settings: bool = False) -> int:
    store = ConfigStore()
    cfg = store.load()
    i18n.set_language(cfg.general.language)
    qapp = QtWidgets.QApplication.instance() or QtWidgets.QApplication([app_name()])
    qapp.setApplicationName(APP_ID)
    qapp.setQuitOnLastWindowClosed(False)
    qapp.setWindowIcon(icons.app_icon())
    if hasattr(qapp, "setDesktopFileName"):
        qapp.setDesktopFileName(autostart.MENU_FILE[:-len(".desktop")])  # связь окон с пунктом меню
    set_language(qapp, cfg.general.language)
    if send_ipc("settings" if open_settings else "ping"):
        log.info("%s уже запущен", app_name())
        return 0
    if not store.path.exists():
        store.save(cfg)
    app = TrayApp(qapp, store, cfg, allow_download)
    app.start()
    if not auth.is_configured(cfg.auth) or open_settings:
        QtCore.QTimer.singleShot(1500, app.open_settings)
    # периодически возвращаем управление интерпретатору, чтобы обрабатывались SIGTERM/SIGINT
    sig_timer = QtCore.QTimer()
    sig_timer.timeout.connect(lambda: None)
    sig_timer.start(1000)
    t0 = time.monotonic()
    try:
        code = exec_(qapp)
    finally:
        app.shutdown()
        log.info("Работа завершена (%.0f с)", time.monotonic() - t0)
    return int(code or 0)
