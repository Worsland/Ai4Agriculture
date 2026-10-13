"""Prédiction du besoin d'irrigation à partir du modèle final.

Utilisation dans le serveur :

    from irrigation_model import IrrigationModel

    model = IrrigationModel.load()          # models/irrigation_final.joblib
    result = model.predict({
        "soil_moisture": 18.0,              # capteur ESP32
        "temperature": 34.5,                # capteur ESP32
        "rainfall": 300.0,                  # météo simulée
        "wind": 15.0,                       # météo simulée
        "growth_stage": "Flowering",        # réglage du tableau de bord
        "mulching": False,                  # réglage du tableau de bord
    })
    result["need"]          # "Low", "Medium" ou "High"

Comportement de sécurité :
    - une valeur manquante, non numérique ou une modalité inconnue lève
      une ValueError : le serveur ne doit alors PAS commander la vanne ;
    - les valeurs numériques hors de la plage d'entraînement sont ramenées
      aux bornes, et la liste des valeurs modifiées est renvoyée.

Remarque : le modèle est entraîné avec des poids de classes équilibrés.
Les probabilités renvoyées servent à comparer les classes entre elles ;
ce ne sont pas des probabilités calibrées.

Test rapide : python irrigation_model.py
"""

import math
from pathlib import Path

import joblib
import pandas as pd

DEFAULT_PATH = Path(__file__).resolve().parent / "models" / "irrigation_final.joblib"

# Noms utilisés par le projet (Firebase / tableau de bord) -> noms du jeu de données
ALIASES = {
    "soil_moisture": "Soil_Moisture",
    "temperature": "Temperature_C",
    "rainfall": "Rainfall_mm",
    "wind": "Wind_Speed_kmh",
    "growth_stage": "Crop_Growth_Stage",
    "mulching": "Mulching_Used",
}


class IrrigationModel:
    def __init__(self, bundle):
        self.bundle = bundle
        self.pipeline = bundle["pipeline"]
        self.features = bundle["features"]
        self.classes = bundle["classes"]
        self.clip_ranges = bundle["clip_ranges"]
        self.categories = bundle["categories"]

    @classmethod
    def load(cls, path=DEFAULT_PATH):
        path = Path(path)
        if not path.exists():
            raise FileNotFoundError(
                f"Modèle introuvable : {path}. Lancer d'abord train_final.py."
            )
        return cls(joblib.load(path))

    # ------------------------------------------------------------------
    def _normalize(self, measures):
        """Renomme les clés, convertit les types et valide les entrées."""
        data = {ALIASES.get(k, k): v for k, v in measures.items()}

        missing = [f for f in self.features if data.get(f) is None]
        if missing:
            raise ValueError(f"Valeurs manquantes : {', '.join(missing)}")

        row, clipped = {}, {}
        for feat in self.features:
            value = data[feat]
            if feat in self.clip_ranges:
                try:
                    value = float(value)
                except (TypeError, ValueError):
                    raise ValueError(f"{feat} doit être numérique (reçu : {value!r})")
                if math.isnan(value) or math.isinf(value):
                    raise ValueError(f"{feat} invalide (reçu : {value})")
                lo, hi = self.clip_ranges[feat]
                used = min(max(value, lo), hi)
                if used != value:
                    clipped[feat] = {"recu": value, "utilise": used}
                row[feat] = used
            else:
                row[feat] = self._normalize_category(feat, value)
        return row, clipped

    def _normalize_category(self, feat, value):
        if isinstance(value, bool):
            value = "Yes" if value else "No"
        text = str(value).strip()
        allowed = self.categories[feat]
        for option in allowed:
            if option.lower() == text.lower():
                return option
        raise ValueError(f"{feat} : valeur inconnue {value!r} (autorisées : {allowed})")

    # ------------------------------------------------------------------
    def predict(self, measures):
        """Renvoie {"need", "probabilities", "clipped", "model"}."""
        row, clipped = self._normalize(measures)
        X = pd.DataFrame([row], columns=self.features)
        need = str(self.pipeline.predict(X)[0])
        probs = self.pipeline.predict_proba(X)[0]
        class_order = list(self.pipeline.classes_)
        probabilities = {c: round(float(probs[class_order.index(c)]), 4) for c in self.classes}
        return {
            "need": need,
            "probabilities": probabilities,
            "clipped": clipped,
            "model": self.bundle["model_name"],
        }


if __name__ == "__main__":
    model = IrrigationModel.load()
    cv = model.bundle["cv"]
    print(
        f"Modèle : {model.bundle['model_name']} | validation croisée : "
        f"balanced accuracy {cv['balanced_acc']:.3f} +/- {cv['balanced_acc_std']:.3f}"
    )

    examples = {
        "Sol sec, chaud, peu de pluie": {
            "soil_moisture": 12, "temperature": 38, "rainfall": 200, "wind": 18,
            "growth_stage": "Flowering", "mulching": False,
        },
        "Sol humide, frais, pluvieux": {
            "soil_moisture": 60, "temperature": 18, "rainfall": 2000, "wind": 3,
            "growth_stage": "Sowing", "mulching": True,
        },
        "Capteurs hors plage (potentiomètre à 95 %, 55 °C)": {
            "soil_moisture": 95, "temperature": 55, "rainfall": 1000, "wind": 10,
            "growth_stage": "Vegetative", "mulching": "No",
        },
        "Donnée manquante": {
            "soil_moisture": 30, "temperature": 25, "rainfall": 800, "wind": 8,
            "growth_stage": "Harvest",
        },
    }
    for label, measures in examples.items():
        print(f"\n{label}")
        try:
            result = model.predict(measures)
            print(f"  besoin = {result['need']}  probabilités = {result['probabilities']}")
            if result["clipped"]:
                print(f"  valeurs bornées : {result['clipped']}")
        except ValueError as err:
            print(f"  refusé (pas de décision) : {err}")
