"""Tests du module de prédiction température/humidité (sensor_ai.py).

Aucun accès réseau : les appels HTTP à Firebase sont remplacés par de faux objets,
et le modèle entraîné est écrit dans un dossier temporaire (pas dans ai/).

Lancer depuis ai/ :
    python -m pytest test_sensor_ai.py -v
"""

import math
from datetime import datetime, timedelta, timezone

import pytest

import sensor_ai as ai


# ---------------------------------------------------------------- conversions
@pytest.mark.parametrize("value, expected", [
    (21.5, 21.5), ("21.5", 21.5), (3, 3.0), (True, 1.0),
])
def test_to_float_accepts_numbers_and_numeric_strings(value, expected):
    assert ai.to_float(value) == expected


@pytest.mark.parametrize("value", [None, "abc", "", [], {}, float("nan")])
def test_to_float_rejects_invalid_values(value):
    assert ai.to_float(value) is None


def test_to_datetime_reads_milliseconds_and_seconds():
    ms = 1_760_950_000_000
    expected = datetime.fromtimestamp(ms / 1000, tz=timezone.utc)
    assert ai.to_datetime(ms) == expected
    assert ai.to_datetime(ms // 1000) == expected


def test_to_datetime_reads_iso_text_with_and_without_timezone():
    z = ai.to_datetime("2026-10-20T10:00:00Z")
    naive = ai.to_datetime("2026-10-20T10:00:00")
    assert z == datetime(2026, 10, 20, 10, tzinfo=timezone.utc)
    assert naive == z  # sans fuseau : considéré comme UTC


@pytest.mark.parametrize("value", [None, "hier", 5, 0, [], {}])
def test_to_datetime_rejects_invalid_values(value):
    assert ai.to_datetime(value) is None


# ---------------------------------------------------------------- lecture de /history
def entry(temp, hum, ts=None):
    e = {"temperature": temp, "humidity": hum}
    if ts is not None:
        e["timestamp"] = ts
    return e


def test_parse_history_accepts_firebase_dict_and_list():
    as_dict = {"-Nabc": entry(20, 50), "-Nabd": entry(21, 51)}
    as_list = [entry(20, 50), entry(21, 51)]
    assert [(s.temp, s.hum) for s in ai.parse_history(as_dict)] == [(20.0, 50.0), (21.0, 51.0)]
    assert len(ai.parse_history(as_list)) == 2


@pytest.mark.parametrize("raw", [None, "texte", 42, {}, []])
def test_parse_history_returns_empty_for_unusable_input(raw):
    assert ai.parse_history(raw) == []


def test_parse_history_skips_invalid_entries():
    raw = [
        entry(20, 50),
        "pas un dictionnaire",
        {"temperature": 20},               # humidité absente
        entry("abc", 50),                  # valeur non numérique
        entry(float("nan"), 50),
        entry(22, 52),
    ]
    assert [s.temp for s in ai.parse_history(raw)] == [20.0, 22.0]


def test_parse_history_sorts_by_timestamp_when_all_are_dated():
    t0 = 1_760_950_000_000
    raw = [entry(3, 30, t0 + 120_000), entry(1, 10, t0), entry(2, 20, t0 + 60_000)]
    assert [s.temp for s in ai.parse_history(raw)] == [1.0, 2.0, 3.0]


def test_parse_history_keeps_order_when_some_timestamps_are_missing():
    raw = [entry(3, 30, 1_760_950_120_000), entry(1, 10), entry(2, 20, 1_760_950_060_000)]
    assert [s.temp for s in ai.parse_history(raw)] == [3.0, 1.0, 2.0]


def test_fetch_history_asks_for_the_last_entries_only(monkeypatch):
    seen = {}

    class Resp:
        def raise_for_status(self):
            pass

        def json(self):
            return {"-N1": entry(20, 50), "-N2": entry(21, 51)}

    def fake_get(url, params=None, timeout=None):
        seen.update(url=url, params=params, timeout=timeout)
        return Resp()

    monkeypatch.setattr(ai.requests, "get", fake_get)
    samples = ai.fetch_history("https://exemple.firebaseio.com/", "CLE", limit=42)
    assert seen["url"] == "https://exemple.firebaseio.com/history.json"
    assert seen["params"] == {"orderBy": '"$key"', "limitToLast": 42, "auth": "CLE"}
    assert len(samples) == 2


def test_fetch_history_omits_auth_without_api_key(monkeypatch):
    seen = {}

    class Resp:
        def raise_for_status(self):
            pass

        def json(self):
            return None

    monkeypatch.setattr(ai.requests, "get", lambda url, params=None, timeout=None: seen.update(params=params) or Resp())
    assert ai.fetch_history("https://exemple.firebaseio.com", None) == []
    assert "auth" not in seen["params"]


# ---------------------------------------------------------------- entraînement
@pytest.fixture(autouse=True)
def isolated_model_file(tmp_path, monkeypatch):
    """Le modèle entraîné est écrit dans un dossier temporaire, jamais dans ai/."""
    monkeypatch.setattr(ai, "MODEL_PATH", tmp_path / "sensor_model.joblib")


def test_demo_history_has_requested_length_and_increasing_dates():
    samples = ai.demo_history(50)
    assert len(samples) == 50
    assert all(a.t < b.t for a, b in zip(samples, samples[1:]))


def test_training_refuses_too_few_samples():
    with pytest.raises(ValueError, match="Pas assez de mesures"):
        ai.train_and_predict(ai.demo_history(ai.MIN_SAMPLES - 1))


def test_training_returns_prediction_close_to_last_measure():
    samples = ai.demo_history(120)
    result = ai.train_and_predict(samples)
    last = samples[-1]
    assert result["samples"] == 120
    assert abs(result["prediction"]["temperature"] - last.temp) < 2
    assert abs(result["prediction"]["humidity"] - last.hum) < 3
    assert all(math.isfinite(v) for v in result["prediction"].values())


def test_training_saves_the_model_file():
    ai.train_and_predict(ai.demo_history(60))
    assert ai.MODEL_PATH.exists()


def test_error_is_evaluated_against_the_naive_baseline_with_enough_data():
    result = ai.train_and_predict(ai.demo_history(120))
    assert set(result["mae"]) == {"temperature", "humidity"}
    assert set(result["baseline_mae"]) == {"temperature", "humidity"}
    assert all(v >= 0 for v in result["mae"].values())


def test_no_evaluation_with_only_the_minimum_of_samples():
    # 20 mesures -> 18 exemples d'entraînement, sous le seuil de 30 pour évaluer
    result = ai.train_and_predict(ai.demo_history(ai.MIN_SAMPLES))
    assert result["mae"] is None and result["baseline_mae"] is None


def test_training_works_without_timestamps():
    samples = [ai.Sample(None, 20 + (i % 5) * 0.2, 50 + (i % 3) * 0.5) for i in range(40)]
    result = ai.train_and_predict(samples)
    assert math.isfinite(result["prediction"]["temperature"])


def test_features_encode_time_of_day_cyclically():
    midnight = ai.Sample(datetime(2026, 10, 20, 0, 0, tzinfo=timezone.utc), 20, 50)
    noon = ai.Sample(datetime(2026, 10, 20, 12, 0, tzinfo=timezone.utc), 20, 50)
    f0 = ai._features([midnight, midnight], 1)
    f12 = ai._features([noon, noon], 1)
    assert f0[:2] == pytest.approx([0.0, 1.0])
    assert f12[:2] == pytest.approx([0.0, -1.0], abs=1e-9)


def test_dataset_target_is_the_change_to_the_next_measure():
    base = datetime(2026, 10, 20, tzinfo=timezone.utc)
    samples = [ai.Sample(base + timedelta(minutes=i), 20.0 + i, 50.0 - i) for i in range(5)]
    X, y = ai._dataset(samples)
    assert len(X) == len(y) == 3
    assert y.tolist() == [[1.0, -1.0]] * 3


# ---------------------------------------------------------------- écriture dans Firebase
RESULT = {
    "prediction": {"temperature": 23.1, "humidity": 55.2},
    "samples": 120,
    "mae": {"temperature": 0.1, "humidity": 0.2},
    "baseline_mae": {"temperature": 0.2, "humidity": 0.3},
}


class _Put:
    def __init__(self):
        self.calls = []

    def __call__(self, url, params=None, json=None, timeout=None):
        self.calls.append((url, params, json))

        class Resp:
            def raise_for_status(self):
                pass

        return Resp()


def test_write_results_updates_prediction_and_status(monkeypatch):
    put = _Put()
    monkeypatch.setattr(ai.requests, "put", put)
    ai.write_results(RESULT, "https://exemple.firebaseio.com/", "CLE")
    urls = [c[0] for c in put.calls]
    assert urls == [
        "https://exemple.firebaseio.com/ai/prediction.json",
        "https://exemple.firebaseio.com/ai/status.json",
    ]
    prediction, status = put.calls[0][2], put.calls[1][2]
    assert prediction["temperature"] == 23.1
    assert prediction["updated_at"] == {".sv": "timestamp"}  # horodatage posé par Firebase
    assert set(status) == {"samples", "mae", "baseline_mae"}
    assert put.calls[0][1] == {"auth": "CLE"}


def test_write_results_without_api_key_sends_no_auth(monkeypatch):
    put = _Put()
    monkeypatch.setattr(ai.requests, "put", put)
    ai.write_results(RESULT, "https://exemple.firebaseio.com", None)
    assert all(c[1] is None for c in put.calls)