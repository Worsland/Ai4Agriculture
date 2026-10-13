"""Modèle final de besoin d'irrigation : validation croisée puis entraînement complet.

Étapes :
    1. Réduction à 6 variables (retenues après exploration et ablation).
    2. Validation croisée stratifiée (5 plis par défaut) de 3 algorithmes.
    3. Choix du meilleur (balanced accuracy moyenne), puis entraînement sur
       toutes les données.
    4. Sauvegarde dans models/irrigation_final.joblib avec les métadonnées
       nécessaires à la prédiction (variables, classes, plages de bornage,
       modalités autorisées).

Usage (depuis le dossier ai/) :
    python train_final.py --sample 200000      # essai rapide
    python train_final.py                      # jeu complet (plusieurs minutes)
    python train_final.py --model Arbre_decision   # forcer un algorithme

Nécessite train_irrigation.py dans le même dossier.
"""

import argparse
from datetime import datetime
from pathlib import Path

import joblib
import pandas as pd
import sklearn
from sklearn.metrics import make_scorer, recall_score
from sklearn.model_selection import StratifiedKFold, cross_validate
from sklearn.pipeline import Pipeline

from train_irrigation import CLASSES, SEED, TARGET, build_models, make_preprocessor

FEATURES = [
    "Soil_Moisture",
    "Temperature_C",
    "Rainfall_mm",
    "Wind_Speed_kmh",
    "Crop_Growth_Stage",
    "Mulching_Used",
]
CANDIDATES = ["Arbre_decision", "Random_Forest", "Gradient_Boosting"]

REPORT = []


def out(text=""):
    print(text)
    REPORT.append(str(text))


def title(text):
    out()
    out("=" * 70)
    out(text)
    out("=" * 70)


def cross_validate_models(X, y, folds):
    scoring = {
        "balanced_acc": "balanced_accuracy",
        "f1_macro": "f1_macro",
        "recall_High": make_scorer(recall_score, labels=["High"], average="macro"),
    }
    cv = StratifiedKFold(n_splits=folds, shuffle=True, random_state=SEED)
    rows = []
    for name, kind, est in build_models():
        if name not in CANDIDATES:
            continue
        pipe = Pipeline([("prep", make_preprocessor(X, kind)), ("model", est)])
        res = cross_validate(pipe, X, y, cv=cv, scoring=scoring, n_jobs=1)
        row = {"modele": name}
        for key in scoring:
            scores = res[f"test_{key}"]
            row[f"{key}_moy"] = scores.mean()
            row[f"{key}_std"] = scores.std()
        row["temps_pli_s"] = res["fit_time"].mean()
        rows.append(row)
        out(
            f"  {name:<20} bal_acc={row['balanced_acc_moy']:.4f} +/- {row['balanced_acc_std']:.4f}  "
            f"f1_macro={row['f1_macro_moy']:.4f}  recall_High={row['recall_High_moy']:.4f}  "
            f"({row['temps_pli_s']:.0f}s/pli)"
        )
    return pd.DataFrame(rows)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--path", default="data/train.csv")
    parser.add_argument("--sample", type=int, default=0, help="taille d'échantillon (0 = tout)")
    parser.add_argument("--folds", type=int, default=5)
    parser.add_argument("--model", choices=CANDIDATES, help="forcer l'algorithme final")
    args = parser.parse_args()

    outdir = Path("reports")
    outdir.mkdir(exist_ok=True)
    models_dir = Path("models")
    models_dir.mkdir(exist_ok=True)

    df = pd.read_csv(args.path)
    if args.sample and args.sample < len(df):
        df = df.sample(args.sample, random_state=SEED).reset_index(drop=True)
        out(f"(Échantillon aléatoire de {args.sample} lignes)")

    X, y = df[FEATURES], df[TARGET]
    out(f"Variables ({len(FEATURES)}) : {', '.join(FEATURES)}")
    out(f"Observations : {len(df)}")

    title(f"1. Validation croisée ({args.folds} plis)")
    results = cross_validate_models(X, y, args.folds)
    results.to_csv(outdir / "final_cv_results.csv", index=False)

    title("2. Choix du modèle")
    ranked = results.sort_values("balanced_acc_moy", ascending=False).reset_index(drop=True)
    best_row = ranked.iloc[0]
    close = ranked[
        ranked["balanced_acc_moy"] >= best_row["balanced_acc_moy"] - best_row["balanced_acc_std"]
    ]["modele"].tolist()
    out(f"Meilleure balanced accuracy moyenne : {best_row['modele']} "
        f"({best_row['balanced_acc_moy']:.4f})")
    out(f"Modèles à moins d'un écart-type du meilleur : {', '.join(close)}")
    if len(close) > 1:
        out("-> Écart non significatif : à départager sur la simplicité ou la rapidité.")

    chosen = args.model or best_row["modele"]
    out(f"Modèle retenu pour l'entraînement final : {chosen}"
        + (" (forcé)" if args.model else ""))

    title("3. Entraînement final sur toutes les données")
    kind, est = next((k, e) for n, k, e in build_models() if n == chosen)
    final = Pipeline([("prep", make_preprocessor(X, kind)), ("model", est)])
    final.fit(X, y)

    num = X.select_dtypes(include="number").columns
    cat = [c for c in X.columns if c not in num]
    chosen_row = results[results["modele"] == chosen].iloc[0]
    bundle = {
        "pipeline": final,
        "model_name": chosen,
        "features": FEATURES,
        "classes": CLASSES,
        "clip_ranges": {c: [float(X[c].min()), float(X[c].max())] for c in num},
        "categories": {c: sorted(X[c].unique().tolist()) for c in cat},
        "cv": {
            "folds": args.folds,
            "balanced_acc": float(chosen_row["balanced_acc_moy"]),
            "balanced_acc_std": float(chosen_row["balanced_acc_std"]),
            "f1_macro": float(chosen_row["f1_macro_moy"]),
            "recall_High": float(chosen_row["recall_High_moy"]),
        },
        "trained_on_rows": int(len(df)),
        "trained_at": datetime.now().isoformat(timespec="seconds"),
        "sklearn_version": sklearn.__version__,
    }
    path = models_dir / "irrigation_final.joblib"
    joblib.dump(bundle, path)

    out(f"Modèle sauvegardé : {path}")
    out("Plages de bornage :")
    for c, (lo, hi) in bundle["clip_ranges"].items():
        out(f"  {c:<16} [{lo:.2f}, {hi:.2f}]")
    out("Modalités autorisées :")
    for c, vals in bundle["categories"].items():
        out(f"  {c:<18} {vals}")

    (outdir / "final_model.txt").write_text("\n".join(REPORT), encoding="utf-8")
    print(f"\nRapport enregistré : {outdir / 'final_model.txt'}")


if __name__ == "__main__":
    main()
