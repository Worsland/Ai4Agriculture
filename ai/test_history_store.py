"""Tests de l'historique agricole (Firestore simulé en mémoire).

Lancer depuis ai/ :
    python -m pytest test_history_store.py -v
"""

from datetime import datetime

from history_store import (
    HistoryRecorder,
    ValveEventTracker,
    add_sample,
    day_id,
    empty_delta,
    merge_daily,
)


class FakeStore:
    """Magasin en mémoire ; `fail` simule une panne de Firestore."""

    def __init__(self):
        self.events = []
        self.daily = {}
        self.fail = False

    def add_event(self, event):
        if self.fail:
            raise RuntimeError("Firestore indisponible")
        self.events.append(event)

    def get_daily(self, day):
        if self.fail:
            raise RuntimeError("Firestore indisponible")
        return self.daily.get(day)

    def set_daily(self, day, data):
        if self.fail:
            raise RuntimeError("Firestore indisponible")
        self.daily[day] = data


class FakeDB:
    def __init__(self, sensors=None, valve_open=None, mode="auto"):
        self.data = {
            "/sensors": sensors or {"temperature": 20.0, "humidity": 50.0, "soil_moisture": 30.0},
            "/valve/state": {"open": valve_open} if valve_open is not None else None,
            "/valve/mode": mode,
        }

    def get(self, path):
        return self.data.get(path)


class Clock:
    def __init__(self, t=None):
        self.t = t if t is not None else datetime(2026, 10, 20, 10, 0, 0).timestamp()

    def __call__(self):
        return self.t


def make(flush_every=600, **db_kwargs):
    clock, store, db = Clock(), FakeStore(), FakeDB(**db_kwargs)
    return HistoryRecorder(db, store, clock, flush_every=flush_every), db, store, clock


# ---------------------------------------------------------------- cumuls et fusion
def test_add_sample_tracks_min_max_sum_and_ignores_invalid_values():
    delta = empty_delta()
    add_sample(delta, {"temperature": 20, "soil_moisture": "abc", "ph": None, "light": float("nan")})
    add_sample(delta, {"temperature": 30.0})
    assert delta["samples"] == 2
    assert delta["sensors"]["temperature"] == {"n": 2, "sum": 50.0, "min": 20.0, "max": 30.0}
    assert set(delta["sensors"]) == {"temperature"}


def test_merge_daily_combines_with_stored_document():
    d1 = empty_delta()
    add_sample(d1, {"temperature": 10})
    add_sample(d1, {"temperature": 20})
    first = merge_daily(None, d1)
    d2 = empty_delta()
    add_sample(d2, {"temperature": 40})
    d2["valve_open_s"] = 300.0
    d2["irrigation_count"] = 1
    merged = merge_daily(first, d2)
    temp = merged["sensors"]["temperature"]
    assert merged["samples"] == 3
    assert (temp["min"], temp["max"], temp["n"]) == (10.0, 40.0, 3)
    assert temp["avg"] == round(70 / 3, 3)
    assert merged["valve_open_s"] == 300.0 and merged["irrigation_count"] == 1


# ---------------------------------------------------------------- événements de vanne
def test_tracker_returns_event_when_valve_closes():
    tracker = ValveEventTracker()
    assert tracker.update(False, 0) is None
    assert tracker.update(True, 100, {"mode": "auto", "need": "High", "reason": "r"}) is None
    event = tracker.update(False, 400)
    assert event["duration_s"] == 300
    assert event["mode"] == "auto" and event["need"] == "High"
    assert event["approximate"] is False


def test_tracker_marks_valve_already_open_at_startup_as_approximate():
    tracker = ValveEventTracker()
    tracker.update(True, 0)
    assert tracker.update(False, 120)["approximate"] is True


def test_tracker_ignores_unreadable_state():
    tracker = ValveEventTracker()
    tracker.update(True, 0)
    assert tracker.update(None, 60) is None
    assert tracker.open_since == 0  # l'ouverture en cours n'est pas perdue


# ---------------------------------------------------------------- enregistreur
def test_first_signature_is_not_counted_then_new_entries_are():
    rec, db, store, clock = make()
    rec.step("sig-0")
    assert rec.pending == {}
    clock.t += 60
    rec.step("sig-1")
    clock.t += 60
    rec.step("sig-1")  # pas de nouvelle entrée : mesure périmée, non comptée
    assert rec.pending[day_id(clock.t)]["samples"] == 1


def test_summary_is_written_only_after_flush_interval():
    rec, db, store, clock = make(flush_every=600)
    rec.step("a")
    clock.t += 60
    rec.step("b")
    assert store.daily == {}
    clock.t += 600
    rec.step("c")
    day = day_id(clock.t)
    assert store.daily[day]["samples"] == 2
    assert store.daily[day]["sensors"]["temperature"]["avg"] == 20.0
    assert store.daily[day]["date"] == day


def test_flush_merges_into_existing_summary_after_server_restart():
    rec, db, store, clock = make()
    store.daily[day_id(clock.t)] = {
        "samples": 10,
        "sensors": {"temperature": {"n": 10, "sum": 100.0, "min": 5.0, "max": 15.0, "avg": 10.0}},
        "valve_open_s": 60.0,
        "irrigation_count": 1,
    }
    rec.step("a")
    clock.t += 60
    rec.step("b")
    rec.flush(force=True)
    stored = store.daily[day_id(clock.t)]
    assert stored["samples"] == 11
    assert stored["sensors"]["temperature"]["min"] == 5.0
    assert stored["valve_open_s"] == 60.0


def test_valve_cycle_creates_event_and_counts_in_daily_summary():
    rec, db, store, clock = make()
    rec.step("a", {"mode": "auto", "need": "High", "reason": "besoin élevé"})
    db.data["/valve/state"] = {"open": True}
    clock.t += 60
    rec.step("b", {"mode": "auto", "need": "High", "reason": "besoin élevé"})
    clock.t += 300
    db.data["/valve/state"] = {"open": False}
    rec.step("c", {"mode": "auto", "need": "Low", "reason": "ok"})
    assert len(store.events) == 1
    event = store.events[0]
    assert event["duration_s"] == 300 and event["need"] == "High" and event["mode"] == "auto"
    rec.flush(force=True)
    daily = store.daily[day_id(clock.t)]
    assert daily["valve_open_s"] == 300.0 and daily["irrigation_count"] == 1


def test_mode_falls_back_to_valve_mode_when_irrigation_is_disabled():
    rec, db, store, clock = make(valve_open=True, mode="manual")
    rec.step("a")
    db.data["/valve/state"] = {"open": False}
    clock.t += 120
    rec.step("b")
    assert store.events[0]["mode"] == "manual"


def test_store_failure_keeps_data_and_retries_next_cycle():
    rec, db, store, clock = make(flush_every=60)
    rec.step("a")
    clock.t += 60
    rec.step("b")
    db.data["/valve/state"] = {"open": True}
    clock.t += 60
    store.fail = True
    rec.step("c")
    db.data["/valve/state"] = {"open": False}
    clock.t += 60
    rec.step("d")  # panne : rien n'est perdu
    assert store.events == []
    assert store.daily[day_id(clock.t)]["samples"] == 1  # seul le résumé d'avant la panne
    assert len(rec.events_out) == 1
    store.fail = False
    clock.t += 60
    rec.step("e")
    assert len(store.events) == 1
    assert store.daily[day_id(clock.t)]["samples"] >= 3
    assert rec.pending == {} and rec.events_out == []


def test_day_change_flushes_previous_day_immediately():
    late = datetime(2026, 10, 20, 23, 59, 0).timestamp()
    rec, db, store, clock = make(flush_every=10_000)
    clock.t = late
    rec.last_flush = late
    rec.step("a")
    clock.t = late + 30
    rec.step("b")           # encore le 20 octobre, rien d'écrit
    assert store.daily == {}
    clock.t = late + 120    # 21 octobre 00:01
    rec.step("c")
    assert "2026-10-20" in store.daily
    assert store.daily["2026-10-20"]["samples"] == 1