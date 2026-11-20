"""Диалоги входа и задания учётных данных администратора."""
from __future__ import annotations

from typing import Optional

from .. import auth
from ..config import AuthConfig
from ..i18n import app_name, tr
from ..qt import Qt, QtWidgets, exec_


class LoginDialog(QtWidgets.QDialog):
    def __init__(self, auth_cfg: AuthConfig, guard: auth.LoginGuard, purpose: str = "", parent=None):
        super().__init__(parent)
        self.auth_cfg = auth_cfg
        self.guard = guard
        self.failed_user: Optional[str] = None
        self.setWindowTitle(tr("{app} — вход", app=app_name()))
        self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)
        lay = QtWidgets.QFormLayout(self)
        if purpose:
            info = QtWidgets.QLabel(purpose)
            info.setWordWrap(True)
            lay.addRow(info)
        self.user = QtWidgets.QLineEdit(auth_cfg.username)
        self.password = QtWidgets.QLineEdit()
        self.password.setEchoMode(QtWidgets.QLineEdit.EchoMode.Password)
        lay.addRow(tr("Логин:"), self.user)
        lay.addRow(tr("Пароль:"), self.password)
        self.error = QtWidgets.QLabel()
        self.error.setStyleSheet("color: #c00;")
        self.error.setWordWrap(True)
        lay.addRow(self.error)
        buttons = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.StandardButton.Ok
                                             | QtWidgets.QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self._try)
        buttons.rejected.connect(self.reject)
        lay.addRow(buttons)
        (self.password if auth_cfg.username else self.user).setFocus()
        self.failures = 0

    def _try(self) -> None:
        ok, msg = self.guard.attempt(self.auth_cfg, self.user.text(), self.password.text())
        if ok:
            self.accept()
            return
        self.failures += 1
        self.failed_user = self.user.text()
        self.error.setText(msg)
        self.password.clear()
        self.password.setFocus()


class SetCredentialsDialog(QtWidgets.QDialog):
    """Первичная настройка или смена логина/пароля."""

    def __init__(self, auth_cfg: AuthConfig, first_time: bool, parent=None):
        super().__init__(parent)
        self.auth_cfg = auth_cfg
        self.setWindowTitle(tr("{app} — учётная запись администратора", app=app_name()))
        self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)
        lay = QtWidgets.QFormLayout(self)
        if first_time:
            info = QtWidgets.QLabel(tr("Первый запуск: задайте логин и пароль для входа в настройки. "
                                       "Без них изменить настройки и закрыть программу будет нельзя."))
            info.setWordWrap(True)
            lay.addRow(info)
        self.user = QtWidgets.QLineEdit(auth_cfg.username or "admin")
        self.p1 = QtWidgets.QLineEdit()
        self.p2 = QtWidgets.QLineEdit()
        for p in (self.p1, self.p2):
            p.setEchoMode(QtWidgets.QLineEdit.EchoMode.Password)
        lay.addRow(tr("Логин:"), self.user)
        lay.addRow(tr("Новый пароль:"), self.p1)
        lay.addRow(tr("Повтор пароля:"), self.p2)
        self.error = QtWidgets.QLabel()
        self.error.setStyleSheet("color: #c00;")
        lay.addRow(self.error)
        buttons = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.StandardButton.Ok
                                             | QtWidgets.QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self._ok)
        buttons.rejected.connect(self.reject)
        lay.addRow(buttons)

    def _ok(self) -> None:
        if self.p1.text() != self.p2.text():
            self.error.setText(tr("Пароли не совпадают"))
            return
        try:
            auth.set_credentials(self.auth_cfg, self.user.text(), self.p1.text())
        except ValueError as exc:
            self.error.setText(str(exc))
            return
        self.accept()


def run_dialog(dlg: QtWidgets.QDialog) -> bool:
    dlg.raise_()
    dlg.activateWindow()
    return int(exec_(dlg)) == 1
