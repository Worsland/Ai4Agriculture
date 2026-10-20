#!/usr/bin/env python3
"""Serveur IA : tourne en continu, met à jour /ai/prediction et pilote la vanne.

Boucle : lire /history -> s'il y a une nouvelle mesure -> entraîner -> écrire la prédiction,
puis (si le modèle d'irrigation est disponible) décider de l'irrigation et écrire
/ai/irrigation, ainsi que /valve/command en mode automatique.

Lancer :  python server.py            (toutes les 60 s)
          python server.py --interval 30
          python server.py --no-irrigation   (prédiction température/humidité seule)
          python server.py --no-history      (sans historique Firestore)
          python server.py --history-flush 60   (résumé Firestore toutes les 60 s, pour tester)
Arrêter : Ctrl+C

Le modèle d'irrigation vient de models/irrigation_final.joblib (voir train_final.py).
S'il est absent, le serveur continue sans la partie irrigation.

L'historique agricole (événements de vanne, résumés journaliers) est écrit dans
Firestore par history_store.py. Il faut FIRESTORE_CREDENTIALS dans ai/.env (clé de
compte de service) ; sans elle, le serveur continue sans historique.
"""
from __future__ import annotations

import argparse
import logging
import os
import time

import sensor_ai as ai
from irrigation_service import FirebaseRest

logging.basicConfig(level=logging.INFO, format="%(asctime)s  %(message)s", datefmt="%H:%M:%S")
log = logging.getLogger("ai-server")


def build_irrigation_service(db):
    """Crée le service d'irrigation, ou renvoie None s'il ne peut pas démarrer."""
    try:
        from irrigation_model import IrrigationModel
        from irrigation_service import IrrigationService

        service = IrrigationService(db, IrrigationModel.load())
        log.info("Décision d'irrigation activée.")
        return service
    except Exception as exc:  # modèle absent, version de scikit-learn différente...
        log.warning("Décision d'irrigation désactivée : %s", exc)
        return None


def build_history_recorder(db, credentials_path: str | None, flush_every: float):
    """Crée l'enregistreur Firestore, ou renvoie None s'il ne peut pas démarrer."""
    if not credentials_path:
        log.warning("Historique Firestore désactivé : FIRESTORE_CREDENTIALS manquant (fichier ai/.env).")
        return None
    try:
        from history_store import FirestoreStore, HistoryRecorder

        recorder = HistoryRecorder(db, FirestoreStore(credentials_path), flush_every=flush_every)
        log.info("Historique Firestore activé (résumé toutes les %s s).", flush_every)
        return recorder
    except Exception as exc:  # clé absente, firebase-admin manquant...
        log.warning("Historique Firestore désactivé : %s", exc)
        return None


def main() -> int:
    p = argparse.ArgumentParser(description="Serveur IA relié à Firebase.")
    p.add_argument("--interval", type=int, default=60, help="Secondes entre deux vérifications.")
    p.add_argument("--database-url", default=os.getenv("FIREBASE_DATABASE_URL"))
    p.add_argument("--api-key", default=os.getenv("FIREBASE_API_KEY"))
    p.add_argument("--no-irrigation", action="store_true",
                   help="Désactive la décision d'irrigation et la commande de la vanne.")
    p.add_argument("--firestore-credentials", default=os.getenv("FIRESTORE_CREDENTIALS"),
                   help="Clé de compte de service Firestore (chemin relatif à ai/).")
    p.add_argument("--history-flush", type=int, default=600,
                   help="Secondes entre deux écritures du résumé journalier dans Firestore.")
    p.add_argument("--no-history", action="store_true",
                   help="Désactive l'historique Firestore.")
    a = p.parse_args()
    if not a.database_url:
        log.error("FIREBASE_DATABASE_URL manquant (fichier ai/.env).")
        return 1

    db = FirebaseRest(a.database_url)
    irrigation = None if a.no_irrigation else build_irrigation_service(db)
    history = None if a.no_history else build_history_recorder(
        db, a.firestore_credentials, a.history_flush)

    last_seen = None  # dernière mesure déjà utilisée
    log.info("Serveur démarré (vérification toutes les %s s). Ctrl+C pour arrêter.", a.interval)
    try:
        while True:
            newest = None  # signature de la dernière entrée de /history (None si illisible)
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

            # Irrigation : bloc séparé, une erreur ici ne bloque pas la prédiction ci-dessus.
            irrigation_payload = None
            if irrigation is not None:
                try:
                    irrigation_payload = irrigation.step(newest)
                except Exception as exc:
                    log.warning("Irrigation : %s", exc)

            # Historique : autre bloc séparé, une panne de Firestore ne bloque rien.
            if history is not None:
                try:
                    history.step(newest, irrigation_payload)
                except Exception as exc:
                    log.warning("Historique : %s", exc)

            time.sleep(a.interval)
    except KeyboardInterrupt:
        if history is not None:
            history.flush(force=True)  # écrit ce qui est encore en attente
        log.info("Arrêt du serveur.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())