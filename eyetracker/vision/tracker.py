"""Простой IoU-трекер лиц с голосованием за личность.

Нужен, чтобы:
* не распознавать каждое лицо в каждом кадре (экономия CPU);
* сглаживать ошибки распознавания (решение по нескольким кадрам);
* не терять человека при кратковременном пропуске детекции.
"""
from __future__ import annotations

from collections import Counter, deque
from dataclasses import dataclass, field
from typing import Deque, List, Optional, Tuple

import numpy as np

PENDING = "pending"
AUTHORIZED = "authorized"
UNKNOWN = "unknown"


@dataclass
class Track:
    id: int
    row: np.ndarray                 # последняя строка детектора (15 значений)
    first_seen: float
    last_seen: float
    hits: int = 1
    votes: Deque[Tuple[Optional[str], float]] = field(default_factory=lambda: deque(maxlen=7))
    names: dict = field(default_factory=dict)
    last_recog_t: float = -1e9
    status: str = PENDING
    person_id: Optional[str] = None
    name: Optional[str] = None
    score: float = 0.0
    recognizable: bool = False      # лицо достаточно крупное для распознавания
    gaze: object = None             # последний GazeSample
    gaze_t: float = -1e9

    @property
    def bbox(self) -> Tuple[int, int, int, int]:
        x, y, w, h = self.row[:4]
        return int(x), int(y), int(w), int(h)

    @property
    def area(self) -> float:
        return float(self.row[2] * self.row[3])

    def add_vote(self, person_id: Optional[str], name: Optional[str], score: float, t: float,
                 min_auth_votes: int = 2, min_unknown_votes: int = 3) -> None:
        self.votes.append((person_id, score))
        if person_id:
            self.names[person_id] = name
        self.last_recog_t = t
        counts = Counter(pid for pid, _ in self.votes)
        unknown_votes = counts.pop(None, 0)
        best_pid, best_cnt = (counts.most_common(1)[0] if counts else (None, 0))
        if best_pid and best_cnt >= min_auth_votes and best_cnt >= unknown_votes:
            self.status = AUTHORIZED
            self.person_id = best_pid
            self.name = self.names.get(best_pid)
            self.score = max(s for pid, s in self.votes if pid == best_pid)
        elif unknown_votes >= min_unknown_votes and unknown_votes > best_cnt:
            self.status = UNKNOWN
            self.person_id = None
            self.name = None
            self.score = max(s for _, s in self.votes)
        elif self.status == AUTHORIZED and best_pid == self.person_id:
            pass  # остаётся авторизованным
        else:
            self.status = PENDING

    def reset_identity(self) -> None:
        self.votes.clear()
        self.status = PENDING
        self.person_id = None
        self.name = None
        self.score = 0.0
        self.last_recog_t = -1e9


def iou(a: np.ndarray, b: np.ndarray) -> float:
    ax, ay, aw, ah = a[:4]
    bx, by, bw, bh = b[:4]
    x1, y1 = max(ax, bx), max(ay, by)
    x2, y2 = min(ax + aw, bx + bw), min(ay + ah, by + bh)
    inter = max(0.0, x2 - x1) * max(0.0, y2 - y1)
    union = aw * ah + bw * bh - inter
    return float(inter / union) if union > 0 else 0.0


class FaceTracker:
    def __init__(self, max_age_s: float = 0.8, iou_threshold: float = 0.25):
        self.max_age_s = max_age_s
        self.iou_threshold = iou_threshold
        self._tracks: List[Track] = []
        self._next_id = 1

    @property
    def tracks(self) -> List[Track]:
        return list(self._tracks)

    def clear(self) -> None:
        self._tracks.clear()

    def reset_identities(self) -> None:
        for tr in self._tracks:
            tr.reset_identity()

    def update(self, detections: np.ndarray, t: float) -> List[Track]:
        """Сопоставляет детекции с треками; возвращает активные треки."""
        pairs = []
        for ti, tr in enumerate(self._tracks):
            for di in range(detections.shape[0]):
                score = iou(tr.row, detections[di])
                if score >= self.iou_threshold:
                    pairs.append((score, ti, di))
        pairs.sort(reverse=True)
        used_t, used_d = set(), set()
        for _, ti, di in pairs:
            if ti in used_t or di in used_d:
                continue
            used_t.add(ti)
            used_d.add(di)
            tr = self._tracks[ti]
            tr.row = detections[di].copy()
            tr.last_seen = t
            tr.hits += 1
        for di in range(detections.shape[0]):
            if di not in used_d:
                self._tracks.append(Track(self._next_id, detections[di].copy(), t, t))
                self._next_id += 1
        self._tracks = [tr for tr in self._tracks if t - tr.last_seen <= self.max_age_s]
        return list(self._tracks)

    @staticmethod
    def visible(tracks: List[Track], t: float) -> List[Track]:
        return [tr for tr in tracks if tr.last_seen == t]
