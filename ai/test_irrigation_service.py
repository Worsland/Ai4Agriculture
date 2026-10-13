"""Tests du service d'irrigation (base Firebase simulée en mémoire).

Lancer depuis ai/ :
    python -m pytest test_irrigation_service.py -v
"""

import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from irrigation_service import (
    INF,
    FirebaseRest,
    FreshnessTracker,
    IrrigationService,
)
from valve_controller import ValveController


class FakeDB:
    """Base en mémoire : get/put par chemin."""

    def __init__(self, data=None):
        self.data = data or {}
        self.writes = []

    def get(self, path):
        return self.data.get(path)

    def put(self, path, value):
        self.writes.append((path, value))
        self.data[path] = value


class FakeModel:
    """Renvoie un besoin fixe, ou lève ValueError si une entrée manque."""

    def __init__(self, need="High"):
        self.need = need

    def predict(self, measures):
        missing = [k for k, v in measures.items() if v is None]
        if missing:
            raise ValueError(f"Valeurs manquantes : {', '.join(missing)}")
        return {
            "need": self.need,
            "probabilities": {"Low": 0.0, "Medium": 0.0, "High": 1.0},
            "clipped": {},
            "model": "fake",
        }


class Clock:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t


def full_db(mode="auto", **extra):
    data = {
        "/valve/mode": mode,
        "/sensors": {"soil_moisture": 15, "temperature": 35},
        "/weather": {"rainfall": 200, "wind": 15},
        "/field": {"growth_stage": "Flowering", "mulching": False},
    }
    data.update(extra)
    return FakeDB(data)


def make_service(db, need="High"):
    clock = Clock()
    return IrrigationService(db, FakeModel(need), ValveController(), clock), clock


def warm_up(service, clock):
    """Deux observations différentes de /history : les mesures deviennent fraîches."""
    service.fresh.update("sig-0", clock.t)
    clock.t += 60
    service.fresh.update("sig-1", clock.t)


def command_writes(db):
    return [v for p, v in db.writes if p == "/valve/command"]


# ---------------------------------------------------------------- suivi de fraîcheur
def test_freshness_is_infinite_until_a_change_is_seen():
    tracker = FreshnessTracker()
    tracker.update("a", 0)
    assert tracker.age(10) == INF
    tracker.update("b", 60)
    assert tracker.age(100) == 40


def test_freshness_ignores_missing_signature():
    tracker = FreshnessTracker()
    tracker.update("a", 0)
    tracker.update("b", 60)
    tracker.update(None, 120)  # lecture impossible : pas un changement
    assert tracker.age(400) == 340


# ---------------------------------------------------------------- service
def test_manual_mode_never_writes_valve_command():
    db = full_db(mode="manual")
    service, clock = make_service(db)
    warm_up(service, clock)
    payload = service.step("sig-2")
    assert command_writes(db) == []
    assert payload["action"] == "manual"
    assert payload["mode"] == "manual"
    assert payload["need"] == "High"  # la recommandation est quand même publiée


def test_missing_mode_is_treated_as_manual():
    db = full_db(mode=None)
    service, clock = make_service(db)
    warm_up(service, clock)
    service.step("sig-2")
    assert command_writes(db) == []


def test_auto_opens_valve_when_need_is_high_and_data_fresh():
    db = full_db()
    service, clock = make_service(db)
    warm_up(service, clock)
    payload = service.step("sig-2")
    assert command_writes(db) == [True]
    assert payload["action"] == "open"
    assert db.data["/ai/irrigation"]["need"] == "High"


def test_auto_keeps_valve_closed_right_after_startup():
    # Une seule observation de /history : fraîcheur inconnue -> sécurité
    db = full_db()
    service, clock = make_service(db)
    payload = service.step("sig-0")
    assert command_writes(db) == [False]
    assert "trop anciennes" in payload["reason"]


def test_auto_closes_valve_when_history_stops_updating():
    db = full_db()
    service, clock = make_service(db)
    warm_up(service, clock)
    service.step("sig-1")
    assert command_writes(db)[-1] is True
    clock.t += 400  # plus aucune nouvelle entrée depuis plus de 5 min
    payload = service.step("sig-1")
    assert command_writes(db)[-1] is False
    assert payload["action"] == "close"


def test_missing_weather_blocks_decision_and_reports_error():
    db = full_db()
    del db.data["/weather"]
    service, clock = make_service(db)
    warm_up(service, clock)
    payload = service.step("sig-2")
    assert command_writes(db) == [False]
    assert payload["need"] is None
    assert "rainfall" in payload["error"] and "wind" in payload["error"]


def test_low_need_keeps_valve_closed():
    db = full_db()
    service, clock = make_service(db, need="Low")
    warm_up(service, clock)
    service.step("sig-2")
    assert command_writes(db) == [False]


def test_service_adopts_valve_state_reported_by_esp32():
    db = full_db(**{"/valve/state": {"open": True, "angle": 90}})
    service, clock = make_service(db, need="Medium")
    warm_up(service, clock)
    service.step("sig-2")
    assert service.controller.is_open is True


def test_switching_to_manual_resets_controller():
    db = full_db()
    service, clock = make_service(db)
    warm_up(service, clock)
    service.step("sig-2")
    assert service.controller.is_open
    db.data["/valve/mode"] = "manual"
    service.step("sig-3")
    assert service.controller.is_open is False


def test_payload_contains_inputs_and_timestamp():
    db = full_db()
    service, clock = make_service(db)
    warm_up(service, clock)
    payload = service.step("sig-2")
    assert payload["inputs"]["growth_stage"] == "Flowering"
    assert payload["updated_at"] == int(clock.t * 1000)


# ---------------------------------------------------------------- accès REST
class _Handler(BaseHTTPRequestHandler):
    store = {}
    requests_seen = []

    def _send(self, body):
        data = json.dumps(body).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        _Handler.requests_seen.append(("GET", self.path))
        self._send(_Handler.store.get(self.path.split("?")[0]))

    def do_PUT(self):
        length = int(self.headers.get("Content-Length", 0))
        body = json.loads(self.rfile.read(length))
        _Handler.requests_seen.append(("PUT", self.path, body))
        _Handler.store[self.path.split("?")[0]] = body
        self._send(body)

    def log_message(self, *args):
        pass


@pytest.fixture
def rest_server():
    _Handler.store = {"/sensors.json": {"temperature": 21.5}}
    _Handler.requests_seen = []
    server = HTTPServer(("127.0.0.1", 0), _Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{server.server_port}/"
    server.shutdown()


def test_rest_get_builds_json_url(rest_server):
    db = FirebaseRest(rest_server)
    assert db.get("/sensors") == {"temperature": 21.5}
    assert _Handler.requests_seen[0] == ("GET", "/sensors.json")


def test_rest_put_sends_booleans_and_dicts(rest_server):
    db = FirebaseRest(rest_server)
    db.put("/valve/command", False)
    db.put("/ai/irrigation", {"need": "Low", "probabilities": {"Low": 0.9}})
    assert _Handler.store["/valve/command.json"] is False
    assert _Handler.store["/ai/irrigation.json"]["need"] == "Low"


def test_rest_get_returns_none_for_missing_node(rest_server):
    assert FirebaseRest(rest_server).get("/weather") is None
