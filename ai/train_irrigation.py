"""Comparaison des modèles de besoin d'irrigation (Kaggle Playground S6E4).

Compare 3 jeux de variables x 4 algorithmes, puis fait une ablation
(retrait d'une variable à la fois) pour les modèles A et B.

Jeux de variables :
    A    capteurs seuls (mesurés par l'ESP32)
    B    capteurs + contexte (pluie, vent, stade de croissance, paillage)
    ALL  toutes les variables (référence)

Usage (depuis le dossier ai/) :
    python train_irrigation.py --sample 200000     # premier essai, plus rapide
    python train_irrigation.py                      # jeu complet (630 000 lignes)
    python train_irrigation.py --no-save            # sans sauvegarde des modèles

Produit :
    reports/model_comparison.csv / .txt   résultats
    reports/confusion_*.png               matrices de confusion (si matplotlib)
    models/irrigation_<jeu>.joblib        meilleur modèle de chaque jeu
"""

import argparse
import time
from pathlib import Path

import joblib
import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.ensemble import HistGradientBoostingClassifier, RandomForestClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import (
    accuracy_score,
    balanced_accuracy_score,
    confusion_matrix,
    f1_score,
    recall_score,
)
from sklearn.model_selection import train_test_split
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, OrdinalEncoder, StandardScaler
from sklearn.tree import DecisionTreeClassifier

TARGET = "Irrigation_Need"
CLASSES = ["Low", "Medium", "High"]
SEED = 42

SENSORS = ["Soil_Moisture", "Temperature_C", "Humidity", "Soil_pH"]
CONTEXT = ["Rainfall_mm", "Wind_Speed_kmh", "Crop_Growth_Stage", "Mulching_Used"]

FEATURE_SETS = {
    "A": SENSORS,
    "B": SENSORS + CONTEXT,
    "ALL": None,  # toutes les colonnes sauf id et la cible
}

REPORT = []


def out(text=""):
    print(text)
    REPORT.append(str(text))


def make_preprocessor(X, kind):
    """kind = 'linear' (standardisation + one-hot) ou 'tree' (codage ordinal)."""
    num = X.select_dtypes(include="number").columns.tolist()
    cat = [c for c in X.columns if c not in num]
    if kind == "linear":
        cat_enc = OneHotEncoder(handle_unknown="ignore")
        num_enc = StandardScaler()
    else:
        cat_enc = OrdinalEncoder(handle_unknown="use_encoded_value", unknown_value=-1)
        num_enc = "passthrough"
    return ColumnTransformer([("num", num_enc, num), ("cat", cat_enc, cat)])


def build_models():
    """(nom, type de prétraitement, estimateur)"""
    return [
        (
            "Regression_logistique",
            "linear",
            LogisticRegression(max_iter=300, class_weight="balanced"),
        ),
        (
            "Arbre_decision",
            "tree",
            DecisionTreeClassifier(
                max_depth=12,
                min_samples_leaf=20,
                class_weight="balanced",
                random_state=SEED,
            ),
        ),
        (
            "Random_Forest",
            "tree",
            RandomForestClassifier(
                n_estimators=150,
                min_samples_leaf=5,
                class_weight="balanced_subsample",
                n_jobs=-1,
                random_state=SEED,
            ),
        ),
        (
            "Gradient_Boosting",
            "tree",
            HistGradientBoostingClassifier(
                max_iter=300,
                learning_rate=0.1,
                class_weight="balanced",
                random_state=SEED,
            ),
        ),
    ]


def fit_eval(X_tr, y_tr, X_te, y_te, kind, estimator):
    pipe = Pipeline([("prep", make_preprocessor(X_tr, kind)), ("model", estimator)])
    t0 = time.time()
    pipe.fit(X_tr, y_tr)
    fit_time = time.time() - t0
    pred = pipe.predict(X_te)
    metrics = {
        "balanced_acc": balanced_accuracy_score(y_te, pred),
        "f1_macro": f1_score(y_te, pred, average="macro"),
        "accuracy": accuracy_score(y_te, pred),
        "recall_High": recall_score(y_te, pred, labels=["High"], average=None)[0],
        "f1_High": f1_score(y_te, pred, labels=["High"], average=None)[0],
        "temps_s": fit_time,
    }
    return pipe, pred, metrics


def compare(df, save, outdir, models_dir):
    section_title("1. Comparaison des jeux de variables et des algorithmes")
    y = df[TARGET]
    rows = []
    best = {}  # meilleur modèle par jeu de variables

    train_idx, test_idx = train_test_split(
        df.index, test_size=0.2, stratify=y, random_state=SEED
    )
    out(f"Entraînement : {len(train_idx)} lignes | Test : {len(test_idx)} lignes")

    for set_name, cols in FEATURE_SETS.items():
        if cols is None:
            cols = [c for c in df.columns if c not in ("id", TARGET)]
        X = df[cols]
        X_tr, X_te = X.loc[train_idx], X.loc[test_idx]
        y_tr, y_te = y.loc[train_idx], y.loc[test_idx]

        for name, kind, est in build_models():
            pipe, pred, m = fit_eval(X_tr, y_tr, X_te, y_te, kind, est)
            rows.append({"jeu": set_name, "modele": name, **m})
            out(
                f"  [{set_name:<3}] {name:<22} "
                f"bal_acc={m['balanced_acc']:.3f}  f1_macro={m['f1_macro']:.3f}  "
                f"recall_High={m['recall_High']:.3f}  ({m['temps_s']:.0f}s)"
            )
            if set_name not in best or m["balanced_acc"] > best[set_name]["m"]["balanced_acc"]:
                best[set_name] = {
                    "name": name,
                    "pipe": pipe,
                    "pred": pred,
                    "m": m,
                    "cols": cols,
                    "y_te": y_te,
                }

    res = pd.DataFrame(rows)
    res.to_csv(outdir / "model_comparison.csv", index=False)

    section_title("2. Tableau récapitulatif (trié par balanced accuracy)")
    out(
        res.sort_values("balanced_acc", ascending=False)
        .round(3)
        .to_string(index=False)
    )

    section_title("3. Meilleur modèle par jeu de variables")
    for set_name, b in best.items():
        m = b["m"]
        out(
            f"{set_name:<4} -> {b['name']:<22} bal_acc={m['balanced_acc']:.3f} "
            f"f1_macro={m['f1_macro']:.3f} recall_High={m['recall_High']:.3f}"
        )
        cm = pd.DataFrame(
            confusion_matrix(b["y_te"], b["pred"], labels=CLASSES, normalize="true"),
            index=[f"vrai_{c}" for c in CLASSES],
            columns=[f"pred_{c}" for c in CLASSES],
        )
        out("Matrice de confusion (normalisée par ligne) :")
        out(cm.round(3).to_string())
        out()
        plot_confusion(cm, set_name, b["name"], outdir)

        if save:
            models_dir.mkdir(exist_ok=True)
            joblib.dump(
                {
                    "pipeline": b["pipe"],
                    "features": b["cols"],
                    "classes": CLASSES,
                    "model_name": b["name"],
                    "metrics": {k: float(v) for k, v in m.items()},
                },
                models_dir / f"irrigation_{set_name}.joblib",
            )
    if save:
        out(f"Modèles sauvegardés dans {models_dir}/")
    return df.loc[train_idx], df.loc[test_idx]


def ablation(train, test):
    section_title("4. Ablation : perte de balanced accuracy si on retire une variable")
    out("(Gradient Boosting, jeu de test identique ; delta négatif = la variable compte)")
    y_tr, y_te = train[TARGET], test[TARGET]
    for set_name in ("A", "B"):
        cols = FEATURE_SETS[set_name]
        est = HistGradientBoostingClassifier(
            max_iter=300, learning_rate=0.1, class_weight="balanced", random_state=SEED
        )
        _, _, base = fit_eval(train[cols], y_tr, test[cols], y_te, "tree", est)
        out(f"\nJeu {set_name} complet : bal_acc={base['balanced_acc']:.3f}")
        rows = []
        for col in cols:
            sub = [c for c in cols if c != col]
            est = HistGradientBoostingClassifier(
                max_iter=300, learning_rate=0.1, class_weight="balanced", random_state=SEED
            )
            _, _, m = fit_eval(train[sub], y_tr, test[sub], y_te, "tree", est)
            rows.append(
                {
                    "variable_retiree": col,
                    "bal_acc": m["balanced_acc"],
                    "delta": m["balanced_acc"] - base["balanced_acc"],
                }
            )
        table = pd.DataFrame(rows).sort_values("delta")
        out(table.round(4).to_string(index=False))


def plot_confusion(cm, set_name, model_name, outdir):
    try:
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError:
        return
    plt.figure(figsize=(5, 4.2))
    plt.imshow(cm.values, cmap="Blues", vmin=0, vmax=1)
    plt.xticks(range(3), CLASSES)
    plt.yticks(range(3), CLASSES)
    for i in range(3):
        for j in range(3):
            plt.text(j, i, f"{cm.values[i, j]:.2f}", ha="center", va="center")
    plt.xlabel("Prédit")
    plt.ylabel("Réel")
    plt.title(f"Jeu {set_name} - {model_name}")
    plt.tight_layout()
    plt.savefig(outdir / f"confusion_{set_name}.png", dpi=120)
    plt.close()


def section_title(title):
    out()
    out("=" * 70)
    out(title)
    out("=" * 70)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--path", default="data/train.csv")
    parser.add_argument("--sample", type=int, default=0, help="taille d'échantillon (0 = tout)")
    parser.add_argument("--no-save", action="store_true", help="ne pas sauvegarder les modèles")
    parser.add_argument("--no-ablation", action="store_true", help="ignorer l'ablation")
    args = parser.parse_args()

    outdir = Path("reports")
    outdir.mkdir(exist_ok=True)

    df = pd.read_csv(args.path)
    if args.sample and args.sample < len(df):
        df = df.sample(args.sample, random_state=SEED).reset_index(drop=True)
        out(f"(Échantillon aléatoire de {args.sample} lignes)")

    train, test = compare(df, not args.no_save, outdir, Path("models"))
    if not args.no_ablation:
        ablation(train, test)

    (outdir / "model_comparison.txt").write_text("\n".join(REPORT), encoding="utf-8")
    print(f"\nRapport enregistré : {outdir / 'model_comparison.txt'}")


if __name__ == "__main__":
    main()
