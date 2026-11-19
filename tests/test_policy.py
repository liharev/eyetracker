from eyetracker.config import Config
from eyetracker.policy import AUTHORIZED, PENDING, UNKNOWN, FaceInfo, GazeStage, Observation, Policy


def cfg(**kw):
    c = Config()
    c.presence.lock_on_absence = False
    for path, value in kw.items():
        section, name = path.split("__")
        setattr(getattr(c, section), name, value)
    return c


def auth(tid=1, name="Иван"):
    return FaceInfo(tid, AUTHORIZED, "p1", name, 0.7, 100)


def stranger(tid=2):
    return FaceInfo(tid, UNKNOWN, None, None, 0.1, 100)


def run(policy, t0, t1, faces, step=0.1, **obs_kw):
    results = []
    t = t0
    while t <= t1 + 1e-9:
        results.append(policy.update(Observation(round(t, 3), faces, **obs_kw)))
        t += step
    return results


def events(results, etype=None):
    out = [e for r in results for e in r.events]
    return [e for e in out if etype is None or e.type == etype]


def locks(results):
    return [r.lock_reason for r in results if r.lock_reason]


def test_presence_events_and_debounce():
    p = Policy(cfg(presence__leave_debounce_s=2.0), 0)
    r = run(p, 0, 1, [auth()])
    assert len(events(r, "person_appeared")) == 1
    r = run(p, 1.1, 2.5, [])
    assert not events(r, "person_left")          # меньше 2 с — ещё не ушёл
    r = run(p, 2.6, 4.0, [])
    assert len(events(r, "person_left")) == 1


def test_recognition_announced_once_per_visit():
    p = Policy(cfg(presence__leave_debounce_s=1.0), 0)
    r = run(p, 0, 3, [auth()])
    assert len(events(r, "authorized_recognized")) == 1
    run(p, 3.1, 5, [])
    r = run(p, 5.1, 6, [auth(tid=7)])
    assert len(events(r, "authorized_recognized")) == 1
    r = run(p, 6.1, 7, [auth(tid=7), stranger(9)])
    assert len(events(r, "unknown_face")) == 1


def test_lock_on_absence_after_timeout():
    p = Policy(cfg(presence__lock_on_absence=True, presence__absence_timeout_s=5), 0)
    run(p, 0, 1, [auth()])
    r = run(p, 1.1, 5.9, [])
    assert not locks(r)
    r = run(p, 6.0, 10, [])
    assert locks(r) == ["lock_absence"]          # однократно на эпизод
    assert len(events(r, "screen_locked")) == 1
    run(p, 10.1, 11, [auth()])                   # вернулся — эпизод сброшен
    r = run(p, 11.1, 20, [])
    assert locks(r) == ["lock_absence"]


def test_absence_disabled():
    p = Policy(cfg(presence__lock_on_absence=False), 0)
    assert not locks(run(p, 0, 100, [], step=1))


def test_lock_without_authorized_even_with_other_faces():
    p = Policy(cfg(authorized__lock_if_no_authorized=True, authorized__timeout_s=3), 0)
    run(p, 0, 1, [auth()])
    r = run(p, 1.1, 3.9, [stranger()])
    assert not locks(r)
    r = run(p, 4.0, 6, [stranger()])
    assert locks(r) == ["lock_unauthorized"]


def test_lock_on_stranger_even_with_authorized():
    p = Policy(cfg(stranger__lock_on_stranger=True, stranger__confirm_s=1.0), 0)
    r = run(p, 0, 0.8, [auth(), stranger()])
    assert not locks(r)
    r = run(p, 0.9, 2, [auth(), stranger()])
    assert locks(r) == ["lock_stranger"]


def test_stranger_rule_ignores_pending_faces():
    p = Policy(cfg(stranger__lock_on_stranger=True, stranger__confirm_s=0.5), 0)
    r = run(p, 0, 5, [auth(), FaceInfo(3, PENDING)])
    assert not locks(r)


def test_no_lock_when_already_locked_and_relock_when_unlocked():
    c = cfg(stranger__lock_on_stranger=True, stranger__confirm_s=0.0, lock__relock_interval_s=5)
    p = Policy(c, 0)
    r = run(p, 0, 0.5, [stranger()], screen_locked=False)
    assert locks(r) == ["lock_stranger"]
    r = run(p, 0.6, 10, [stranger()], screen_locked=True)
    assert not locks(r)
    # разблокировали, а посторонний всё ещё здесь — повторная блокировка
    r = run(p, 10.1, 16, [stranger()], screen_locked=False)
    assert locks(r)


def test_unknown_lock_state_does_not_spam():
    p = Policy(cfg(stranger__lock_on_stranger=True, stranger__confirm_s=0.0, lock__relock_interval_s=1), 0)
    r = run(p, 0, 30, [stranger()], screen_locked=None)
    assert locks(r) == ["lock_stranger"]


def gaze_cfg():
    return cfg(gaze__enabled=True, gaze__t1_s=2, gaze__t2_s=4, gaze__t3_s=6, gaze__return_debounce_s=0.3)


def test_gaze_stages_and_reset():
    p = Policy(gaze_cfg(), 0)
    r = run(p, 0, 1, [auth()], gaze_on_screen=True)
    assert r[-1].gaze_stage == GazeStage.NORMAL
    r = run(p, 1.1, 2.9, [auth()], gaze_on_screen=False)
    assert r[-1].gaze_stage == GazeStage.NORMAL
    r = run(p, 3.0, 3.2, [auth()], gaze_on_screen=False)
    assert r[-1].gaze_stage == GazeStage.RED
    r = run(p, 3.3, 5.2, [auth()], gaze_on_screen=False)
    assert r[-1].gaze_stage == GazeStage.BLINK
    r = run(p, 5.3, 8, [auth()], gaze_on_screen=False)
    assert r[-1].gaze_stage == GazeStage.SOUND
    # краткий взгляд на экран (меньше return_debounce) — стадия сохраняется
    r = run(p, 8.1, 8.2, [auth()], gaze_on_screen=True)
    assert r[-1].gaze_stage == GazeStage.SOUND
    r = run(p, 8.3, 9, [auth()], gaze_on_screen=True)
    assert r[-1].gaze_stage == GazeStage.NORMAL
    assert len(events(r, "gaze_returned")) == 1
    # таймеры сброшены: снова отсчёт с нуля
    r = run(p, 9.1, 10.5, [auth()], gaze_on_screen=False)
    assert r[-1].gaze_stage == GazeStage.NORMAL


def test_gaze_disabled():
    c = gaze_cfg()
    c.gaze.enabled = False
    p = Policy(c, 0)
    r = run(p, 0, 20, [auth()], gaze_on_screen=False)
    assert all(x.gaze_stage == GazeStage.NORMAL for x in r)


def test_gaze_face_lost_counts_as_away():
    p = Policy(gaze_cfg(), 0)
    run(p, 0, 1, [auth()], gaze_on_screen=True)
    r = run(p, 1.1, 4, [], gaze_on_screen=None)
    assert r[-1].gaze_stage == GazeStage.RED
    c = gaze_cfg()
    c.gaze.face_lost_is_away = False
    p = Policy(c, 0)
    run(p, 0, 1, [auth()], gaze_on_screen=True)
    r = run(p, 1.1, 10, [], gaze_on_screen=None)
    assert r[-1].gaze_stage == GazeStage.NORMAL


def test_gaze_only_for_authorized():
    p = Policy(gaze_cfg(), 0)
    r = run(p, 0, 10, [stranger()], gaze_on_screen=None)
    assert all(x.gaze_stage == GazeStage.NORMAL for x in r)


def test_gaze_reset_on_lock():
    p = Policy(gaze_cfg(), 0)
    r = run(p, 0, 7, [auth()], gaze_on_screen=False, screen_locked=False)
    assert r[-1].gaze_stage == GazeStage.SOUND
    r = run(p, 7.1, 8, [auth()], gaze_on_screen=False, screen_locked=True)
    assert r[-1].gaze_stage == GazeStage.NORMAL
