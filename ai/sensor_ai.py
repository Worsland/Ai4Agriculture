#!/usr/bin/env python3
"""Module IA : lit /history sur Firebase, entraîne un modèle, écrit /ai/prediction.

Usage unique :   python sensor_ai.py [--demo]
En continu :     python server.py   (voir server.py)
"""
from __future__ import annotations

import argparse
import json
import math
import os
import sys
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import joblib
import numpy as np
import requests
from dotenv import load_dotenv
from sklearn.ensemble import RandomForestRegressor

load_dotenv(Path(__file__).with_name(".env"))

MODEL_PATH = Path(__file__).with_name("sensor_model.joblib")
MIN_SAMPLES = 20      # en dessous, pas d'entraînement
HISTORY_LIMIT = 500   # nombre de mesures récupérées (~8 h à 1 mesure/min)


@dataclass
class Sample:
    t: datetime | None
    temp: float
    hum: float


# ---------- Lecture des données ----------
def to_float(v: Any) -> float | None:
    try:
        f = float(v)
        return None if math.isnan(f) else f
    except (TypeError, ValueError):
        return None


def to_datetime(v: Any) -> datetime | None:
    """Accepte millisecondes (ESP32/Firebase), secondes ou texte ISO."""
    if isinstance(v, (int, float)):
        seconds = v / 1000 if v > 1e11 else v
        return datetime.fromtimestamp(seconds, tz=timezone.utc) if seconds > 1e9 else None
    if isinstance(v, str):
        try:
            d = datetime.fromisoformat(v.replace("Z", "+00:00"))
            return d if d.tzinfo else d.replace(tzinfo=timezone.utc)
        except ValueError:
            return None
    return None


def parse_history(raw: Any) -> list[Sample]:
    items = raw.values() if isinstance(raw, dict) else raw if isinstance(raw, list) else []
    samples: list[Sample] = []
    for e in items:
        if not isinstance(e, dict):
            continue
        temp, hum = to_float(e.get("temperature")), to_float(e.get("humidity"))
        if temp is None or hum is None:
            continue
        samples.append(Sample(to_datetime(e.get("timestamp")), temp, hum))
    if samples and all(s.t for s in samples):
        samples.sort(key=lambda s: s.t)  # type: ignore[arg-type,return-value]
    return samples


def demo_history(n: int = 120) -> list[Sample]:
    now = datetime.now(timezone.utc)
    return [
        Sample(
            now - timedelta(minutes=n - i),
            round(22.5 + math.sin(i / 8) * 2.0 + (i % 3) * 0.1, 1),
            round(58.0 + math.cos(i / 10) * 4.0 + (i % 2) * 0.4, 1),
        )
        for i in range(n)
    ]


def fetch_history(db_url: str, api_key: str | None, limit: int = HISTORY_LIMIT) -> list[Sample]:
    """Ne récupère que les `limit` dernières mesures (clés push = ordre chronologique)."""
    params: dict[str, Any] = {"orderBy": '"$key"', "limitToLast": limit}
    if api_key:
        params["auth"] = api_key
    r = requests.get(db_url.rstrip("/") + "/history.json", params=params, timeout=15)
    r.raise_for_status()
    return parse_history(r.json())


# ---------- Modèle ----------
def _features(s: list[Sample], i: int) -> list[float]:
    cur, prev = s[i], s[i - 1]
    minutes = cur.t.hour * 60 + cur.t.minute if cur.t else 0
    angle = 2 * math.pi * minutes / 1440
    return [math.sin(angle), math.cos(angle), cur.temp, cur.hum, cur.temp - prev.temp, cur.hum - prev.hum]


def _dataset(s: list[Sample]) -> tuple[np.ndarray, np.ndarray]:
    idx = range(1, len(s) - 1)
    X = np.array([_features(s, i) for i in idx])
    # Cible = variation jusqu'à la mesure SUIVANTE (et non la valeur actuelle)
    y = np.array([[s[i + 1].temp - s[i].temp, s[i + 1].hum - s[i].hum] for i in idx])
    return X, y


def _new_model() -> RandomForestRegressor:
    return RandomForestRegressor(n_estimators=150, min_samples_leaf=2, random_state=42)


def train_and_predict(samples: list[Sample]) -> dict[str, Any]:
    if len(samples) < MIN_SAMPLES:
        raise ValueError(f"Pas assez de mesures ({len(samples)}/{MIN_SAMPLES}).")
    X, y = _dataset(samples)

    mae = baseline = None
    if len(X) >= 30:  # validation sur les 20 % de mesures les plus récentes
        cut = int(len(X) * 0.8)
        err = np.abs(_new_model().fit(X[:cut], y[:cut]).predict(X[cut:]) - y[cut:]).mean(axis=0)
        base = np.abs(y[cut:]).mean(axis=0)  # référence : "la valeur ne change pas"
        mae = {"temperature": round(float(err[0]), 3), "humidity": round(float(err[1]), 3)}
        baseline = {"temperature": round(float(base[0]), 3), "humidity": round(float(base[1]), 3)}

    model = _new_model().fit(X, y)
    joblib.dump(model, MODEL_PATH)

    delta = model.predict(np.array([_features(samples, len(samples) - 1)]))[0]
    last = samples[-1]
    return {
        "prediction": {
            "temperature": round(last.temp + float(delta[0]), 1),
            "humidity": round(last.hum + float(delta[1]), 1),
        },
        "samples": len(samples),
        "mae": mae,
        "baseline_mae": baseline,
    }


# ---------- Écriture Firebase ----------
def write_results(result: dict[str, Any], db_url: str, api_key: str | None) -> None:
    base = db_url.rstrip("/")
    params = {"auth": api_key} if api_key else None
    pred = {**result["prediction"], "updated_at": {".sv": "timestamp"}}
    status = {k: result[k] for k in ("samples", "mae", "baseline_mae")}
    for path, body in (("/ai/prediction.json", pred), ("/ai/status.json", status)):
        requests.put(base + path, params=params, json=body, timeout=15).raise_for_status()


def main() -> int:
    p = argparse.ArgumentParser(description="Entraîne le modèle une fois et envoie la prédiction.")
    p.add_argument("--demo", action="store_true", help="Données fictives, aucune écriture Firebase.")
    p.add_argument("--database-url", default=os.getenv("FIREBASE_DATABASE_URL"))
    p.add_argument("--api-key", default=os.getenv("FIREBASE_API_KEY"))
    a = p.parse_args()

    try:
        if a.demo:
            samples = demo_history()
        elif not a.database_url:
            print("FIREBASE_DATABASE_URL manquant (fichier ai/.env).", file=sys.stderr)
            return 1
        else:
            samples = fetch_history(a.database_url, a.api_key)
        result = train_and_predict(samples)
        if not a.demo:
            write_results(result, a.database_url, a.api_key)
    except Exception as exc:
        print(f"Erreur : {exc}", file=sys.stderr)
        return 1

    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())