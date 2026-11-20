import json
import time
from datetime import datetime

import numpy as np
import pytest

from eyetracker import auth, sound
from eyetracker.config import Config, ConfigStore
from eyetracker.events import Event, EventDispatcher, EventStore
from eyetracker.mailer import DigestScheduler, Mailer, next_digest_time, parse_times
from eyetracker.resources import parse_cpu_list, efficiency_cores
from eyetracker.vision.gaze import GazeEstimator, GazeZone, head_pose_from_yunet
from eyetracker.vision.recognizer import FaceDatabase
from eyetracker.vision.tracker import AUTHORIZED, PENDING, UNKNOWN, FaceTracker


# ----------------------------------------------------------------- config
def test_config_roundtrip_and_permissions(tmp_path):
    store = ConfigStore(tmp_path / "c.json")
    c = Config()
    c.gaze.enabled = True
    c.gaze.t1_s, c.gaze.t2_s, c.gaze.t3_s = 9, 3, 1     # неверный порядок — исправляется
    c.notify.routes["gaze"].digest = True
    c.notify.routes["gaze"].log = False
    store.save(c)
    assert (tmp_path / "c.json").stat().st_mode & 0o777 == 0o600
    c2 = store.load()
    assert c2.gaze.enabled
    assert c2.gaze.t1_s <= c2.gaze.t2_s <= c2.gaze.t3_s
    assert c2.notify.routes["gaze"].log  # отчёт по расписанию требует журнала


def test_config_tolerates_garbage():
    c = Config.from_dict({"gaze": {"t1_s": "abc", "enabled": "true"}, "unknown": 1,
                          "notify": {"routes": {"presence": {"email": True}}}})
    assert c.gaze.enabled is True
    assert c.gaze.t1_s == Config().gaze.t1_s
    assert c.notify.routes["presence"].email
    assert "lock_stranger" in c.notify.routes


def test_config_migrates_v1_keys():
    c = Config.from_dict({"processing": {"use_mediapipe": False}})
    assert c.processing.precise_gaze is False


# ------------------------------------------------------------------- auth
def test_auth_and_lockout():
    a = Config().auth
    assert not auth.is_configured(a)
    auth.set_credentials(a, "admin", "s3cret")
    assert auth.verify(a, "admin", "s3cret")
    assert not auth.verify(a, "admin", "bad")
    assert "s3cret" not in json.dumps(a.__dict__)
    now = [0.0]
    guard = auth.LoginGuard(max_failures=3, lockout_s=60, clock=lambda: now[0])
    for _ in range(3):
        assert not guard.attempt(a, "admin", "x")[0]
    ok, msg = guard.attempt(a, "admin", "s3cret")
    assert not ok and "заблокирован" in msg.lower() or "повторите" in msg.lower()
    now[0] = 61
    assert guard.attempt(a, "admin", "s3cret")[0]


# ------------------------------------------------------- events / e-mail
class FakeMailer:
    def __init__(self):
        self.sent = []

    def send_event(self, ev, snap):
        self.sent.append((ev, snap))


def test_dispatch_routes(tmp_path):
    c = Config()
    c.notify.routes["presence"].email = True
    c.notify.routes["presence"].log = False
    c.notify.routes["presence"].digest = False
    c.notify.routes["lock_stranger"].log = True
    c.notify.routes["lock_stranger"].digest = True
    store = EventStore(tmp_path / "e.db", tmp_path / "snaps")
    fm = FakeMailer()
    d = EventDispatcher(c, store, fm)
    d.publish(Event("presence", "person_appeared", "появился", snapshot_jpeg=b"jpg"))
    d.publish(Event("lock_stranger", "screen_locked", "заблокировано", snapshot_jpeg=b"jpg"))
    assert len(fm.sent) == 1 and fm.sent[0][1] == b"jpg"
    evs = store.query()
    assert [e.category for e in evs] == ["lock_stranger"]
    assert evs[0].snapshot_path and (tmp_path / "snaps").exists()
    assert len(store.pending_digest()) == 1
    store.mark_digested([evs[0].id])
    assert store.pending_digest() == []


def test_schedule_times():
    c = Config().schedule
    c.mode = "daily"
    c.daily_times = "18:00, 09:30"
    assert parse_times(c.daily_times) == [(9, 30), (18, 0)]
    assert next_digest_time(datetime(2026, 1, 1, 10, 0), c) == datetime(2026, 1, 1, 18, 0)
    assert next_digest_time(datetime(2026, 1, 1, 19, 0), c) == datetime(2026, 1, 2, 9, 30)
    c.mode = "interval"
    c.interval_min = 15
    assert next_digest_time(datetime(2026, 1, 1, 10, 0), c) == datetime(2026, 1, 1, 10, 15)
    with pytest.raises(ValueError):
        parse_times("25:00")


def test_digest_send(tmp_path):
    c = Config()
    c.email.smtp_host = "smtp.example.com"
    c.email.recipients = "a@example.com"
    store = EventStore(tmp_path / "e.db")
    for i in range(3):
        store.add(Event("lock_absence", "screen_locked", f"событие {i}"), digest=True)
    sent = []
    mailer = Mailer(c.email, sender=lambda cfg, msg: sent.append(msg))
    sch = DigestScheduler(lambda: c, store, mailer, tmp_path / "state.json")
    ok, text = sch.send_digest()
    assert ok and len(sent) == 1
    body = sent[0].get_body(("plain",)).get_content()
    assert "Всего событий: 3" in body
    assert any(p.get_filename() == "events.csv" for p in sent[0].iter_attachments())
    assert store.pending_digest() == []
    assert DigestScheduler(lambda: c, store, mailer, tmp_path / "state.json").last_run is not None
    mailer.stop()


def test_immediate_mail_retries(tmp_path, monkeypatch):
    c = Config()
    c.email.smtp_host, c.email.recipients = "h", "a@b.c"
    calls = []

    def flaky(cfg, msg):
        calls.append(msg)
        if len(calls) == 1:
            raise OSError("temporary")

    monkeypatch.setattr(Mailer, "RETRIES", 2)
    m = Mailer(c.email, sender=flaky)
    import eyetracker.mailer as mm
    orig = mm.time.sleep
    mm.time.sleep = lambda s: None
    try:
        m.send_event(Event("gaze", "gaze_stage_sound", "звук"), b"\xff\xd8")
        t0 = time.time()
        while len(calls) < 2 and time.time() - t0 < 5:
            time.sleep(0.01)
    finally:
        mm.time.sleep = orig
        m.stop()
    assert len(calls) == 2
    assert any(p.get_content_type() == "image/jpeg" for p in calls[0].iter_attachments())


# ------------------------------------------------------------------ vision
def row(x, y, w, h):
    r = np.zeros(15, np.float32)
    r[:4] = (x, y, w, h)
    r[14] = 0.9
    return r


def test_tracker_identity_votes():
    tr = FaceTracker(max_age_s=0.5)
    t = tr.update(np.array([row(100, 100, 80, 80)]), 0.0)[0]
    assert t.status == PENDING
    t.add_vote("p1", "Иван", 0.6, 0.0)
    assert t.status == PENDING
    t.add_vote("p1", "Иван", 0.62, 0.1)
    assert t.status == AUTHORIZED and t.name == "Иван"
    t2 = tr.update(np.array([row(104, 102, 80, 80)]), 0.2)[0]
    assert t2.id == t.id                       # тот же трек
    tr.update(np.zeros((0, 15), np.float32), 0.6)
    assert tr.tracks                           # держится max_age
    tr.update(np.zeros((0, 15), np.float32), 0.8)
    assert not tr.tracks
    s = tr.update(np.array([row(10, 10, 80, 80)]), 1.0)[0]
    for i in range(3):
        s.add_vote(None, None, 0.1, 1.0 + i)
    assert s.status == UNKNOWN


def test_face_db(tmp_path):
    db = FaceDatabase(tmp_path / "faces")
    rng = np.random.default_rng(0)
    a = rng.normal(size=128).astype(np.float32)
    a /= np.linalg.norm(a)
    b = rng.normal(size=128).astype(np.float32)
    b /= np.linalg.norm(b)
    p = db.add_person("Анна", np.vstack([a, a]))
    db.add_person("Борис", b[None, :])
    assert db.match(a, 0.4).name == "Анна"
    assert db.match(-a, 0.4).person_id is None
    db2 = FaceDatabase(tmp_path / "faces")
    assert len(db2) == 2 and db2.get(p.id).samples == 2
    db2.remove(p.id)
    assert len(FaceDatabase(tmp_path / "faces")) == 1


def test_gaze_zone_and_geometry():
    z = GazeZone.from_points([(0, -10), (-20, 0), (20, 0), (20, -30), (-20, -30)], margin=2)
    assert z.contains(0, -15) and z.contains(21.5, 1.5)
    assert not z.contains(30, -15) and not z.contains(0, 10)
    # голова прямо: нос посередине между глазами
    r = np.array([0, 0, 100, 100, 30, 40, 70, 40, 50, 62, 35, 80, 65, 80, 1], np.float32)
    yaw, pitch = head_pose_from_yunet(r)
    assert abs(yaw) < 1 and abs(pitch) < 15
    r[8] = 60  # нос смещён вправо по изображению → поворот вправо
    assert head_pose_from_yunet(r)[0] > 10


def test_iris_composition():
    pts = np.zeros((478, 2))
    # глаз A: уголки (0.30,0.40)-(0.40,0.40), глаз B: (0.60,0.40)-(0.70,0.40)
    pts[33], pts[133], pts[159], pts[145] = (0.30, 0.40), (0.40, 0.40), (0.35, 0.385), (0.35, 0.415)
    pts[362], pts[263], pts[386], pts[374] = (0.60, 0.40), (0.70, 0.40), (0.65, 0.385), (0.65, 0.415)
    pts[468], pts[473] = (0.35, 0.40), (0.65, 0.40)
    s = GazeEstimator.compose(pts, 0.0, -10.0, 2.5)
    assert abs(s.yaw) < 1e-6 and abs(s.pitch + 10) < 1e-6 and not s.eyes_closed
    pts[468], pts[473] = (0.37, 0.40), (0.67, 0.40)      # радужки вправо
    assert GazeEstimator.compose(pts, 0.0, 0.0, 2.5).yaw > 20
    pts[468], pts[473] = (0.35, 0.405), (0.65, 0.405)    # радужки вниз
    assert GazeEstimator.compose(pts, 0.0, 0.0, 2.5).pitch < -5
    pts[159], pts[145], pts[386], pts[374] = (0.35, 0.399), (0.35, 0.401), (0.65, 0.399), (0.65, 0.401)
    assert GazeEstimator.compose(pts, 0.0, 0.0, 2.5).eyes_closed


# ------------------------------------------------------------- resources/sound
def test_cpu_helpers(tmp_path):
    assert parse_cpu_list("0-2,5") == {0, 1, 2, 5}
    for i, cap in enumerate([414, 414, 414, 414, 1024, 1024, 1024, 1024]):
        d = tmp_path / f"cpu{i}"
        d.mkdir()
        (d / "cpu_capacity").write_text(str(cap))
    assert efficiency_cores(tmp_path) == [0, 1, 2, 3]


def test_sounds(tmp_path):
    sound.ensure_builtin_sounds()
    ids = [sid for sid, _ in sound.list_sounds()]
    assert ids[:3] == ["builtin:beep", "builtin:chime", "builtin:siren"]
    for sid in ids:
        assert sound.resolve(sid).stat().st_size > 1000
    src = tmp_path / "мой сигнал.wav"
    src.write_bytes(sound.resolve("builtin:beep").read_bytes())
    sid = sound.import_sound(src)
    assert sound.resolve(sid) is not None
    assert sound.resolve("custom:../../etc/passwd") is None
    with pytest.raises(ValueError):
        sound.delete_sound("builtin:beep")
    sound.delete_sound(sid)
    assert sound.resolve(sid) is None
