"""Декодирование «сырых» выходов модели YuNet (как в cv2.FaceDetectorYN).

Нужно для запуска YuNet на NPU: там модель отдаёт 12 тензоров
(cls/obj/bbox/kps для шагов 8, 16, 32), а рамки и точки лица собираются здесь.
"""
from __future__ import annotations

from typing import Dict, Sequence

import cv2
import numpy as np

STRIDES = (8, 16, 32)
OUTPUT_NAMES = [f"{k}_{s}" for k in ("cls", "obj", "bbox", "kps") for s in STRIDES]


def decode(outputs: Dict[str, np.ndarray], width: int, height: int, score_threshold: float = 0.75,
           nms_threshold: float = 0.3, top_k: int = 5000) -> np.ndarray:
    """outputs: имя → массив; width/height — размер входа модели. Возвращает N×15 (как YuNet)."""
    boxes, scores, kps_all = [], [], []
    for s in STRIDES:
        cols, rows = width // s, height // s
        n = cols * rows
        cls = np.clip(outputs[f"cls_{s}"].reshape(n), 0, 1)
        obj = np.clip(outputs[f"obj_{s}"].reshape(n), 0, 1)
        score = np.sqrt(cls * obj)
        keep = score >= score_threshold
        if not keep.any():
            continue
        idx = np.nonzero(keep)[0]
        c = (idx % cols).astype(np.float32)
        r = (idx // cols).astype(np.float32)
        bb = outputs[f"bbox_{s}"].reshape(n, 4)[idx]
        kp = outputs[f"kps_{s}"].reshape(n, 10)[idx]
        cx = (c + bb[:, 0]) * s
        cy = (r + bb[:, 1]) * s
        w = np.exp(bb[:, 2]) * s
        h = np.exp(bb[:, 3]) * s
        boxes.append(np.stack([cx - w / 2, cy - h / 2, w, h], 1))
        k = np.empty_like(kp)
        k[:, 0::2] = (kp[:, 0::2] + c[:, None]) * s
        k[:, 1::2] = (kp[:, 1::2] + r[:, None]) * s
        kps_all.append(k)
        scores.append(score[idx])
    if not boxes:
        return np.zeros((0, 15), np.float32)
    boxes_a = np.concatenate(boxes).astype(np.float32)
    scores_a = np.concatenate(scores).astype(np.float32)
    kps_a = np.concatenate(kps_all).astype(np.float32)
    keep = cv2.dnn.NMSBoxes(boxes_a.tolist(), scores_a.tolist(), score_threshold, nms_threshold, top_k=top_k)
    keep = np.asarray(keep, dtype=np.int64).reshape(-1)
    if keep.size == 0:
        return np.zeros((0, 15), np.float32)
    return np.concatenate([boxes_a[keep], kps_a[keep], scores_a[keep, None]], 1).astype(np.float32)


def letterbox(frame: np.ndarray, width: int, height: int) -> tuple:
    """Вписывает кадр в width×height с сохранением пропорций (поля — снизу/справа).
    Возвращает (изображение, масштаб «вход модели → кадр»)."""
    h, w = frame.shape[:2]
    k = min(width / w, height / h)
    nw, nh = max(1, int(round(w * k))), max(1, int(round(h * k)))
    small = cv2.resize(frame, (nw, nh), interpolation=cv2.INTER_AREA if k < 1 else cv2.INTER_LINEAR)
    if (nw, nh) != (width, height):
        small = cv2.copyMakeBorder(small, 0, height - nh, 0, width - nw, cv2.BORDER_CONSTANT, value=0)
    return small, 1.0 / k


def order_outputs(names: Sequence[str], arrays: Sequence[np.ndarray]) -> Dict[str, np.ndarray]:
    return dict(zip(names, arrays))
