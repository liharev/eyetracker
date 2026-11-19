"""Логика правил 1–6 без привязки к камере, GUI и системе.

На вход каждый такт получает «наблюдение» (кто в кадре, куда смотрит авторизованный
пользователь, заблокирован ли экран), на выходе — события, требование блокировки
и стадию предупреждения о взгляде. Время передаётся явно, что упрощает тестирование.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import IntEnum
from typing import Dict, List, Optional, Set

from .config import Config

AUTHORIZED = "authorized"
UNKNOWN = "unknown"
PENDING = "pending"


class GazeStage(IntEnum):
    NORMAL = 0   # взгляд на экране / контроль не активен
    RED = 1      # T1: красная рамка
    BLINK = 2    # T2: красная мигающая рамка
    SOUND = 3    # T3: мигающая рамка + звуковой сигнал


GAZE_STAGE_TEXT = {
    GazeStage.NORMAL: "норма",
    GazeStage.RED: "красная рамка",
    GazeStage.BLINK: "мигающая рамка",
    GazeStage.SOUND: "звуковой сигнал",
}


@dataclass
class FaceInfo:
    track_id: int
    status: str                      # authorized | unknown | pending
    person_id: Optional[str] = None
    name: Optional[str] = None
    score: float = 0.0
    area: float = 0.0


@dataclass
class Observation:
    t: float
    faces: List[FaceInfo]
    # Взгляд авторизованного пользователя: True — на экран, False — мимо,
    # None — оценить невозможно (авторизованного лица нет в кадре).
    gaze_on_screen: Optional[bool] = None
    screen_locked: Optional[bool] = None  # None — состояние неизвестно


@dataclass
class PolicyEvent:
    category: str
    type: str
    message: str
    details: Dict = field(default_factory=dict)


@dataclass
class PolicyResult:
    events: List[PolicyEvent] = field(default_factory=list)
    lock_reason: Optional[str] = None     # категория правила, вызвавшего блокировку
    gaze_stage: GazeStage = GazeStage.NORMAL
    away_s: float = 0.0


LOCK_PRIORITY = ("lock_stranger", "lock_unauthorized", "lock_absence")
LOCK_TEXT = {
    "lock_absence": "Экран заблокирован: перед экраном никого нет",
    "lock_unauthorized": "Экран заблокирован: перед экраном нет авторизованного лица",
    "lock_stranger": "Экран заблокирован: обнаружено постороннее лицо",
}


class Policy:
    def __init__(self, cfg: Config, t0: float):
        self.cfg = cfg
        self.reset(t0)

    def reset(self, t: float) -> None:
        # п.1 присутствие
        self._present = False
        self._last_face_t = t
        # п.2 распознавание
        self._person_last_seen: Dict[str, float] = {}
        self._announced_persons: Set[str] = set()
        self._announced_unknown: Set[int] = set()
        # п.3/4 таймеры
        self._last_authorized_t = t
        # п.5
        self._unknown_since: Dict[int, float] = {}
        # блокировка
        self._episode_fired: Dict[str, bool] = {}
        self._last_lock_t = -1e9
        # п.6
        self._away_since: Optional[float] = None
        self._return_since: Optional[float] = None
        self._stage = GazeStage.NORMAL
        self._authorized_seen = False

    def set_config(self, cfg: Config) -> None:
        self.cfg = cfg

    # ------------------------------------------------------------------
    def update(self, obs: Observation) -> PolicyResult:
        res = PolicyResult()
        t = obs.t
        faces = obs.faces
        authorized = [f for f in faces if f.status == AUTHORIZED]
        unknown = [f for f in faces if f.status == UNKNOWN]

        self._presence(t, faces, res)
        self._recognition(t, faces, authorized, unknown, res)

        if authorized:
            self._last_authorized_t = t

        conditions = self._lock_conditions(t, faces, unknown)
        self._lock_controller(t, conditions, obs.screen_locked, faces, res)

        self._gaze(t, obs, bool(authorized), res)
        return res

    # ---------------------------------------------------------------- п.1
    def _presence(self, t: float, faces: List[FaceInfo], res: PolicyResult) -> None:
        if faces:
            self._last_face_t = t
            if not self._present:
                self._present = True
                res.events.append(PolicyEvent(
                    "presence", "person_appeared",
                    f"Перед экраном появился человек (лиц в кадре: {len(faces)})",
                    {"faces": len(faces)}))
        elif self._present and t - self._last_face_t >= self.cfg.presence.leave_debounce_s:
            self._present = False
            res.events.append(PolicyEvent("presence", "person_left", "Перед экраном никого нет", {}))

    # ---------------------------------------------------------------- п.2
    def _recognition(self, t, faces, authorized, unknown, res: PolicyResult) -> None:
        debounce = self.cfg.presence.leave_debounce_s
        for f in authorized:
            pid = f.person_id or f.name or "?"
            last = self._person_last_seen.get(pid)
            if pid not in self._announced_persons or last is None or t - last > debounce:
                self._announced_persons.add(pid)
                res.events.append(PolicyEvent(
                    "recognition", "authorized_recognized",
                    f"Распознано авторизованное лицо: {f.name} (сходство {f.score:.2f})",
                    {"person_id": f.person_id, "name": f.name, "score": round(f.score, 3)}))
            self._person_last_seen[pid] = t
        for f in unknown:
            if f.track_id not in self._announced_unknown:
                self._announced_unknown.add(f.track_id)
                res.events.append(PolicyEvent(
                    "recognition", "unknown_face",
                    f"Обнаружено неизвестное лицо (макс. сходство с базой {f.score:.2f})",
                    {"track_id": f.track_id, "score": round(f.score, 3)}))
        live_ids = {f.track_id for f in faces}
        self._announced_unknown &= live_ids | {f.track_id for f in unknown}
        for pid in [p for p, ts in self._person_last_seen.items() if t - ts > debounce]:
            self._announced_persons.discard(pid)
            del self._person_last_seen[pid]

    # ------------------------------------------------------------- п.3-5
    def _lock_conditions(self, t: float, faces, unknown) -> Dict[str, bool]:
        cfg = self.cfg
        cond = {k: False for k in LOCK_PRIORITY}
        # п.3 — никого нет дольше таймаута
        if cfg.presence.lock_on_absence and not faces:
            cond["lock_absence"] = t - self._last_face_t >= cfg.presence.absence_timeout_s
        # п.4 — нет авторизованного лица дольше таймаута (в т.ч. если есть другие лица)
        if cfg.authorized.lock_if_no_authorized:
            cond["lock_unauthorized"] = t - self._last_authorized_t >= cfg.authorized.timeout_s
        # п.5 — постороннее лицо видно дольше времени подтверждения
        live = {f.track_id for f in unknown}
        for tid in list(self._unknown_since):
            if tid not in live:
                del self._unknown_since[tid]
        for f in unknown:
            self._unknown_since.setdefault(f.track_id, t)
        if cfg.stranger.lock_on_stranger and self._unknown_since:
            first = min(self._unknown_since.values())
            cond["lock_stranger"] = t - first >= cfg.stranger.confirm_s
        return cond

    def _lock_controller(self, t, cond: Dict[str, bool], screen_locked: Optional[bool], faces,
                         res: PolicyResult) -> None:
        for key in LOCK_PRIORITY:
            if not cond[key]:
                self._episode_fired[key] = False
        if screen_locked:
            # экран уже заблокирован — считаем текущие эпизоды отработанными
            for key in LOCK_PRIORITY:
                if cond[key]:
                    self._episode_fired[key] = True
            return
        relock = self.cfg.lock.relock_interval_s
        for key in LOCK_PRIORITY:
            if not cond[key]:
                continue
            fired = self._episode_fired.get(key, False)
            # Повтор, только если точно известно, что экран снова разблокирован
            # (иначе — однократно на эпизод, чтобы не «дёргать» блокировку).
            repeat = fired and screen_locked is False and t - self._last_lock_t >= relock
            if not fired or repeat:
                self._episode_fired[key] = True
                if res.lock_reason is None:
                    res.lock_reason = key
                    self._last_lock_t = t
                    details = {"faces": len(faces)}
                    if key == "lock_stranger":
                        details["unknown_faces"] = len(self._unknown_since)
                    res.events.append(PolicyEvent(key, "screen_locked", LOCK_TEXT[key], details))

    # ---------------------------------------------------------------- п.6
    def _gaze(self, t: float, obs: Observation, has_authorized: bool, res: PolicyResult) -> None:
        g = self.cfg.gaze
        if not g.enabled or obs.screen_locked:
            self._reset_gaze(t, res, reason="disabled" if not g.enabled else "locked")
            if obs.screen_locked:
                self._authorized_seen = False
            return
        if has_authorized:
            self._authorized_seen = True
            away = obs.gaze_on_screen is False
        else:
            # авторизованное лицо пропало из кадра (например, отвернулся в профиль)
            away = g.face_lost_is_away and self._authorized_seen
            if not away:
                self._reset_gaze(t, res, reason="no_target")
                return

        if away:
            self._return_since = None
            if self._away_since is None:
                self._away_since = t
        elif self._away_since is not None:
            if self._return_since is None:
                self._return_since = t
            if t - self._return_since >= g.return_debounce_s:
                self._reset_gaze(t, res)
                return

        if self._away_since is None:
            res.gaze_stage = GazeStage.NORMAL
            return
        away_s = t - self._away_since
        res.away_s = away_s
        if away_s >= g.t3_s:
            stage = GazeStage.SOUND
        elif away_s >= g.t2_s:
            stage = GazeStage.BLINK
        elif away_s >= g.t1_s:
            stage = GazeStage.RED
        else:
            stage = GazeStage.NORMAL
        if stage > self._stage:
            for s in range(int(self._stage) + 1, int(stage) + 1):
                st = GazeStage(s)
                res.events.append(PolicyEvent(
                    "gaze", f"gaze_stage_{st.name.lower()}",
                    f"Взгляд не на экране {away_s:.1f} с — {GAZE_STAGE_TEXT[st]}",
                    {"stage": int(st), "away_s": round(away_s, 1)}))
            self._stage = stage
        res.gaze_stage = self._stage

    def _reset_gaze(self, t: float, res: PolicyResult, reason: str = "returned") -> None:
        if self._stage > GazeStage.NORMAL and reason != "disabled":
            away_s = t - self._away_since if self._away_since is not None else 0.0
            text = {
                "returned": "Взгляд вернулся на экран",
                "locked": "Экран заблокирован — предупреждения о взгляде сняты",
                "no_target": "Авторизованное лицо вне кадра — предупреждения о взгляде сняты",
            }[reason]
            res.events.append(PolicyEvent(
                "gaze", "gaze_returned" if reason == "returned" else "gaze_reset",
                f"{text} (взгляд отсутствовал {away_s:.1f} с)",
                {"away_s": round(away_s, 1), "reason": reason}))
        self._stage = GazeStage.NORMAL
        self._away_since = None
        self._return_since = None
        res.gaze_stage = GazeStage.NORMAL
