"""Décision automatique de la vanne à partir du besoin d'irrigation prédit.

Règles (mode automatique) :
    Low      -> vanne fermée
    Medium   -> ouverture courte (5 min par défaut), puis réévaluation
    High     -> ouverture tant que le besoin reste High ; fermeture dès qu'il
                redescend à Medium ou Low

Garde-fous :
    - durée maximale d'ouverture continue (15 min par défaut) ;
    - délai minimal entre deux ouvertures (10 min par défaut), pour éviter
      que la vanne ne s'ouvre et ne se ferme sans arrêt ;
    - sécurité : sans décision fiable du modèle (valeur manquante, erreur) ou
      avec des mesures trop anciennes (5 min par défaut), la vanne est fermée.

Ce module ne dépend ni de Firebase ni du modèle : il reçoit le besoin prédit
et l'heure, et renvoie une décision. Le serveur se charge de lire et d'écrire
dans Firebase.

Utilisation dans le serveur (une fois par cycle, par exemple chaque minute) :

    controller = ValveController()
    controller.sync(actual_open=etat_reel_vanne, now=time.time())
    decision = controller.decide(now=time.time(), need=besoin, data_age_s=age)
    if decision.changed:
        ecrire_commande_vanne(decision.command)

En mode manuel, le serveur ne doit pas appeler decide() et doit appeler
controller.reset() pour repartir d'un état propre au retour en automatique.

Démonstration : python valve_controller.py
"""

import math
from dataclasses import dataclass

NEEDS = ("Low", "Medium", "High")


@dataclass
class ValveConfig:
    medium_open_s: float = 300      # ouverture courte pour Medium
    max_open_s: float = 900         # durée maximale d'ouverture continue
    min_closed_s: float = 600       # délai minimal entre deux ouvertures
    stale_after_s: float = 300      # âge maximal des mesures


@dataclass
class Decision:
    command: bool   # True = ouvrir / rester ouverte, False = fermer / rester fermée
    action: str     # "open", "close", "keep_open" ou "keep_closed"
    reason: str

    @property
    def changed(self):
        """True si la commande de la vanne doit être modifiée."""
        return self.action in ("open", "close")


class ValveController:
    def __init__(self, config=None):
        self.config = config or ValveConfig()
        self.reset()

    def reset(self):
        self.is_open = False
        self.opened_at = None
        self.closed_at = None
        self.kind = None  # "Medium" ou "High" : raison de l'ouverture en cours

    # ------------------------------------------------------------------
    def sync(self, actual_open, now):
        """Aligne l'état interne sur l'état réel confirmé par l'ESP32.

        Cas utiles : redémarrage du serveur pendant que la vanne est ouverte,
        ou ouverture/fermeture faite en dehors du contrôleur.
        """
        if actual_open and not self.is_open:
            self.is_open = True
            self.opened_at = now
            self.kind = "Medium"  # reprise prudente : traitée comme une ouverture courte
        elif not actual_open and self.is_open:
            self.is_open = False
            self.closed_at = now
            self.kind = None

    def decide(self, now, need, data_age_s=0.0):
        cfg = self.config
        if need not in NEEDS:
            return self._fail_safe(now, "pas de décision fiable du modèle")
        if data_age_s is not None and data_age_s > cfg.stale_after_s:
            if math.isinf(data_age_s):
                why = "mesures trop anciennes ou pas encore confirmées (aucune nouvelle entrée observée)"
            else:
                why = f"mesures trop anciennes ({data_age_s:.0f} s)"
            return self._fail_safe(now, why)
        if self.is_open:
            return self._while_open(now, need)
        return self._while_closed(now, need)

    # ------------------------------------------------------------------
    def _while_open(self, now, need):
        cfg = self.config
        elapsed = now - self.opened_at

        if elapsed >= cfg.max_open_s:
            return self._close(now, "durée maximale d'ouverture atteinte")

        if self.kind == "High":
            if need != "High":
                return self._close(now, f"besoin redescendu à {need}")
            return Decision(True, "keep_open", "besoin élevé persistant")

        # Ouverture courte (Medium)
        if need == "High":
            self.kind = "High"
            return Decision(True, "keep_open", "besoin passé à High")
        if need == "Low":
            return self._close(now, "besoin satisfait")
        if elapsed >= cfg.medium_open_s:
            return self._close(now, "ouverture courte terminée")
        return Decision(True, "keep_open", "ouverture courte en cours")

    def _while_closed(self, now, need):
        cfg = self.config
        if need == "Low":
            return Decision(False, "keep_closed", "pas de besoin")
        if self.closed_at is not None:
            wait = cfg.min_closed_s - (now - self.closed_at)
            if wait > 0:
                return Decision(
                    False,
                    "keep_closed",
                    f"délai minimal entre deux ouvertures ({wait:.0f} s restantes)",
                )
        self.is_open = True
        self.opened_at = now
        self.kind = need
        return Decision(True, "open", f"besoin {need}")

    def _close(self, now, reason):
        self.is_open = False
        self.closed_at = now
        self.kind = None
        return Decision(False, "close", reason)

    def _fail_safe(self, now, reason):
        if self.is_open:
            return self._close(now, f"sécurité : {reason}")
        return Decision(False, "keep_closed", f"sécurité : {reason}")


# ----------------------------------------------------------------------
def _simulate(title, needs, step_s=60, ages=None):
    """Affiche les changements de la vanne pour une suite de besoins (1 par minute)."""
    print(f"\n{title}")
    controller = ValveController()
    for i, need in enumerate(needs):
        now = i * step_s
        age = ages[i] if ages else 0.0
        d = controller.decide(now, need, age)
        if d.changed:
            print(f"  t={now // 60:>3} min  besoin={need!s:<7} -> {d.action:<5} ({d.reason})")


if __name__ == "__main__":
    _simulate("Besoin Medium permanent pendant 40 min", ["Medium"] * 40)
    _simulate("Besoin High permanent pendant 40 min", ["High"] * 40)
    _simulate(
        "High pendant 6 min, puis Medium (le sol a réagi), puis Low",
        ["High"] * 6 + ["Medium"] * 4 + ["Low"] * 4,
    )
    _simulate(
        "Modèle indisponible à t=3 min pendant que la vanne est ouverte",
        ["High"] * 3 + [None] * 3 + ["High"] * 3,
    )
    _simulate(
        "Mesures trop anciennes à partir de t=2 min",
        ["High"] * 5,
        ages=[0, 0, 400, 400, 400],
    )
