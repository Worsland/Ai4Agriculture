#!/usr/bin/env python3
"""Serveur d'entraînement IA : tourne en continu et met à jour /ai/prediction.

Boucle : lire /history -> s'il y a une nouvelle mesure -> entraîner -> écrire la prédiction.
Lancer :  python server.py            (toutes les 60 s)
          python server.py --interval 30
Arrêter : Ctrl+C
"""
from __future__ import annotations

import argparse
import logging
import os
import time

import sensor_ai as ai

logging.basicConfig(level=logging.INFO, format="%(asctime)s  %(message)s", datefmt="%H:%M:%S")
log = logging.getLogger("ai-server")


def main() -> int:
    p = argparse.ArgumentParser(description="Serveur d'entraînement IA relié à Firebase.")
    p.add_argument("--interval", type=int, default=60, help="Secondes entre deux vérifications.")
    p.add_argument("--database-url", default=os.getenv("FIREBASE_DATABASE_URL"))
    p.add_argument("--api-key", default=os.getenv("FIREBASE_API_KEY"))
    a = p.parse_args()
    if not a.database_url:
        log.error("FIREBASE_DATABASE_URL manquant (fichier ai/.env).")
        return 1

    last_seen = None  # dernière mesure déjà utilisée
    log.info("Serveur démarré (vérification toutes les %s s). Ctrl+C pour arrêter.", a.interval)
    try:
        while True:
            try:
                samples = ai.fetch_history(a.database_url, a.api_key)
                newest = (samples[-1].t, samples[-1].temp, samples[-1].hum) if samples else None
                if not samples:
                    log.info("Historique vide, en attente de mesures.")
                elif newest == last_seen:
                    log.info("Pas de nouvelle mesure.")
                else:
                    result = ai.train_and_predict(samples)
                    ai.write_results(result, a.database_url, a.api_key)
                    last_seen = newest
                    log.info("Prédiction envoyée : %s (sur %s mesures, erreur moyenne %s)",
                             result["prediction"], result["samples"], result["mae"])
            except ValueError as exc:      # pas assez de données : normal au début
                log.info("%s", exc)
            except Exception as exc:       # réseau, Firebase... on réessaie au prochain tour
                log.warning("Erreur : %s", exc)
            time.sleep(a.interval)
    except KeyboardInterrupt:
        log.info("Arrêt du serveur.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())