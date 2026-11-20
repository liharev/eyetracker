# Модели для NPU RK3588 (формат .rknn)

Сконвертированы скриптом `scripts/convert_rknn.py` (rknn-toolkit2 2.5.0, FP16, без квантования)
и проверены в симуляторе rknn-toolkit2 против эталона на CPU — результаты в `manifest.json`.
Для запуска нужна библиотека `librknnrt.so` той же версии (2.5.0) — её устанавливает `install.sh`.

| Файл | Исходная модель | Лицензия исходной модели |
|------|-----------------|--------------------------|
| `yunet_320x256.rknn`, `yunet_128x128.rknn` | YuNet 2023mar (OpenCV Zoo) | MIT |
| `sface_112.rknn` | SFace 2021dec (OpenCV Zoo) | Apache-2.0 |
| `face_landmarks_256.rknn` | MediaPipe Face Landmarker | Apache-2.0 |

Пересобрать (на ПК с Linux, Python 3.11, нужен TensorFlow ≤ 2.15 для модели TFLite):

```bash
python3.11 -m venv rknn-venv && rknn-venv/bin/pip install rknn-toolkit2 "setuptools<70" "tensorflow-cpu==2.15.1"
rknn-venv/bin/python scripts/convert_rknn.py --models ~/.local/share/eyetracker/models --out models/rknn
```
