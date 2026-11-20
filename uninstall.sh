#!/usr/bin/env bash
# Удаление EyeTracker текущего пользователя.
#   ./uninstall.sh          — удалить программу, сохранив настройки, базу лиц и журнал
#   ./uninstall.sh --purge  — удалить всё, включая настройки, базу лиц, журнал и снимки
set -euo pipefail
APP_HOME="${APP_HOME:-$HOME/.local/share/eyetracker}"

pkill -f "python.* -m eyetracker" 2>/dev/null && echo "Запущенный экземпляр остановлен" || true
rm -f "$HOME/.local/bin/eyetracker" \
      "$HOME/.local/share/applications/eyetracker-settings.desktop" \
      "${XDG_CONFIG_HOME:-$HOME/.config}/autostart/eyetracker.desktop"
rm -rf "$APP_HOME/venv" "$APP_HOME/models" "$APP_HOME/lib"
if [ "${1:-}" = "--purge" ]; then
    rm -rf "$APP_HOME" "${XDG_CONFIG_HOME:-$HOME/.config}/eyetracker"
    echo "Удалено полностью (включая настройки, базу лиц и журнал)."
else
    echo "Программа удалена. Данные сохранены в $APP_HOME и ~/.config/eyetracker"
    echo "(для полного удаления: ./uninstall.sh --purge)"
fi
