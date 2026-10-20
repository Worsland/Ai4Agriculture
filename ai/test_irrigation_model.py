"""Tests du module de prédiction d'irrigation (irrigation_model.py).

Deux niveaux :
- Logique d'entrée/sortie (renommage, bornage, validation) : testée avec un petit
  modèle entraîné à la volée sur des données synthétiques. Aucun fichier requis,
  donc ces tests passent aussi sur une machine sans models/irrigation_final.joblib
  (intégration continue).
- Cohérence du vrai modèle final : lancée seulement si models/irrigation_final.joblib
  existe (voir train_final.py), sinon ignorée.

Lancer depuis ai/ :
    python -m pytest test_irrigation_model.py -v
"""

import math

import joblib
import numpy as np
import pandas as pd
import pytest
from sklearn.compose import ColumnTransformer
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder
from sklearn.tree import DecisionTreeClassifier

from irrigation_model import DEFAULT_PATH, IrrigationModel

FEATURES = [
    "Soil_Moisture", "Temperature_C", "Rainfall_mm", "Wind_Speed_kmh",
    "Crop_Growth_Stage", "Mulching_Used",
]
CLIP = {
    "Soil_Moisture": (8.0, 65.0), "Temperature_C": (12.0, 42.0),
    "Rainfall_mm": (0.0, 2500.0), "Wind_Speed_kmh": (1.0, 20.0),
}
CATEGORIES = {
    "Crop_Growth_Stage": ["Sowing", "Vegetative", "Flowering", "Harvest"],
    "Mulching_Used": ["No", "Yes"],
}
CLASSES = ["Low", "Medium", "High"]

GOOD = {
    "soil_moisture": 30, "temperature": 25, "rainfall": 800, "wind": 8,
    "growth_stage": "Vegetative", "mulching": False,
}


def make_bundle():
    """Petit modèle à arbre, entraîné sur une règle simple : sol sec -> High, humide -> Low."""
    rng = np.random.default_rng(0)
    n = 600
    X = pd.DataFrame({
        "Soil_Moisture": rng.uniform(8, 65, n),
        "Temperature_C": rng.uniform(12, 42, n),
        "Rainfall_mm": rng.uniform(0, 2500, n),
        "Wind_Speed_kmh": rng.uniform(1, 20, n),
        "Crop_Growth_Stage": rng.choice(CATEGORIES["Crop_Growth_Stage"], n),
        "Mulching_Used": rng.choice(CATEGORIES["Mulching_Used"], n),
    })[FEATURES]
    y = np.where(X["Soil_Moisture"] < 20, "High", np.where(X["Soil_Moisture"] < 40, "Medium", "Low"))
    pre = ColumnTransformer(
        [("cat", OneHotEncoder(handle_unknown="ignore"), list(CATEGORIES))],
        remainder="passthrough",
    )
    pipe = Pipeline([("pre", pre), ("clf", DecisionTreeClassifier(max_depth=4, random_state=0))])
    pipe.fit(X, y)
    return {
        "pipeline": pipe, "features": FEATURES, "classes": CLASSES,
        "clip_ranges": CLIP, "categories": CATEGORIES, "model_name": "arbre-test",
        "cv": {"balanced_acc": 0.9, "balanced_acc_std": 0.01},
    }


@pytest.fixture(scope="module")
def model():
    return IrrigationModel(make_bundle())


# ---------------------------------------------------------------- sortie
def test_predict_returns_need_probabilities_and_model_name(model):
    result = model.predict(GOOD)
    assert result["need"] in CLASSES
    assert set(result["probabilities"]) == set(CLASSES)
    assert sum(result["probabilities"].values()) == pytest.approx(1.0, abs=1e-3)
    assert result["clipped"] == {}
    assert result["model"] == "arbre-test"


def test_dry_soil_needs_more_water_than_wet_soil(model):
    dry = model.predict({**GOOD, "soil_moisture": 10})
    wet = model.predict({**GOOD, "soil_moisture": 60})
    assert dry["need"] == "High"
    assert wet["need"] == "Low"


# ---------------------------------------------------------------- bornage
def test_out_of_range_values_are_clipped_and_reported(model):
    result = model.predict({**GOOD, "soil_moisture": 95, "temperature": 55})
    assert result["clipped"] == {
        "Soil_Moisture": {"recu": 95.0, "utilise": 65.0},
        "Temperature_C": {"recu": 55.0, "utilise": 42.0},
    }


def test_clipped_value_gives_same_prediction_as_the_bound(model):
    at_bound = model.predict({**GOOD, "soil_moisture": 65})
    beyond = model.predict({**GOOD, "soil_moisture": 500})
    assert beyond["need"] == at_bound["need"]
    assert beyond["probabilities"] == at_bound["probabilities"]


def test_value_below_lower_bound_is_raised_to_it(model):
    row, clipped = model._normalize({**GOOD, "soil_moisture": -20})
    assert row["Soil_Moisture"] == 8.0
    assert clipped["Soil_Moisture"]["recu"] == -20.0


def test_numeric_strings_are_accepted(model):
    row, clipped = model._normalize({**GOOD, "soil_moisture": "30.5"})
    assert row["Soil_Moisture"] == 30.5 and clipped == {}


# ---------------------------------------------------------------- noms de variables
def test_project_names_and_dataset_names_are_equivalent(model):
    project = model._normalize(GOOD)[0]
    dataset = model._normalize({
        "Soil_Moisture": 30, "Temperature_C": 25, "Rainfall_mm": 800,
        "Wind_Speed_kmh": 8, "Crop_Growth_Stage": "Vegetative", "Mulching_Used": "No",
    })[0]
    assert project == dataset


def test_extra_keys_are_ignored(model):
    assert model.predict({**GOOD, "ph": 6.8, "light": 70})["need"] in CLASSES


# ---------------------------------------------------------------- catégories
@pytest.mark.parametrize("value, expected", [
    (True, "Yes"), (False, "No"), ("yes", "Yes"), ("NO", "No"), (" Yes ", "Yes"),
])
def test_mulching_is_normalized(model, value, expected):
    assert model._normalize({**GOOD, "mulching": value})[0]["Mulching_Used"] == expected


def test_growth_stage_is_case_insensitive(model):
    assert model._normalize({**GOOD, "growth_stage": "flowering"})[0]["Crop_Growth_Stage"] == "Flowering"


def test_unknown_growth_stage_is_rejected(model):
    with pytest.raises(ValueError, match="valeur inconnue"):
        model.predict({**GOOD, "growth_stage": "Hiver"})


# ---------------------------------------------------------------- refus de décider
@pytest.mark.parametrize("key", list(GOOD))
def test_missing_key_is_rejected(model, key):
    measures = {k: v for k, v in GOOD.items() if k != key}
    with pytest.raises(ValueError, match="manquantes"):
        model.predict(measures)


def test_none_value_counts_as_missing_and_all_missing_are_listed(model):
    with pytest.raises(ValueError) as err:
        model.predict({**GOOD, "rainfall": None, "wind": None})
    assert "Rainfall_mm" in str(err.value) and "Wind_Speed_kmh" in str(err.value)


def test_false_mulching_is_a_value_not_a_missing_one(model):
    assert model.predict({**GOOD, "mulching": False})["need"] in CLASSES


@pytest.mark.parametrize("bad", ["abc", [], {}, float("nan"), math.inf, -math.inf])
def test_non_numeric_or_non_finite_values_are_rejected(model, bad):
    with pytest.raises(ValueError):
        model.predict({**GOOD, "soil_moisture": bad})


# ---------------------------------------------------------------- chargement
def test_load_missing_file_explains_how_to_train(tmp_path):
    with pytest.raises(FileNotFoundError, match="train_final.py"):
        IrrigationModel.load(tmp_path / "absent.joblib")


def test_load_roundtrip(tmp_path):
    path = tmp_path / "m.joblib"
    joblib.dump(make_bundle(), path)
    loaded = IrrigationModel.load(path)
    assert loaded.predict(GOOD)["model"] == "arbre-test"


# ---------------------------------------------------------------- vrai modèle (optionnel)
real_model = pytest.mark.skipif(
    not DEFAULT_PATH.exists(), reason="models/irrigation_final.joblib absent (lancer train_final.py)"
)

DRY_HOT = {"soil_moisture": 12, "temperature": 38, "rainfall": 200, "wind": 18,
           "growth_stage": "Flowering", "mulching": False}
WET_COOL = {"soil_moisture": 60, "temperature": 18, "rainfall": 2000, "wind": 3,
            "growth_stage": "Sowing", "mulching": True}


@pytest.fixture(scope="module")
def final_model():
    return IrrigationModel.load()


@real_model
def test_final_model_metadata(final_model):
    assert set(final_model.classes) == set(CLASSES)
    assert len(final_model.features) == 6
    assert final_model.bundle["cv"]["balanced_acc"] > 0.9


@real_model
def test_final_model_probabilities_are_valid(final_model):
    for measures in (DRY_HOT, WET_COOL):
        result = final_model.predict(measures)
        assert result["need"] in CLASSES
        assert sum(result["probabilities"].values()) == pytest.approx(1.0, abs=1e-2)


@real_model
def test_final_model_is_directionally_sensible(final_model):
    dry = final_model.predict(DRY_HOT)["probabilities"]
    wet = final_model.predict(WET_COOL)["probabilities"]
    assert dry["Low"] < wet["Low"]
    assert dry["High"] > wet["High"]


@real_model
def test_final_model_handles_simulator_out_of_range_values(final_model):
    result = final_model.predict({**DRY_HOT, "soil_moisture": 95, "temperature": 55})
    assert result["need"] in CLASSES
    assert set(result["clipped"]) >= {"Soil_Moisture", "Temperature_C"}