#!/bin/sh
# Загрузка тестовых изображений для tests/test_engine_integration.py (в git не хранятся).
set -e
DIR="$(dirname "$0")/../tests/data"
mkdir -p "$DIR"
curl -fsSL -o "$DIR/lena.jpg"  https://raw.githubusercontent.com/opencv/opencv/4.x/samples/data/lena.jpg
curl -fsSL -o "$DIR/face2.jpg" https://storage.googleapis.com/mediapipe-assets/portrait.jpg
echo "Готово: $DIR"
