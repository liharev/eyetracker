"""Отправка e-mail (SMTP) и отчёты по расписанию."""
from __future__ import annotations

import json
import logging
import queue
import smtplib
import socket
import ssl
import threading
import time
from datetime import datetime, timedelta
from email.message import EmailMessage
from email.utils import formatdate, make_msgid
from pathlib import Path
from typing import List, Optional, Tuple

from .config import EVENT_CATEGORIES, EmailConfig, ScheduleConfig, category_title
from .i18n import app_name, tr
from .events import Event, EventStore, events_to_csv

log = logging.getLogger(__name__)


def parse_recipients(value: str) -> List[str]:
    return [r.strip() for r in value.replace(";", ",").split(",") if r.strip()]


def is_configured(cfg: EmailConfig) -> bool:
    return bool(cfg.smtp_host and parse_recipients(cfg.recipients))


def build_message(cfg: EmailConfig, subject: str, body: str,
                  attachments: Optional[List[Tuple[str, bytes, str, str]]] = None) -> EmailMessage:
    msg = EmailMessage()
    sender = cfg.sender or cfg.username or f"eyetracker@{socket.gethostname()}"
    msg["From"] = sender
    msg["To"] = ", ".join(parse_recipients(cfg.recipients))
    msg["Subject"] = f"{cfg.subject_prefix} {subject}".strip()
    msg["Date"] = formatdate(localtime=True)
    msg["Message-ID"] = make_msgid(domain=sender.split("@")[-1] if "@" in sender else None)
    msg.set_content(body)
    for filename, data, maintype, subtype in attachments or []:
        msg.add_attachment(data, maintype=maintype, subtype=subtype, filename=filename)
    return msg


def send_message(cfg: EmailConfig, msg: EmailMessage) -> None:
    if not is_configured(cfg):
        raise RuntimeError(tr("Не настроен SMTP-сервер или адрес получателя"))
    ctx = ssl.create_default_context()
    if cfg.security == "ssl":
        server = smtplib.SMTP_SSL(cfg.smtp_host, cfg.smtp_port, timeout=cfg.timeout_s, context=ctx)
    else:
        server = smtplib.SMTP(cfg.smtp_host, cfg.smtp_port, timeout=cfg.timeout_s)
    try:
        server.ehlo()
        if cfg.security == "starttls":
            server.starttls(context=ctx)
            server.ehlo()
        if cfg.username:
            server.login(cfg.username, cfg.password)
        server.send_message(msg)
    finally:
        try:
            server.quit()
        except Exception:  # noqa: BLE001
            pass


def host_info() -> str:
    return tr("Компьютер: {host}", host=socket.gethostname())


def format_event(ev: Event) -> str:
    lines = [
        tr("Время: {value}", value=ev.time_str),
        tr("Категория: {value}", value=ev.category_title),
        tr("Событие: {value}", value=ev.message),
        host_info(),
    ]
    if ev.details:
        lines.append(tr("Подробности: {value}", value=json.dumps(ev.details, ensure_ascii=False)))
    return "\n".join(lines)


class Mailer:
    """Асинхронная отправка писем с повторными попытками."""

    RETRIES = 3

    def __init__(self, cfg: EmailConfig, sender=send_message):
        self.cfg = cfg
        self._send = sender
        self._queue: "queue.Queue[Optional[Tuple[EmailMessage, str]]]" = queue.Queue(maxsize=200)
        self._thread = threading.Thread(target=self._worker, name="mailer", daemon=True)
        self._thread.start()
        self.last_error = ""

    def set_config(self, cfg: EmailConfig) -> None:
        self.cfg = cfg

    def stop(self) -> None:
        try:
            self._queue.put_nowait(None)
        except queue.Full:
            pass
        self._thread.join(timeout=5)

    def send_event(self, ev: Event, snapshot_jpeg: Optional[bytes]) -> None:
        if not is_configured(self.cfg):
            log.warning("Событие не отправлено по e-mail: SMTP не настроен")
            return
        attachments = []
        if snapshot_jpeg:
            attachments.append((f"snapshot-{int(ev.ts)}.jpg", snapshot_jpeg, "image", "jpeg"))
        msg = build_message(self.cfg, ev.message, format_event(ev), attachments)
        self.enqueue(msg, ev.message)

    def enqueue(self, msg: EmailMessage, label: str) -> None:
        try:
            self._queue.put_nowait((msg, label))
        except queue.Full:
            log.error("Очередь писем переполнена, письмо «%s» отброшено", label)

    def send_now(self, msg: EmailMessage) -> None:
        """Синхронная отправка (для тестового письма и отчёта)."""
        self._send(self.cfg, msg)

    def _worker(self) -> None:
        while True:
            item = self._queue.get()
            if item is None:
                return
            msg, label = item
            for attempt in range(1, self.RETRIES + 1):
                try:
                    self._send(self.cfg, msg)
                    log.info("Письмо отправлено: %s", label)
                    self.last_error = ""
                    break
                except Exception as exc:  # noqa: BLE001
                    self.last_error = str(exc)
                    log.warning("Ошибка отправки письма «%s» (попытка %d): %s", label, attempt, exc)
                    time.sleep(min(30, 5 * attempt))


# ---------------------------------------------------------------------- отчёт
def parse_times(value: str) -> List[Tuple[int, int]]:
    out = []
    for part in value.replace(";", ",").split(","):
        part = part.strip()
        if not part:
            continue
        hh, _, mm = part.partition(":")
        h, m = int(hh), int(mm or 0)
        if not (0 <= h < 24 and 0 <= m < 60):
            raise ValueError(tr("Неверное время: {value}", value=part))
        out.append((h, m))
    return sorted(set(out))


def next_digest_time(after: datetime, cfg: ScheduleConfig) -> datetime:
    if cfg.mode == "daily":
        try:
            times = parse_times(cfg.daily_times)
        except ValueError:
            times = []
        if times:
            for day in range(0, 2):
                base = (after + timedelta(days=day)).replace(second=0, microsecond=0)
                for h, m in times:
                    cand = base.replace(hour=h, minute=m)
                    if cand > after:
                        return cand
    return after + timedelta(minutes=max(1, cfg.interval_min))


def build_digest(cfg: EmailConfig, events: List[Event], period_from: Optional[datetime],
                 period_to: datetime) -> EmailMessage:
    lines = [
        tr("Отчёт {app} о событиях", app=app_name()),
        host_info(),
        tr("Период: {start} — {end}", start=period_from.strftime('%Y-%m-%d %H:%M') if period_from else '—',
           end=period_to.strftime('%Y-%m-%d %H:%M')),
        tr("Всего событий: {n}", n=len(events)),
        "",
    ]
    counts = {}
    for e in events:
        counts[e.category] = counts.get(e.category, 0) + 1
    for cat in EVENT_CATEGORIES:
        if counts.get(cat):
            lines.append(f"  {category_title(cat)}: {counts[cat]}")
    lines.append("")
    for e in events[:500]:
        lines.append(f"{e.time_str}  {e.message}")
    if len(events) > 500:
        lines.append(tr("... и ещё {n} (см. вложение CSV)", n=len(events) - 500))
    attachments = [("events.csv", events_to_csv(events).encode("utf-8-sig"), "text", "csv")] if events else []
    return build_message(cfg, tr("Отчёт о событиях ({n})", n=len(events)), "\n".join(lines), attachments)


class DigestScheduler:
    def __init__(self, get_config, store: EventStore, mailer: Mailer, state_path: Path):
        self._get_config = get_config
        self.store = store
        self.mailer = mailer
        self.state_path = Path(state_path)
        self._stop = threading.Event()
        self._wake = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self.next_run: Optional[datetime] = None
        self.last_run: Optional[datetime] = self._load_last()

    def _load_last(self) -> Optional[datetime]:
        try:
            ts = json.loads(self.state_path.read_text())["last_digest"]
            return datetime.fromtimestamp(float(ts))
        except (OSError, ValueError, KeyError, TypeError):
            return None

    def _save_last(self) -> None:
        try:
            self.state_path.write_text(json.dumps({"last_digest": self.last_run.timestamp()}))
        except OSError as exc:
            log.warning("Не удалось сохранить время последнего отчёта: %s", exc)

    def start(self) -> None:
        self._thread = threading.Thread(target=self._run, name="digest", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        self._wake.set()
        if self._thread:
            self._thread.join(timeout=3)

    def reschedule(self) -> None:
        self.next_run = None
        self._wake.set()

    def _run(self) -> None:
        while not self._stop.is_set():
            cfg = self._get_config()
            now = datetime.now()
            if self.next_run is None:
                self.next_run = next_digest_time(self.last_run or now, cfg.schedule)
                log.info("Следующий отчёт по расписанию: %s", self.next_run.strftime("%Y-%m-%d %H:%M"))
            if now >= self.next_run:
                self.send_digest()
                self.next_run = next_digest_time(datetime.now(), cfg.schedule)
                log.info("Следующий отчёт по расписанию: %s", self.next_run.strftime("%Y-%m-%d %H:%M"))
            self._wake.wait(20)
            self._wake.clear()

    def send_digest(self, force: bool = False) -> Tuple[bool, str]:
        cfg = self._get_config()
        events = self.store.pending_digest()
        now = datetime.now()
        if not events and not (cfg.schedule.send_empty or force):
            self.last_run = now
            self._save_last()
            return True, tr("Новых событий нет — отчёт не отправлялся")
        if not is_configured(cfg.email):
            return False, tr("SMTP не настроен — события сохранены и будут отправлены позже")
        msg = build_digest(cfg.email, events, self.last_run, now)
        try:
            self.mailer.send_now(msg)
        except Exception as exc:  # noqa: BLE001
            log.error("Не удалось отправить отчёт: %s", exc)
            return False, tr("Ошибка отправки: {error}", error=exc)
        self.store.mark_digested([e.id for e in events if e.id is not None])
        self.last_run = now
        self._save_last()
        log.info("Отчёт отправлен (%d событий)", len(events))
        return True, tr("Отчёт отправлен ({n} событий)", n=len(events))
