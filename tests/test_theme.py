"""Выбор белых/чёрных значков по теме оформления."""
import pytest

from eyetracker import autostart, theme


@pytest.fixture
def kde(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "share"))
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))
    monkeypatch.setenv("XDG_CURRENT_DESKTOP", "KDE")
    monkeypatch.setattr(theme.shutil, "which", lambda name: None)   # без gsettings
    cfg = tmp_path / "config"
    cfg.mkdir()
    return cfg


def write(path, text):
    path.write_text(text, encoding="utf-8")


def test_kde_color_scheme(kde):
    write(kde / "kdeglobals", "[General]\nColorScheme=BreezeDark\n\n[Colors:Window]\nBackgroundNormal=32,35,38\n")
    assert theme.desktop_is_light() is False
    write(kde / "kdeglobals", "[Colors:Window]\nBackgroundNormal=239,240,241\n")
    assert theme.desktop_is_light() is True


def test_plasma_style_has_priority(kde):
    # Breeze Twilight: светлые окна, но тёмная панель — значки в меню и трее должны быть белыми
    write(kde / "kdeglobals", "[Colors:Window]\nBackgroundNormal=239,240,241\n")
    write(kde / "plasmarc", "[Theme]\nname=breeze-dark\n")
    assert theme.desktop_is_light() is False
    write(kde / "plasmarc", "[Theme]\nname=breeze-light\n")
    assert theme.desktop_is_light() is True


def test_kde_default_is_light(kde):
    assert theme.desktop_is_light() is True


def test_manual_override(kde):
    write(kde / "kdeglobals", "[Colors:Window]\nBackgroundNormal=239,240,241\n")
    assert theme.use_black_icons("auto") is True
    assert theme.use_black_icons("light") is False
    assert theme.use_black_icons("dark") is True


def test_unknown_desktop_uses_palette(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    monkeypatch.setenv("XDG_CURRENT_DESKTOP", "")
    monkeypatch.setenv("DESKTOP_SESSION", "")
    monkeypatch.setattr(theme.shutil, "which", lambda name: None)
    assert theme.desktop_is_light() is None
    assert theme.use_black_icons("auto", palette_is_light=True) is True
    assert theme.use_black_icons("auto") is False      # не определить — исходный белый вариант


def test_menu_icon_follows_theme(kde, monkeypatch):
    from eyetracker.qt import QtWidgets
    QtWidgets.QApplication.instance() or QtWidgets.QApplication(["t", "-platform", "offscreen"])
    calls = []
    monkeypatch.setattr(autostart, "refresh_caches", lambda icons_changed, wait=False: calls.append(1))
    write(kde / "kdeglobals", "[Colors:Window]\nBackgroundNormal=32,35,38\n")
    autostart.ensure_desktop_integration(True, theme.use_black_icons("auto"))
    menu = autostart.menu_file().read_text(encoding="utf-8")
    assert f"Icon={autostart.icon_path(False)}" in menu
    # пользователь переключил тему на светлую
    write(kde / "kdeglobals", "[Colors:Window]\nBackgroundNormal=239,240,241\n")
    assert autostart.ensure_desktop_integration(True, theme.use_black_icons("auto"))
    menu = autostart.menu_file().read_text(encoding="utf-8")
    assert f"Icon={autostart.icon_path(True)}" in menu and autostart.icon_path(True).exists()
    assert "#000000" in autostart.icon_path(True).read_text(encoding="utf-8")
    assert len(calls) == 2
