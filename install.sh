#!/usr/bin/env bash
# Установка CAMAI бдительность (CAMAI vigilance) для текущего пользователя (Radxa OS / Debian / Ubuntu, aarch64 и x86_64).
#
#   ./install.sh               — полная установка (LiteRT для быстрой оценки взгляда по радужке)
#   WITH_LITERT=0 ./install.sh — без LiteRT: модель точек лица выполняется через OpenCV
#                                (чуть больше нагрузка в режиме контроля взгляда)
#   WITH_NPU=0 ./install.sh    — не устанавливать поддержку NPU RK3588 (librknnrt.so и модели .rknn)
#
set -euo pipefail

SRC="$(cd "$(dirname "$0")" && pwd)"
APP_HOME="${APP_HOME:-$HOME/.local/share/eyetracker}"
VENV="$APP_HOME/venv"
WITH_LITERT="${WITH_LITERT:-${WITH_MEDIAPIPE:-1}}"
WITH_NPU="${WITH_NPU:-1}"
RKNNRT_VERSION="2.5.0"
RKNNRT_URL="https://raw.githubusercontent.com/airockchip/rknn-toolkit2/v${RKNNRT_VERSION}/rknpu2/runtime/Linux/librknn_api/aarch64/librknnrt.so"
RKNNRT_SHA256="4b6cc575bedf8952b13db4b1190fa3b3d2ac213f00be774ff6ccd19d651970c0"
RELOGIN=0

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

echo "==> Установка программы"
"$VENV/bin/pip" install --no-deps --force-reinstall "$SRC"

if [ "$WITH_NPU" != "0" ] && [ "$(uname -m)" = "aarch64" ]; then
    echo "==> NPU RK3588: библиотека librknnrt.so $RKNNRT_VERSION и модели .rknn"
    mkdir -p "$APP_HOME/lib" "$APP_HOME/models/rknn"
    "$VENV/bin/python" - "$RKNNRT_URL" "$RKNNRT_SHA256" "$APP_HOME/lib/librknnrt.so" <<'PYEOF' || \
        echo "!! Не удалось загрузить librknnrt.so — программа будет работать на CPU"
import hashlib, os, sys, urllib.request
url, sha, dst = sys.argv[1:4]
def ok(p):
    return os.path.exists(p) and hashlib.sha256(open(p, "rb").read()).hexdigest() == sha
if not ok(dst):
    tmp = dst + ".part"
    with urllib.request.urlopen(url, timeout=120) as r, open(tmp, "wb") as f:
        f.write(r.read())
    if not ok(tmp):
        os.remove(tmp)
        sys.exit("контрольная сумма librknnrt.so не совпадает")
    os.replace(tmp, dst)
print("librknnrt.so:", dst)
PYEOF
    cp "$SRC"/models/rknn/*.rknn "$SRC"/models/rknn/manifest.json "$APP_HOME/models/rknn/"
    # доступ к устройству NPU (/dev/dri/renderD*) обычно есть у группы render
    for grp in render video; do
        if getent group "$grp" >/dev/null && ! id -nG "$USER" | grep -qw "$grp"; then
            sudo usermod -aG "$grp" "$USER" && RELOGIN=1
        fi
    done
fi

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
# значки программы для меню и автозапуска
"$VENV/bin/python" -m eyetracker --install-icons >/dev/null || echo "!! Не удалось установить значки"
cat > "$HOME/.local/share/applications/eyetracker-settings.desktop" <<EOS
[Desktop Entry]
Type=Application
Name=CAMAI vigilance — settings
Name[ru]=CAMAI бдительность — настройки
Exec=$VENV/bin/python -m eyetracker --settings
Icon=camai-vigilance
Terminal=false
Categories=Utility;Security;
EOS

# доступ к камере
if ! id -nG "$USER" | grep -qw video; then
    sudo usermod -aG video "$USER" && RELOGIN=1
fi
if [ "$RELOGIN" = "1" ]; then
    echo "!! Пользователь добавлен в группы video/render (камера, NPU) — выйдите из системы и войдите снова"
fi

echo
"$VENV/bin/python" -m eyetracker --check || true
echo
echo "Готово. Запуск: ~/.local/bin/eyetracker   (автозапуск при входе включается в настройках, по умолчанию — вкл.)"
echo "При первом запуске будет предложено задать логин и пароль администратора."
