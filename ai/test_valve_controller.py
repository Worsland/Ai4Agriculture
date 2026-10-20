"""Tests de la logique de décision de la vanne.

Lancer depuis ai/ :
    python -m pip install pytest
    python -m pytest test_valve_controller.py -v
"""

from valve_controller import ValveConfig, ValveController

MIN = 60  # secondes


def run(controller, needs, start=0, step=MIN, ages=None):
    """Applique une suite de besoins (1 par pas) et renvoie la liste des décisions."""
    decisions = []
    for i, need in enumerate(needs):
        age = ages[i] if ages else 0.0
        decisions.append(controller.decide(start + i * step, need, age))
    return decisions


def commands(decisions):
    return [d.command for d in decisions]


def test_low_keeps_valve_closed():
    decisions = run(ValveController(), ["Low"] * 30)
    assert not any(d.command for d in decisions)
    assert not any(d.changed for d in decisions)


def test_medium_opens_then_closes_after_short_opening():
    decisions = run(ValveController(), ["Medium"] * 6)
    assert decisions[0].action == "open"
    assert all(d.command for d in decisions[:5])      # minutes 0 à 4 : ouverte
    assert decisions[5].action == "close"             # minute 5 : fermée
    assert decisions[5].reason == "ouverture courte terminée"


def test_medium_waits_minimum_delay_then_reopens():
    decisions = run(ValveController(), ["Medium"] * 20)
    # Fermée à t=5 min, délai de 10 min : pas de réouverture avant t=15 min
    assert not any(d.command for d in decisions[5:15])
    assert decisions[15].action == "open"


def test_high_stays_open_until_need_drops_to_medium():
    needs = ["High"] * 6 + ["Medium"]
    decisions = run(ValveController(), needs)
    assert all(d.command for d in decisions[:6])
    assert decisions[6].action == "close"
    assert "Medium" in decisions[6].reason


def test_high_to_low_closes():
    decisions = run(ValveController(), ["High", "High", "Low"])
    assert decisions[2].action == "close"


def test_max_open_duration_closes_valve_even_if_high_persists():
    decisions = run(ValveController(), ["High"] * 20)
    assert decisions[0].action == "open"
    assert all(d.command for d in decisions[:15])
    assert decisions[15].action == "close"
    assert decisions[15].reason == "durée maximale d'ouverture atteinte"


def test_medium_upgraded_to_high_stays_open_beyond_short_opening():
    needs = ["Medium"] * 3 + ["High"] * 6
    decisions = run(ValveController(), needs)
    # Au-delà de 5 min, la vanne reste ouverte car le besoin est passé à High
    assert all(d.command for d in decisions)


def test_no_decision_from_model_closes_open_valve_and_keeps_closed():
    controller = ValveController()
    decisions = run(controller, ["High", "High", None, "High"])
    assert decisions[2].action == "close"
    assert decisions[2].reason.startswith("sécurité")
    # Le délai minimal empêche une réouverture immédiate
    assert decisions[3].command is False


def test_none_when_closed_keeps_closed():
    d = ValveController().decide(0, None)
    assert d.command is False and d.action == "keep_closed"


def test_unknown_need_value_is_treated_as_no_decision():
    d = ValveController().decide(0, "Urgent")
    assert d.command is False


def test_stale_data_closes_open_valve():
    controller = ValveController()
    run(controller, ["High", "High"])
    d = controller.decide(2 * MIN, "High", data_age_s=400)
    assert d.action == "close"
    assert "trop anciennes" in d.reason


def test_stale_data_prevents_opening():
    d = ValveController().decide(0, "High", data_age_s=400)
    assert d.command is False


def test_sync_adopts_open_valve_after_restart():
    controller = ValveController()
    controller.sync(actual_open=True, now=0)
    assert controller.is_open
    # Traitée comme une ouverture courte : fermée après 5 min si besoin Medium
    d = controller.decide(5 * MIN, "Medium")
    assert d.action == "close"


def test_sync_detects_external_closing():
    controller = ValveController()
    run(controller, ["High", "High"])
    controller.sync(actual_open=False, now=2 * MIN)
    assert not controller.is_open
    # Le délai minimal s'applique à partir de cette fermeture
    assert controller.decide(3 * MIN, "High").command is False


def test_reset_clears_state():
    controller = ValveController()
    run(controller, ["High"] * 3)
    controller.reset()
    assert controller.decide(0, "High").action == "open"


def test_custom_config_is_respected():
    cfg = ValveConfig(medium_open_s=120, max_open_s=300, min_closed_s=60)
    decisions = run(ValveController(cfg), ["Medium"] * 5)
    assert decisions[0].action == "open"
    assert decisions[2].action == "close"   # 2 min
    assert decisions[3].command is True     # 3 min : délai de 1 min écoulé -> rouvre
