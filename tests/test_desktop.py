"""Пункт меню, значки и автозапуск обновляются после обновления программы."""
import pytest

from eyetracker import autostart


@pytest.fixture
def xdg(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "share"))
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    calls = []
    monkeypatch.setattr(autostart, "refresh_caches", lambda icons_changed, wait=False: calls.append(icons_changed))
    return tmp_path, calls


def test_outdated_menu_entry_is_replaced(xdg):
    from eyetracker.qt import QtWidgets
    QtWidgets.QApplication.instance() or QtWidgets.QApplication(["t", "-platform", "offscreen"])
    tmp, calls = xdg
    old = tmp / "share" / "applications" / autostart.MENU_FILE
    old.parent.mkdir(parents=True)
    old.write_text("[Desktop Entry]\nName=EyeTracker — настройки\nIcon=camera-web\n", encoding="utf-8")

    assert autostart.ensure_desktop_integration(autostart=True)
    text = old.read_text(encoding="utf-8")
    assert "Name=CAMAI vigilance — settings" in text and "Name[ru]=CAMAI бдительность — настройки" in text
    assert f"Icon={autostart.icon_path()}" in text and autostart.icon_path().exists()
    assert "EyeTracker" not in text
    assert calls == [True]
    # второй запуск — всё актуально, кэши не трогаем
    assert not autostart.ensure_desktop_integration(autostart=True)
    assert calls == [True]
    auto = tmp / "config" / "autostart" / "eyetracker.desktop"
    assert "Name[ru]=CAMAI бдительность" in auto.read_text(encoding="utf-8")
    autostart.set_enabled(False)
    assert not auto.exists()
