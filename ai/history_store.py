"""Historique agricole dans Firestore.

Deux collections, alimentées par le serveur (jamais par l'ESP32) :

    irrigation_events/{id auto}   une ouverture de vanne terminée
        day, opened_at, closed_at, duration_s, mode, need, reason, approximate
    daily_summaries/{AAAA-MM-JJ}  résumé d'une journée (heure locale du serveur)
        date, samples, sensors{temperature|humidity|soil_moisture|ph|light:
        n, sum, min, max, avg}, valve_open_s, irrigation_count, updated_at

Lecture : FirestoreStore.list_daily / list_events servent à l'API (api.py).

Principes :
- On n'écrit pas à chaque cycle : un événement à la fermeture de la vanne, et un
  résumé fusionné toutes les `flush_every` secondes (10 min par défaut), pour
  rester loin des quotas du plan gratuit.
- Une mesure n'est comptée que si /history a reçu une nouvelle entrée : si la
  simulation est arrêtée, les anciennes valeurs de /sensors ne faussent pas les stats.
- Une panne de Firestore ne bloque jamais le serveur : les données restent en
  attente et sont renvoyées au cycle suivant.
- La résolution temporelle est celle du cycle du serveur (60 s par défaut) :
  les durées d'ouverture sont exactes à un cycle près.

La classe FirestoreStore est la seule à dépendre de firebase-admin ; le reste se
teste avec un faux magasin (voir test_history_store.py).
"""

from __future__ import annotations

import logging
import math
import time
from datetime import datetime, timezone
from pathlib import Path

log = logging.getLogger("history")

EVENTS_COLLECTION = "irrigation_events"
DAILY_COLLECTION = "daily_summaries"
SENSOR_FIELDS = ("temperature", "humidity", "soil_moisture", "ph", "light")
MAX_QUEUED_EVENTS = 200


def day_id(ts: float) -> str:
    """Identifiant du jour en heure locale du serveur, ex. '2026-10-20'."""
    return datetime.fromtimestamp(ts).strftime("%Y-%m-%d")


def _utc(ts: float) -> datetime:
    return datetime.fromtimestamp(ts, tz=timezone.utc)


def _number(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value) if math.isfinite(value) else None


# ---------------------------------------------------------------- résumés journaliers
def empty_delta() -> dict:
    return {"samples": 0, "sensors": {}, "valve_open_s": 0.0, "irrigation_count": 0}


def add_sample(delta: dict, sensors: dict) -> None:
    """Ajoute une lecture de /sensors au cumul en attente (valeurs invalides ignorées)."""
    delta["samples"] += 1
    for name in SENSOR_FIELDS:
        value = _number(sensors.get(name))
        if value is None:
            continue
        stat = delta["sensors"].setdefault(name, {"n": 0, "sum": 0.0, "min": value, "max": value})
        stat["n"] += 1
        stat["sum"] += value
        stat["min"] = min(stat["min"], value)
        stat["max"] = max(stat["max"], value)


def merge_daily(existing: dict | None, delta: dict) -> dict:
    """Fusionne le cumul en attente dans le résumé déjà stocké pour ce jour."""
    existing = existing or {}
    old = existing.get("sensors") or {}
    sensors = {}
    for name in set(old) | set(delta["sensors"]):
        parts = [p for p in (old.get(name), delta["sensors"].get(name)) if p and p.get("n")]
        if not parts:
            continue
        n = sum(p["n"] for p in parts)
        total = sum(p["sum"] for p in parts)
        sensors[name] = {
            "n": n,
            "sum": round(total, 3),
            "min": min(p["min"] for p in parts),
            "max": max(p["max"] for p in parts),
            "avg": round(total / n, 3),
        }
    return {
        "samples": existing.get("samples", 0) + delta["samples"],
        "sensors": sensors,
        "valve_open_s": round(existing.get("valve_open_s", 0) + delta["valve_open_s"], 1),
        "irrigation_count": existing.get("irrigation_count", 0) + delta["irrigation_count"],
    }


# ---------------------------------------------------------------- événements de vanne
class ValveEventTracker:
    """Détecte les ouvertures de vanne terminées à partir de /valve/state."""

    def __init__(self):
        self.started = False
        self.open_since = None
        self.context = {}
        self.approximate = False

    def update(self, is_open, now: float, context: dict | None = None) -> dict | None:
        """Renvoie l'événement quand la vanne vient de se fermer, sinon None."""
        if not isinstance(is_open, bool):  # état absent ou illisible : on ne conclut rien
            return None
        first = not self.started
        self.started = True
        if is_open and self.open_since is None:
            self.open_since = now
            self.context = dict(context or {})
            # Vanne déjà ouverte au démarrage du serveur : l'heure d'ouverture est inconnue.
            self.approximate = first
            return None
        if not is_open and self.open_since is not None:
            event = {
                "day": day_id(now),
                "opened_at": _utc(self.open_since),
                "closed_at": _utc(now),
                "duration_s": round(now - self.open_since),
                "approximate": self.approximate,
                **self.context,
            }
            self.open_since = None
            self.context = {}
            return event
        return None


# ---------------------------------------------------------------- enregistreur
class HistoryRecorder:
    """Appelé à chaque cycle par server.py : lit Firebase, alimente Firestore."""

    def __init__(self, db, store, clock=time.time, flush_every: float = 600):
        self.db = db            # FirebaseRest (Realtime Database)
        self.store = store      # FirestoreStore, ou faux magasin dans les tests
        self.clock = clock
        self.flush_every = flush_every
        self.tracker = ValveEventTracker()
        self.pending: dict[str, dict] = {}   # jour -> cumul pas encore écrit
        self.events_out: list[dict] = []     # événements pas encore écrits
        self.seen = False
        self.signature = None
        self.last_flush = clock()

    def step(self, signature, irrigation: dict | None = None) -> None:
        now = self.clock()
        # Lectures d'abord : si Firebase est injoignable, l'état interne reste intact.
        sensors = self.db.get("/sensors") or {}
        state = self.db.get("/valve/state") or {}
        mode = (irrigation or {}).get("mode") or ("auto" if self.db.get("/valve/mode") == "auto" else "manual")

        context = {
            "mode": mode,
            "need": (irrigation or {}).get("need"),
            "reason": (irrigation or {}).get("reason"),
        }
        event = self.tracker.update(state.get("open"), now, context)
        if event:
            self._queue_event(event, now)

        if signature is not None:
            if not self.seen:
                self.seen = True  # première observation : fraîcheur inconnue, on ne compte pas
                self.signature = signature
            elif signature != self.signature:
                self.signature = signature
                add_sample(self._pending_for(now), sensors)

        self.flush(now)

    def _pending_for(self, now: float) -> dict:
        return self.pending.setdefault(day_id(now), empty_delta())

    def _queue_event(self, event: dict, now: float) -> None:
        self.events_out.append(event)
        del self.events_out[:-MAX_QUEUED_EVENTS]
        delta = self._pending_for(now)
        delta["valve_open_s"] += event["duration_s"]
        delta["irrigation_count"] += 1

    def flush(self, now: float | None = None, force: bool = False) -> None:
        """Écrit les événements, puis les résumés si l'échéance est atteinte."""
        now = self.clock() if now is None else now
        for event in list(self.events_out):
            try:
                self.store.add_event(event)
                self.events_out.remove(event)
            except Exception as exc:
                log.warning("Événement non écrit (nouvel essai au prochain cycle) : %s", exc)
                break

        today = day_id(now)
        due = force or now - self.last_flush >= self.flush_every or any(d != today for d in self.pending)
        if not due or not self.pending:
            return
        for day in sorted(self.pending):
            try:
                merged = merge_daily(self.store.get_daily(day), self.pending[day])
                merged["date"] = day
                self.store.set_daily(day, merged)
                del self.pending[day]
                log.info("Résumé %s écrit dans Firestore (%s mesures).", day, merged["samples"])
            except Exception as exc:
                log.warning("Résumé %s non écrit (nouvel essai plus tard) : %s", day, exc)
        self.last_flush = now


# ---------------------------------------------------------------- Firestore
class FirestoreStore:
    """Accès à Firestore par firebase-admin (compte de service, contourne les règles)."""

    def __init__(self, credentials_path: str):
        import firebase_admin
        from firebase_admin import credentials, firestore

        path = Path(credentials_path)
        if not path.is_absolute():
            path = Path(__file__).resolve().parent / path  # relatif au dossier ai/
        if not path.is_file():
            raise FileNotFoundError(f"clé de compte de service introuvable : {path}")
        try:
            firebase_admin.get_app()
        except ValueError:
            firebase_admin.initialize_app(credentials.Certificate(str(path)))
        self._firestore = firestore
        self._db = firestore.client()

    def add_event(self, event: dict) -> None:
        self._db.collection(EVENTS_COLLECTION).add(event)

    def get_daily(self, day: str) -> dict | None:
        snap = self._db.collection(DAILY_COLLECTION).document(day).get()
        return snap.to_dict() if snap.exists else None

    def set_daily(self, day: str, data: dict) -> None:
        data = {**data, "updated_at": self._firestore.SERVER_TIMESTAMP}
        self._db.collection(DAILY_COLLECTION).document(day).set(data)

    # Lecture (utilisée par l'API : api.py)
    def list_daily(self, days: int) -> list[dict]:
        """Les `days` derniers résumés journaliers, du plus récent au plus ancien."""
        query = (self._db.collection(DAILY_COLLECTION)
                 .order_by("date", direction=self._firestore.Query.DESCENDING).limit(days))
        return [snap.to_dict() for snap in query.stream()]

    def list_events(self, limit: int) -> list[dict]:
        """Les `limit` dernières ouvertures de vanne, de la plus récente à la plus ancienne."""
        query = (self._db.collection(EVENTS_COLLECTION)
                 .order_by("opened_at", direction=self._firestore.Query.DESCENDING).limit(limit))
        return [{"id": snap.id, **snap.to_dict()} for snap in query.stream()]
