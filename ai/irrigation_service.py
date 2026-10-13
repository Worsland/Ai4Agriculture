"""Service d'irrigation : relie Firebase, le modèle et le contrôleur de vanne.

À chaque cycle (appelé par server.py) :
    1. lit /valve/mode, /sensors, /weather, /field et /valve/state ;
    2. demande au modèle le besoin d'irrigation ;
    3. en mode "auto" : demande une décision au contrôleur et écrit
       /valve/command ; en mode "manual" (ou mode absent) : n'écrit rien
       sur la vanne ;
    4. publie le résultat dans /ai/irrigation pour le tableau de bord.

Nœuds Firebase utilisés :
    /valve/mode              "auto" ou "manual"              (tableau de bord)
    /sensors                 soil_moisture, temperature, ... (ESP32)
    /weather                 rainfall (mm), wind (km/h)      (tableau de bord)
    /field                   growth_stage, mulching          (tableau de bord)
    /valve/state             open (bool), angle              (ESP32)
    /valve/command           true = ouvrir, false = fermer   (écrit ici en auto)
    /ai/irrigation           need, probabilities, action, reason, ...

Fraîcheur des mesures : l'ESP32 écrit une entrée dans /history chaque minute.
Le service surveille la signature de la dernière entrée (fournie par
server.py). Tant qu'aucun changement n'a été observé, ou si la signature ne
change plus depuis plus de 5 minutes, les mesures sont jugées trop anciennes
et le contrôleur ferme la vanne.

Accès à Firebase : requêtes REST sans jeton, ce qui suppose des règles de base
ouvertes (cas actuel du TP). Avec des règles restreintes, ajouter l'authentification
dans FirebaseRest._params().
"""

from __future__ import annotations

import logging
import time

import requests

from valve_controller import ValveController

log = logging.getLogger("irrigation")

INF = float("inf")


class FirebaseRest:
    """Accès minimal à la Realtime Database par l'API REST."""

    def __init__(self, base_url, timeout=10, session=None):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.session = session or requests.Session()

    def _url(self, path):
        return f"{self.base_url}/{path.strip('/')}.json"

    def _params(self):
        return {}  # point d'extension pour une authentification

    def get(self, path):
        resp = self.session.get(self._url(path), params=self._params(), timeout=self.timeout)
        resp.raise_for_status()
        return resp.json()

    def put(self, path, value):
        resp = self.session.put(
            self._url(path), params=self._params(), json=value, timeout=self.timeout
        )
        resp.raise_for_status()
        return resp.json()


class FreshnessTracker:
    """Estime l'âge des mesures à partir de la signature de la dernière entrée de /history.

    L'âge est infini tant qu'aucun changement de signature n'a été observé :
    après un démarrage du serveur, on ne fait pas confiance à des mesures
    peut-être anciennes avant d'avoir vu arriver une nouvelle entrée.
    """

    def __init__(self):
        self.seen = False
        self.signature = None
        self.last_change = None

    def update(self, signature, now):
        if signature is None:  # lecture de /history impossible ou vide : on ignore
            return
        if not self.seen:
            self.seen = True
            self.signature = signature
            return
        if signature != self.signature:
            self.signature = signature
            self.last_change = now

    def age(self, now):
        return INF if self.last_change is None else now - self.last_change


class IrrigationService:
    def __init__(self, db, model, controller=None, clock=time.time):
        self.db = db
        self.model = model
        self.controller = controller or ValveController()
        self.clock = clock
        self.fresh = FreshnessTracker()

    # ------------------------------------------------------------------
    def _read_inputs(self):
        sensors = self.db.get("/sensors") or {}
        weather = self.db.get("/weather") or {}
        field = self.db.get("/field") or {}
        return {
            "soil_moisture": sensors.get("soil_moisture"),
            "temperature": sensors.get("temperature"),
            "rainfall": weather.get("rainfall"),
            "wind": weather.get("wind"),
            "growth_stage": field.get("growth_stage"),
            "mulching": field.get("mulching"),
        }

    def step(self, history_signature):
        """Exécute un cycle et renvoie la charge publiée dans /ai/irrigation."""
        now = self.clock()
        self.fresh.update(history_signature, now)

        mode = self.db.get("/valve/mode")
        auto = mode == "auto"
        state = self.db.get("/valve/state") or {}
        measures = self._read_inputs()

        need, probabilities, clipped, error = None, None, None, None
        try:
            result = self.model.predict(measures)
            need = result["need"]
            probabilities = result["probabilities"]
            clipped = result["clipped"] or None
        except ValueError as exc:
            error = str(exc)

        decision = None
        if auto:
            actual_open = state.get("open")
            if isinstance(actual_open, bool):
                self.controller.sync(actual_open, now)
            decision = self.controller.decide(now, need, self.fresh.age(now))
            self.db.put("/valve/command", decision.command)
        else:
            self.controller.reset()

        payload = {
            "need": need,
            "probabilities": probabilities,
            "clipped": clipped,
            "error": error,
            "mode": "auto" if auto else "manual",
            "action": decision.action if decision else "manual",
            "reason": decision.reason if decision else "mode manuel : aucune commande automatique",
            "command": decision.command if decision else None,
            "inputs": {k: v for k, v in measures.items() if v is not None},
            "updated_at": int(now * 1000),
        }
        self.db.put("/ai/irrigation", payload)
        log.info(
            "Irrigation : mode=%s besoin=%s action=%s (%s)",
            payload["mode"], need, payload["action"], payload["reason"],
        )
        return payload
