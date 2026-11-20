#!/usr/bin/env bash
# Установка EyeTracker для текущего пользователя (Radxa OS / Debian / Ubuntu, aarch64 и x86_64).
#
#   ./install.sh               — полная установка (LiteRT для быстрой оценки взгляда по радужке)
#   WITH_LITERT=0 ./install.sh — без LiteRT: модель точек лица выполняется через OpenCV
#                                (чуть больше нагрузка в режиме контроля взгляда)
#
set -euo pipefail

SRC="$(cd "$(dirname "$0")" && pwd)"
APP_HOME="${APP_HOME:-$HOME/.local/share/eyetracker}"
VENV="$APP_HOME/venv"
WITH_LITERT="${WITH_LITERT:-${WITH_MEDIAPIPE:-1}}"

echo "==> Системные пакеты (нужен sudo)"
PKGS="python3 python3-venv python3-pip python3-pyqt5 \
      pulseaudio-utils alsa-utils v4l-utils libxcb-cursor0"
# shellcheck disable=SC2086
sudo apt-get update && sudo apt-get install -y --no-install-recommends $PKGS || {
    echo "!! Не удалось установить часть пакетов — проверьте вывод выше"; }

echo "==> Виртуальное окружение: $VENV"
mkdir -p "$APP_HOME"
# --system-site-packages: используем системный PyQt5 (библиотеки Qt5 уже загружены рабочим столом)
python3 -m venv --system-site-packages "$VENV"
"$VENV/bin/pip" install --upgrade pip wheel
"$VENV/bin/pip" install "opencv-python-headless>=4.8" "numpy>=1.21"

# MediaPipe версии 1.0 больше не нужен — удаляем при обновлении (экономия ~75 МБ памяти)
if "$VENV/bin/pip" show mediapipe >/dev/null 2>&1; then
    echo "==> Удаление MediaPipe (заменён прямым запуском модели точек лица)"
    # вместе с зависимостями, которые были нужны только ему
    "$VENV/bin/pip" uninstall -y mediapipe opencv-contrib-python opencv-python matplotlib contourpy cycler \
        fonttools kiwisolver pyparsing pillow python-dateutil sounddevice cffi pycparser absl-py \
        >/dev/null 2>&1 || true
    "$VENV/bin/pip" install --force-reinstall --no-deps "opencv-python-headless>=4.8"
fi

if [ "$WITH_LITERT" != "0" ]; then
    echo "==> LiteRT (быстрое выполнение модели точек лица для оценки взгляда)"
    "$VENV/bin/pip" install ai-edge-litert || \
        echo "!! LiteRT недоступен для этой платформы — модель будет выполняться через OpenCV"
fi

echo "==> Установка EyeTracker"
"$VENV/bin/pip" install --no-deps --force-reinstall "$SRC"

echo "==> Загрузка моделей"
"$VENV/bin/python" -m eyetracker --download-models

mkdir -p "$HOME/.local/bin"
cat > "$HOME/.local/bin/eyetracker" <<EOS
#!/bin/sh
exec "$VENV/bin/python" -m eyetracker "\$@"
EOS
chmod +x "$HOME/.local/bin/eyetracker"

# пункт меню приложений
mkdir -p "$HOME/.local/share/applications"
cat > "$HOME/.local/share/applications/eyetracker-settings.desktop" <<EOS
[Desktop Entry]
Type=Application
Name=EyeTracker — настройки
Exec=$VENV/bin/python -m eyetracker --settings
Icon=camera-web
Terminal=false
Categories=Utility;Security;
EOS

# доступ к камере
if ! id -nG "$USER" | grep -qw video; then
    sudo usermod -aG video "$USER" && echo "!! Пользователь добавлен в группу video — перезайдите в систему"
fi

echo
"$VENV/bin/python" -m eyetracker --check || true
echo
echo "Готово. Запуск: ~/.local/bin/eyetracker   (автозапуск при входе включается в настройках, по умолчанию — вкл.)"
echo "При первом запуске будет предложено задать логин и пароль администратора."
