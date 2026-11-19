"""Журнал событий (SQLite) и маршрутизация событий: e-mail сразу / журнал / отчёт по расписанию."""
from __future__ import annotations

import csv
import io
import json
import logging
import sqlite3
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Callable, Dict, List, Optional

from .config import EVENT_CATEGORIES, Config

log = logging.getLogger(__name__)


@dataclass
class Event:
    category: str
    type: str
    message: str
    details: Dict = field(default_factory=dict)
    ts: float = field(default_factory=time.time)
    snapshot_jpeg: Optional[bytes] = None
    id: Optional[int] = None
    snapshot_path: Optional[str] = None

    @property
    def time_str(self) -> str:
        return datetime.fromtimestamp(self.ts).strftime("%Y-%m-%d %H:%M:%S")

    @property
    def category_title(self) -> str:
        return EVENT_CATEGORIES.get(self.category, self.category)


class EventStore:
    def __init__(self, db_path: Path, snapshots_dir: Optional[Path] = None):
        self.db_path = Path(db_path)
        self.snapshots_dir = Path(snapshots_dir) if snapshots_dir else None
        self._lock = threading.Lock()
        self._db = sqlite3.connect(str(self.db_path), check_same_thread=False)
        self._db.execute(
            """CREATE TABLE IF NOT EXISTS events (
                   id INTEGER PRIMARY KEY AUTOINCREMENT,
                   ts REAL NOT NULL,
                   category TEXT NOT NULL,
                   type TEXT NOT NULL,
                   message TEXT NOT NULL,
                   details TEXT,
                   snapshot TEXT,
                   digest_pending INTEGER NOT NULL DEFAULT 0
               )""")
        self._db.execute("CREATE INDEX IF NOT EXISTS idx_events_ts ON events(ts)")
        self._db.execute("CREATE INDEX IF NOT EXISTS idx_events_digest ON events(digest_pending)")
        self._db.commit()

    def close(self) -> None:
        with self._lock:
            self._db.close()

    def add(self, ev: Event, digest: bool) -> int:
        snap = None
        if ev.snapshot_jpeg and self.snapshots_dir:
            self.snapshots_dir.mkdir(parents=True, exist_ok=True)
            name = datetime.fromtimestamp(ev.ts).strftime("%Y%m%d-%H%M%S") + f"-{ev.category}-{int(ev.ts * 1000) % 1000:03d}.jpg"
            path = self.snapshots_dir / name
            path.write_bytes(ev.snapshot_jpeg)
            snap = str(path)
            ev.snapshot_path = snap
        with self._lock:
            cur = self._db.execute(
                "INSERT INTO events(ts, category, type, message, details, snapshot, digest_pending) VALUES (?,?,?,?,?,?,?)",
                (ev.ts, ev.category, ev.type, ev.message, json.dumps(ev.details, ensure_ascii=False), snap,
                 1 if digest else 0))
            self._db.commit()
            ev.id = cur.lastrowid
            return ev.id

    def _rows_to_events(self, rows) -> List[Event]:
        out = []
        for r in rows:
            try:
                details = json.loads(r[5]) if r[5] else {}
            except ValueError:
                details = {}
            out.append(Event(id=r[0], ts=r[1], category=r[2], type=r[3], message=r[4], details=details,
                             snapshot_path=r[6]))
        return out

    def query(self, limit: int = 1000, category: Optional[str] = None, since: Optional[float] = None) -> List[Event]:
        sql = "SELECT id, ts, category, type, message, details, snapshot FROM events"
        cond, args = [], []
        if category:
            cond.append("category = ?")
            args.append(category)
        if since is not None:
            cond.append("ts >= ?")
            args.append(since)
        if cond:
            sql += " WHERE " + " AND ".join(cond)
        sql += " ORDER BY ts DESC, id DESC LIMIT ?"
        args.append(limit)
        with self._lock:
            rows = self._db.execute(sql, args).fetchall()
        return self._rows_to_events(rows)

    def pending_digest(self) -> List[Event]:
        with self._lock:
            rows = self._db.execute(
                "SELECT id, ts, category, type, message, details, snapshot FROM events "
                "WHERE digest_pending = 1 ORDER BY ts, id").fetchall()
        return self._rows_to_events(rows)

    def mark_digested(self, ids: List[int]) -> None:
        if not ids:
            return
        with self._lock:
            self._db.executemany("UPDATE events SET digest_pending = 0 WHERE id = ?", [(i,) for i in ids])
            self._db.commit()

    def purge(self, older_than_days: int) -> int:
        if older_than_days <= 0:
            return 0
        border = time.time() - older_than_days * 86400
        with self._lock:
            snaps = [r[0] for r in self._db.execute(
                "SELECT snapshot FROM events WHERE ts < ? AND snapshot IS NOT NULL AND digest_pending = 0",
                (border,))]
            cur = self._db.execute("DELETE FROM events WHERE ts < ? AND digest_pending = 0", (border,))
            self._db.commit()
        for s in snaps:
            try:
                Path(s).unlink()
            except OSError:
                pass
        return cur.rowcount

    def clear(self) -> None:
        with self._lock:
            snaps = [r[0] for r in self._db.execute("SELECT snapshot FROM events WHERE snapshot IS NOT NULL")]
            self._db.execute("DELETE FROM events")
            self._db.commit()
        for s in snaps:
            try:
                Path(s).unlink()
            except OSError:
                pass


def events_to_csv(events: List[Event]) -> str:
    buf = io.StringIO()
    w = csv.writer(buf, delimiter=";")
    w.writerow(["id", "время", "категория", "тип", "сообщение", "подробности", "снимок"])
    for e in events:
        w.writerow([e.id or "", e.time_str, e.category_title, e.type, e.message,
                    json.dumps(e.details, ensure_ascii=False), e.snapshot_path or ""])
    return buf.getvalue()


class EventDispatcher:
    """Принимает события от движка и направляет их согласно настройкам."""

    def __init__(self, cfg: Config, store: EventStore, mailer=None):
        self.cfg = cfg
        self.store = store
        self.mailer = mailer
        self._listeners: List[Callable[[Event], None]] = []

    def set_config(self, cfg: Config) -> None:
        self.cfg = cfg

    def add_listener(self, fn: Callable[[Event], None]) -> None:
        self._listeners.append(fn)

    def wants_snapshot(self, category: str) -> bool:
        route = self.cfg.notify.routes.get(category)
        if route is None:
            return False
        return (route.email and self.cfg.email.attach_snapshot) or \
               ((route.log or route.digest) and self.cfg.notify.save_snapshots)

    def publish(self, ev: Event) -> None:
        route = self.cfg.notify.routes.get(ev.category)
        log.info("[%s] %s", ev.category, ev.message)
        if route is not None:
            if route.log or route.digest:
                try:
                    snapshot_backup = ev.snapshot_jpeg
                    if not self.cfg.notify.save_snapshots:
                        ev.snapshot_jpeg = None
                    self.store.add(ev, digest=route.digest)
                    ev.snapshot_jpeg = snapshot_backup
                except sqlite3.Error as exc:
                    log.error("Не удалось записать событие в журнал: %s", exc)
            if route.email and self.mailer is not None:
                attach = ev.snapshot_jpeg if self.cfg.email.attach_snapshot else None
                self.mailer.send_event(ev, attach)
        for fn in self._listeners:
            try:
                fn(ev)
            except Exception:  # noqa: BLE001
                log.exception("Ошибка обработчика события")
