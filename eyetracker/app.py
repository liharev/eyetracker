"""Фоновое приложение: значок в трее, рамка, звук, связь движка с интерфейсом."""
from __future__ import annotations

import getpass
import logging
import time
from typing import Optional

from . import APP_ID, APP_NAME, auth, autostart, paths
from . import sound as sound_mod
from .config import Config, ConfigStore
from .engine import Engine, EngineStatus
from .events import Event, EventDispatcher, EventStore
from .mailer import DigestScheduler, Mailer
from .overlay import BorderOverlay
from .policy import GAZE_STAGE_TEXT, GazeStage
from .qt import QT_API, QtCore, QtNetwork, QtWidgets, Signal, exec_
from .ui.login import LoginDialog, SetCredentialsDialog, run_dialog
from .ui.widgets import make_icon
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

        self._icons = {
            "ok": make_icon("#2e9d3a"), "idle": make_icon("#8a8a8a"), "warn": make_icon("#e0a000"),
            "alert": make_icon("#d42020", ring="#d42020"), "paused": make_icon("#3070d0"),
            "error": make_icon("#d42020"),
        }
        self.tray = QtWidgets.QSystemTrayIcon(self._icons["idle"], self)
        self.tray.setToolTip(APP_NAME)
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
        try:
            autostart.set_enabled(self.cfg.general.autostart)
        except OSError as exc:
            log.warning("Автозапуск: %s", exc)
        self.engine.start()
        self.scheduler.start()
        self._daily()
        self.publish_system("app_started", f"{APP_NAME} запущен (Qt: {QT_API})")

    def shutdown(self) -> None:
        self.publish_system("app_stopped", f"{APP_NAME} остановлен")
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
        self.publish_system("settings_changed", "Настройки изменены администратором")
        self.refresh_gaze_outputs()

    def publish_system(self, etype: str, message: str, details: Optional[dict] = None) -> None:
        self.dispatcher.publish(Event("system", etype, message, details or {}))

    # ----------------------------------------------------------------- tray
    def _build_menu(self) -> None:
        menu = QtWidgets.QMenu()
        self._status_action = menu.addAction("Запуск…")
        self._status_action.setEnabled(False)
        menu.addSeparator()
        menu.addAction("Настройки…", self.open_settings)
        pause_menu = menu.addMenu("Приостановить контроль")
        for minutes in (5, 15, 30, 60):
            pause_menu.addAction(f"на {minutes} мин", lambda m=minutes: self._pause(m))
        self._resume_action = menu.addAction("Возобновить контроль", self._resume)
        self._resume_action.setVisible(False)
        menu.addSeparator()
        menu.addAction("Выход", self._quit)
        self._menu = menu
        self.tray.setContextMenu(menu)

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
                self.publish_system("credentials_created", "Заданы учётные данные администратора")
                return True
            dlg = LoginDialog(self.cfg.auth, self.guard, purpose)
            ok = run_dialog(dlg)
            if dlg.failures:
                self.publish_system("login_failed",
                                    f"Неудачные попытки входа ({purpose or 'настройки'}): {dlg.failures}",
                                    {"username": dlg.failed_user})
            if ok:
                self.publish_system("login_ok", f"Вход администратора: {purpose or 'настройки'}")
            return ok
        finally:
            self._busy_dialog = False

    def open_settings(self) -> None:
        if self._settings is not None:
            self._settings.show()
            self._settings.raise_()
            self._settings.activateWindow()
            return
        if not self._authorize("Вход в настройки"):
            return
        from .ui.settings import SettingsDialog

        self._settings = SettingsDialog(self)
        self._settings.finished.connect(self._settings_closed)
        self._settings.show()
        self._settings.raise_()
        self._settings.activateWindow()

    def _settings_closed(self, *_):
        self._settings.deleteLater()
        self._settings = None

    def _pause(self, minutes: int) -> None:
        if self._authorize(f"Приостановка контроля на {minutes} мин"):
            self.engine.pause(minutes * 60)
            self.publish_system("paused", f"Контроль приостановлен на {minutes} мин")

    def _resume(self) -> None:
        self.engine.resume()
        self.publish_system("resumed", "Контроль возобновлён")

    def _quit(self) -> None:
        if self._authorize("Выход из программы"):
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
            return f"Ошибка: {st.message}"
        if st.state == "camera_error":
            return f"Камера: {st.message}"
        if st.state == "starting":
            return "Запуск…"
        parts = []
        if st.state == "paused":
            parts.append(f"Пауза ({int(st.paused_until // 60) + 1} мин)")
        if st.faces == 0:
            parts.append("перед экраном никого нет")
        else:
            parts.append(f"лиц: {st.faces}")
            if st.authorized:
                parts.append("авторизованы: " + ", ".join(st.authorized))
            if st.unknown:
                parts.append(f"посторонних: {st.unknown}")
        if self.cfg.gaze.enabled and st.authorized:
            parts.append("взгляд: " + ("на экране" if st.on_screen else "не на экране"))
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
        tooltip = f"{APP_NAME}: {text}"
        if key != self._last_icon_key:
            self.tray.setIcon(self._icons[key])
            self._last_icon_key = key
        if self.tray.toolTip() != tooltip:
            self.tray.setToolTip(tooltip)

    def _on_stage(self, stage: int) -> None:
        self._stage = GazeStage(stage)
        log.debug("Стадия взгляда: %s", GAZE_STAGE_TEXT[self._stage])
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


def install_translator(qapp) -> None:
    """Русские подписи стандартных кнопок Qt (OK/Отмена/Применить)."""
    info = QtCore.QLibraryInfo
    try:
        path = info.path(info.LibraryPath.TranslationsPath)
    except AttributeError:
        path = info.location(info.TranslationsPath)
    tr = QtCore.QTranslator(qapp)
    if tr.load(QtCore.QLocale("ru_RU"), "qtbase", "_", path):
        qapp.installTranslator(tr)
        qapp._ru_translator = tr


def run(allow_download: bool = True, open_settings: bool = False) -> int:
    qapp = QtWidgets.QApplication.instance() or QtWidgets.QApplication([APP_NAME])
    qapp.setApplicationName(APP_NAME)
    qapp.setQuitOnLastWindowClosed(False)
    install_translator(qapp)
    if send_ipc("settings" if open_settings else "ping"):
        log.info("%s уже запущен", APP_NAME)
        return 0
    store = ConfigStore()
    cfg = store.load()
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
