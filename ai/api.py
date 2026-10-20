#!/usr/bin/env python3
"""API REST en lecture seule du projet d'agriculture intelligente.

Elle expose ce que le serveur IA et l'ESP32 publient dans Firebase, et l'historique
agricole stocké dans Firestore. Elle n'écrit jamais rien et ne commande jamais la
vanne : c'est un processus séparé de server.py, donc une panne de l'API ne touche
pas à l'irrigation.

Lancer (depuis ai/) :
    python -m uvicorn api:create_app --factory --port 8000
    python api.py                      (équivalent, écoute sur 127.0.0.1:8000)
Documentation interactive : http://127.0.0.1:8000/docs

Routes :
    GET /health                       état de l'API, de Firebase et de Firestore
    GET /sensors                      dernière mesure de l'ESP32
    GET /prediction                   prédiction température/humidité + qualité du modèle
    GET /irrigation                   recommandation d'irrigation
    GET /history/daily?days=7         résumés journaliers (Firestore)
    GET /history/events?limit=20      ouvertures de la vanne (Firestore)

Configuration (ai/.env) : FIREBASE_DATABASE_URL, et FIRESTORE_CREDENTIALS pour
l'historique. Sans FIRESTORE_CREDENTIALS, les routes /history/* répondent 503.

Aucune authentification : l'API n'écoute que sur la machine locale par défaut.
Avant de l'exposer sur un réseau, il faut l'authentifier (voir le README, section 7).
"""

import logging
import os
import time
from pathlib import Path
from typing import Annotated

import requests
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import JSONResponse

from irrigation_service import FirebaseRest

load_dotenv(Path(__file__).with_name(".env"))

log = logging.getLogger("api")


def _store_from_env():
    """Crée l'accès Firestore, ou renvoie None s'il n'est pas configuré."""
    path = os.getenv("FIRESTORE_CREDENTIALS")
    if not path:
        log.warning("Historique Firestore indisponible : FIRESTORE_CREDENTIALS manquant.")
        return None
    try:
        from history_store import FirestoreStore

        return FirestoreStore(path)
    except Exception as exc:  # clé absente, firebase-admin manquant...
        log.warning("Historique Firestore indisponible : %s", exc)
        return None


def _age_seconds(updated_at_ms, now: float):
    """Âge d'une donnée dont `updated_at` est un horodatage Firebase en millisecondes."""
    if isinstance(updated_at_ms, bool) or not isinstance(updated_at_ms, (int, float)):
        return None
    return max(0, round(now - updated_at_ms / 1000))


def create_app(db=None, store=None, clock=time.time) -> FastAPI:
    """Construit l'application.

    db    : accès Realtime Database (méthode get(path)) ; FirebaseRest depuis .env par défaut.
    store : accès Firestore (list_daily, list_events) ; None = historique indisponible.
    """
    if db is None:
        url = os.getenv("FIREBASE_DATABASE_URL")
        if not url:
            raise RuntimeError("FIREBASE_DATABASE_URL manquant (fichier ai/.env).")
        db = FirebaseRest(url)
        store = _store_from_env() if store is None else store

    app = FastAPI(
        title="Agriculture intelligente : API en lecture seule",
        description="Mesures, prédictions, recommandation d'irrigation et historique agricole.",
        version="1.0.0",
    )

    @app.exception_handler(requests.RequestException)
    async def firebase_unreachable(request: Request, exc: requests.RequestException):
        log.warning("Firebase injoignable : %s", exc)
        return JSONResponse({"detail": "Firebase injoignable."}, status_code=502)

    def read_node(path: str):
        return db.get(path)

    # ------------------------------------------------------------------
    @app.get("/health")
    def health():
        """État de l'API. Répond 503 si la Realtime Database est injoignable."""
        try:
            read_node("/valve/mode")
            firebase_ok = True
        except Exception as exc:
            log.warning("Contrôle de santé : %s", exc)
            firebase_ok = False
        body = {
            "status": "ok" if firebase_ok else "degraded",
            "firebase": firebase_ok,
            "firestore": store is not None,
        }
        return JSONResponse(body, status_code=200 if firebase_ok else 503)

    @app.get("/sensors")
    def sensors():
        """Dernière mesure : température, humidité, humidité du sol, pH, luminosité."""
        data = read_node("/sensors")
        if not data:
            raise HTTPException(404, "Aucune mesure disponible.")
        return data

    @app.get("/prediction")
    def prediction():
        """Prédiction de la prochaine mesure température/humidité, avec la qualité du modèle."""
        data = read_node("/ai/prediction")
        if not data:
            raise HTTPException(404, "Aucune prédiction disponible (serveur IA arrêté ?).")
        return {
            **data,
            "age_s": _age_seconds(data.get("updated_at"), clock()),
            "status": read_node("/ai/status"),
        }

    @app.get("/irrigation")
    def irrigation():
        """Recommandation d'irrigation : besoin, scores, action de la vanne et raison."""
        data = read_node("/ai/irrigation")
        if not data:
            raise HTTPException(404, "Aucune recommandation disponible (serveur IA arrêté ?).")
        return {**data, "age_s": _age_seconds(data.get("updated_at"), clock())}

    # ------------------------------------------------------------------
    def history_store():
        if store is None:
            raise HTTPException(503, "Historique Firestore non configuré (FIRESTORE_CREDENTIALS).")
        return store

    @app.get("/history/daily")
    def history_daily(days: Annotated[int, Query(ge=1, le=90, description="Nombre de jours")] = 7):
        """Résumés journaliers, du plus récent au plus ancien."""
        source = history_store()
        try:
            return source.list_daily(days)
        except Exception as exc:
            log.warning("Firestore : %s", exc)
            raise HTTPException(502, "Firestore injoignable.")

    @app.get("/history/events")
    def history_events(limit: Annotated[int, Query(ge=1, le=200, description="Nombre d'événements")] = 20):
        """Dernières ouvertures de la vanne, de la plus récente à la plus ancienne."""
        source = history_store()
        try:
            return source.list_events(limit)
        except Exception as exc:
            log.warning("Firestore : %s", exc)
            raise HTTPException(502, "Firestore injoignable.")

    return app


def main() -> int:
    import uvicorn

    logging.basicConfig(level=logging.INFO, format="%(asctime)s  %(message)s", datefmt="%H:%M:%S")
    host = os.getenv("API_HOST", "127.0.0.1")
    port = int(os.getenv("API_PORT", "8000"))
    uvicorn.run("api:create_app", factory=True, host=host, port=port)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
