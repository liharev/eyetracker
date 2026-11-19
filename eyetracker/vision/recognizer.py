"""Распознавание лиц (OpenCV SFace) и локальная база авторизованных лиц."""
from __future__ import annotations

import json
import logging
import re
import shutil
import threading
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import cv2
import numpy as np

log = logging.getLogger(__name__)


class FaceEmbedder:
    def __init__(self, model_path: Path):
        self._net = cv2.FaceRecognizerSF.create(str(model_path), "")

    def align(self, frame: np.ndarray, face_row: np.ndarray) -> np.ndarray:
        return self._net.alignCrop(frame, face_row)

    def embed(self, frame: np.ndarray, face_row: np.ndarray) -> np.ndarray:
        aligned = self.align(frame, face_row)
        feat = self._net.feature(aligned).reshape(-1).astype(np.float32)
        norm = float(np.linalg.norm(feat))
        return feat / norm if norm > 0 else feat


@dataclass
class Person:
    id: str
    name: str
    created: float
    embeddings: np.ndarray = field(default_factory=lambda: np.zeros((0, 128), np.float32))

    @property
    def samples(self) -> int:
        return int(self.embeddings.shape[0])


@dataclass
class Match:
    person_id: Optional[str]
    name: Optional[str]
    score: float


class FaceDatabase:
    """Хранилище: faces/index.json + faces/<id>/embeddings.npy + faces/<id>/photo.jpg"""

    def __init__(self, root: Path):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._persons: Dict[str, Person] = {}
        self._matrix = np.zeros((0, 128), np.float32)
        self._owners: List[str] = []
        self.version = 0
        self.load()

    # ---------------------------------------------------------------- I/O
    @property
    def index_path(self) -> Path:
        return self.root / "index.json"

    def load(self) -> None:
        with self._lock:
            self._persons.clear()
            if self.index_path.exists():
                try:
                    items = json.loads(self.index_path.read_text(encoding="utf-8"))
                except (OSError, ValueError) as exc:
                    log.error("База лиц повреждена: %s", exc)
                    items = []
                for item in items:
                    pid = str(item.get("id"))
                    if not re.fullmatch(r"[0-9a-f]{32}", pid):
                        continue
                    emb_path = self.root / pid / "embeddings.npy"
                    emb = np.load(emb_path) if emb_path.exists() else np.zeros((0, 128), np.float32)
                    self._persons[pid] = Person(pid, item.get("name", "?"), float(item.get("created", 0)),
                                                emb.astype(np.float32))
            self._rebuild()

    def _save_index(self) -> None:
        items = [{"id": p.id, "name": p.name, "created": p.created} for p in self._persons.values()]
        tmp = self.index_path.with_suffix(".tmp")
        tmp.write_text(json.dumps(items, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(self.index_path)

    def _rebuild(self) -> None:
        mats, owners = [], []
        for p in self._persons.values():
            if p.samples:
                mats.append(p.embeddings)
                owners.extend([p.id] * p.samples)
        self._matrix = np.vstack(mats).astype(np.float32) if mats else np.zeros((0, 128), np.float32)
        self._owners = owners
        self.version += 1

    # ---------------------------------------------------------- operations
    def persons(self) -> List[Person]:
        with self._lock:
            return sorted(self._persons.values(), key=lambda p: p.name.lower())

    def get(self, pid: str) -> Optional[Person]:
        with self._lock:
            return self._persons.get(pid)

    def add_person(self, name: str, embeddings: np.ndarray, photo: Optional[np.ndarray] = None) -> Person:
        name = name.strip()
        if not name:
            raise ValueError("Имя не может быть пустым")
        if embeddings.ndim != 2 or embeddings.shape[0] == 0:
            raise ValueError("Нет образцов лица")
        with self._lock:
            pid = uuid.uuid4().hex
            person = Person(pid, name, time.time(), embeddings.astype(np.float32))
            pdir = self.root / pid
            pdir.mkdir(parents=True, exist_ok=True)
            np.save(pdir / "embeddings.npy", person.embeddings)
            if photo is not None:
                cv2.imwrite(str(pdir / "photo.jpg"), photo)
            self._persons[pid] = person
            self._save_index()
            self._rebuild()
            return person

    def add_samples(self, pid: str, embeddings: np.ndarray) -> None:
        with self._lock:
            person = self._persons[pid]
            person.embeddings = np.vstack([person.embeddings, embeddings.astype(np.float32)])
            np.save(self.root / pid / "embeddings.npy", person.embeddings)
            self._rebuild()

    def rename(self, pid: str, name: str) -> None:
        with self._lock:
            if not name.strip():
                raise ValueError("Имя не может быть пустым")
            self._persons[pid].name = name.strip()
            self._save_index()
            self.version += 1

    def remove(self, pid: str) -> None:
        with self._lock:
            if pid in self._persons:
                del self._persons[pid]
                shutil.rmtree(self.root / pid, ignore_errors=True)
                self._save_index()
                self._rebuild()

    def photo_path(self, pid: str) -> Path:
        return self.root / pid / "photo.jpg"

    def match(self, embedding: np.ndarray, threshold: float) -> Match:
        with self._lock:
            if self._matrix.shape[0] == 0:
                return Match(None, None, 0.0)
            sims = self._matrix @ embedding.astype(np.float32)
            best_score: Dict[str, float] = {}
            for owner, sim in zip(self._owners, sims):
                if sim > best_score.get(owner, -1.0):
                    best_score[owner] = float(sim)
            pid, score = max(best_score.items(), key=lambda kv: kv[1])
            if score >= threshold:
                return Match(pid, self._persons[pid].name, score)
            return Match(None, None, score)

    def __len__(self) -> int:
        with self._lock:
            return len(self._persons)


def embedding_consistency(embeddings: np.ndarray) -> Tuple[float, float]:
    """Минимальная и средняя попарная близость образцов (для контроля качества)."""
    if embeddings.shape[0] < 2:
        return 1.0, 1.0
    sims = embeddings @ embeddings.T
    iu = np.triu_indices(embeddings.shape[0], 1)
    vals = sims[iu]
    return float(vals.min()), float(vals.mean())
