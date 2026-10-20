"""Tests de l'API en lecture seule (api.py).

Aucun réseau : Firebase et Firestore sont remplacés par de faux objets, et le
client de test de FastAPI appelle l'application directement.

Lancer depuis ai/ :
    python -m pytest test_api.py -v
"""

from datetime import datetime, timezone

import pytest
import requests
from fastapi.testclient import TestClient

from api import create_app

NOW = 1_760_950_000.0


class FakeDB:
    """Realtime Database en mémoire. Elle n'a volontairement pas de méthode put :
    si l'API essayait d'écrire, un test échouerait."""

    def __init__(self, data=None, error=None):
        self.data = data if data is not None else {}
        self.error = error
        self.reads = []

    def get(self, path):
        self.reads.append(path)
        if self.error:
            raise self.error
        return self.data.get(path)


class FakeStore:
    def __init__(self, fail=False):
        self.fail = fail
        self.calls = []
        self.daily = [{"date": "2026-10-20", "samples": 40}, {"date": "2026-10-19", "samples": 10}]
        self.events = [{
            "id": "e1", "day": "2026-10-20", "duration_s": 300, "mode": "auto",
            "opened_at": datetime(2026, 10, 20, 8, 0, tzinfo=timezone.utc),
        }]

    def list_daily(self, days):
        self.calls.append(("daily", days))
        if self.fail:
            raise RuntimeError("Firestore indisponible")
        return self.daily[:days]

    def list_events(self, limit):
        self.calls.append(("events", limit))
        if self.fail:
            raise RuntimeError("Firestore indisponible")
        return self.events[:limit]


DATA = {
    "/valve/mode": "auto",
    "/sensors": {"temperature": 23.4, "humidity": 58.1, "soil_moisture": 41.2, "ph": 6.8, "light": 72.5},
    "/ai/prediction": {"temperature": 23.6, "humidity": 57.9, "updated_at": int((NOW - 90) * 1000)},
    "/ai/status": {"samples": 120, "mae": {"temperature": 0.1}, "baseline_mae": {"temperature": 0.2}},
    "/ai/irrigation": {
        "need": "High", "action": "open", "reason": "besoin élevé", "mode": "auto",
        "command": True, "updated_at": int((NOW - 30) * 1000),
    },
}


def make_client(data=None, store=None, error=None):
    db = FakeDB(DATA if data is None else data, error)
    app = create_app(db=db, store=store, clock=lambda: NOW)
    return TestClient(app), db


# ---------------------------------------------------------------- santé
def test_health_ok_reports_firestore_configuration():
    client, _ = make_client(store=FakeStore())
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "firebase": True, "firestore": True}


def test_health_without_firestore():
    client, _ = make_client(store=None)
    assert client.get("/health").json()["firestore"] is False


def test_health_returns_503_when_firebase_is_unreachable():
    client, _ = make_client(error=requests.ConnectionError("réseau coupé"))
    response = client.get("/health")
    assert response.status_code == 503
    assert response.json()["status"] == "degraded"
    assert response.json()["firebase"] is False


# ---------------------------------------------------------------- Firebase
def test_sensors_returns_latest_measure():
    client, db = make_client()
    response = client.get("/sensors")
    assert response.status_code == 200
    assert response.json()["soil_moisture"] == 41.2
    assert db.reads == ["/sensors"]


def test_sensors_404_when_no_measure():
    client, _ = make_client(data={})
    assert client.get("/sensors").status_code == 404


def test_prediction_includes_age_and_model_quality():
    client, _ = make_client()
    body = client.get("/prediction").json()
    assert body["temperature"] == 23.6
    assert body["age_s"] == 90
    assert body["status"]["samples"] == 120


def test_prediction_404_when_server_never_wrote_one():
    client, _ = make_client(data={"/sensors": {"temperature": 20}})
    assert client.get("/prediction").status_code == 404


def test_irrigation_includes_recommendation_and_age():
    client, _ = make_client()
    body = client.get("/irrigation").json()
    assert body["need"] == "High" and body["action"] == "open"
    assert body["age_s"] == 30


def test_irrigation_age_is_null_without_timestamp():
    data = {**DATA, "/ai/irrigation": {"need": "Low"}}
    client, _ = make_client(data=data)
    assert client.get("/irrigation").json()["age_s"] is None


def test_irrigation_age_never_negative_with_clock_skew():
    data = {**DATA, "/ai/irrigation": {"need": "Low", "updated_at": int((NOW + 600) * 1000)}}
    client, _ = make_client(data=data)
    assert client.get("/irrigation").json()["age_s"] == 0


@pytest.mark.parametrize("path", ["/sensors", "/prediction", "/irrigation"])
def test_firebase_outage_gives_502(path):
    client, _ = make_client(error=requests.Timeout("trop lent"))
    response = client.get(path)
    assert response.status_code == 502
    assert response.json()["detail"] == "Firebase injoignable."


# ---------------------------------------------------------------- Firestore
def test_daily_history_defaults_to_seven_days():
    store = FakeStore()
    client, _ = make_client(store=store)
    response = client.get("/history/daily")
    assert response.status_code == 200
    assert store.calls == [("daily", 7)]
    assert response.json()[0]["date"] == "2026-10-20"


def test_daily_history_honours_days_parameter():
    store = FakeStore()
    client, _ = make_client(store=store)
    client.get("/history/daily?days=1")
    assert store.calls == [("daily", 1)]
    assert len(client.get("/history/daily?days=1").json()) == 1


@pytest.mark.parametrize("days", [0, -1, 91, "abc"])
def test_daily_history_rejects_invalid_days(days):
    store = FakeStore()
    client, _ = make_client(store=store)
    assert client.get(f"/history/daily?days={days}").status_code == 422
    assert store.calls == []


def test_events_are_serialized_with_iso_dates():
    client, _ = make_client(store=FakeStore())
    event = client.get("/history/events").json()[0]
    assert event["duration_s"] == 300
    assert event["opened_at"].startswith("2026-10-20T08:00:00")


@pytest.mark.parametrize("limit", [0, 201, "x"])
def test_events_reject_invalid_limit(limit):
    client, _ = make_client(store=FakeStore())
    assert client.get(f"/history/events?limit={limit}").status_code == 422


@pytest.mark.parametrize("path", ["/history/daily", "/history/events"])
def test_history_is_503_without_firestore(path):
    client, _ = make_client(store=None)
    response = client.get(path)
    assert response.status_code == 503
    assert "FIRESTORE_CREDENTIALS" in response.json()["detail"]


@pytest.mark.parametrize("path", ["/history/daily", "/history/events"])
def test_firestore_outage_gives_502(path):
    client, _ = make_client(store=FakeStore(fail=True))
    assert client.get(path).status_code == 502


# ---------------------------------------------------------------- lecture seule et documentation
@pytest.mark.parametrize("path", ["/sensors", "/prediction", "/irrigation", "/history/daily", "/history/events"])
@pytest.mark.parametrize("method", ["post", "put", "delete", "patch"])
def test_routes_are_read_only(path, method):
    client, db = make_client(store=FakeStore())
    assert getattr(client, method)(path).status_code == 405
    assert db.reads == []


def test_openapi_lists_every_route():
    client, _ = make_client(store=FakeStore())
    paths = client.get("/openapi.json").json()["paths"]
    assert set(paths) == {
        "/health", "/sensors", "/prediction", "/irrigation", "/history/daily", "/history/events",
    }
    assert all(set(methods) == {"get"} for methods in paths.values())
    assert client.get("/docs").status_code == 200


def test_create_app_requires_database_url(monkeypatch):
    monkeypatch.delenv("FIREBASE_DATABASE_URL", raising=False)
    with pytest.raises(RuntimeError, match="FIREBASE_DATABASE_URL"):
        create_app()
