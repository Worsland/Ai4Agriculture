"""Exploration du jeu de données d'irrigation (Kaggle Playground S6E4).

Usage (depuis le dossier ai/) :
    python explore_dataset.py
    python explore_dataset.py --sample 100000      # analyse plus rapide
    python explore_dataset.py --path data/train.csv

Produit :
    - un rapport texte  : reports/exploration.txt
    - des graphiques    : reports/*.png (si matplotlib est installé)
"""

import argparse
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestClassifier
from sklearn.feature_selection import mutual_info_classif

TARGET = "Irrigation_Need"
ORDER = ["Low", "Medium", "High"]

# Variables mesurées par l'ESP32 et leur plage côté capteur simulé (Wokwi)
SENSOR_COLS = {
    "Soil_Moisture": (0, 100),
    "Soil_pH": (0, 14),
    "Temperature_C": (-40, 80),
    "Humidity": (0, 100),
}

REPORT_LINES = []


def out(text=""):
    """Affiche et mémorise une ligne du rapport."""
    print(text)
    REPORT_LINES.append(str(text))


def section(title):
    out()
    out("=" * 70)
    out(title)
    out("=" * 70)


def load(path, sample):
    df = pd.read_csv(path)
    if sample and sample < len(df):
        df = df.sample(sample, random_state=42).reset_index(drop=True)
        out(f"(Analyse sur un échantillon aléatoire de {sample} lignes)")
    return df


def overview(df):
    section("1. Vue d'ensemble")
    out(f"Dimensions : {df.shape[0]} lignes x {df.shape[1]} colonnes")
    out(f"Identifiants uniques : {df['id'].is_unique}")
    features = [c for c in df.columns if c not in ("id", TARGET)]
    out(f"Doublons (hors id) : {df.duplicated(subset=features + [TARGET]).sum()}")
    out()
    out("Types des colonnes :")
    out(df.dtypes.to_string())
    out()
    missing = df.isna().sum()
    out("Valeurs manquantes :")
    if missing.sum() == 0:
        out("  aucune")
    else:
        out(missing[missing > 0].to_string())


def target_distribution(df):
    section("2. Distribution de la cible")
    counts = df[TARGET].value_counts().reindex(ORDER)
    for label, n in counts.items():
        out(f"  {label:<7} {n:>8}  ({n / len(df):6.2%})")
    ratio = counts.max() / counts.min()
    out(f"Rapport classe majoritaire / minoritaire : {ratio:.1f}")
    out("-> Utiliser balanced accuracy / F1 macro et des poids de classes.")


def numeric_summary(df, num_cols):
    section("3. Variables numériques")
    out(df[num_cols].describe().T[["min", "mean", "std", "max"]].round(2).to_string())
    out()
    out("Moyenne par classe de besoin :")
    out(df.groupby(TARGET)[num_cols].mean().reindex(ORDER).T.round(2).to_string())


def categorical_summary(df, cat_cols):
    section("4. Variables catégorielles")
    for col in cat_cols:
        out(f"{col} ({df[col].nunique()} valeurs) :")
        share = df[col].value_counts(normalize=True)
        out("  " + ", ".join(f"{k} {v:.1%}" for k, v in share.items()))
        # Part de chaque classe de besoin selon la modalité
        table = pd.crosstab(df[col], df[TARGET], normalize="index")[ORDER]
        spread = (table["High"].max() - table["High"].min()) * 100
        out(f"  écart de part 'High' entre modalités : {spread:.1f} points")


def sensor_domain_check(df):
    section("5. Plages des capteurs ESP32 vs jeu d'entraînement")
    out(f"{'Variable':<16}{'Jeu min':>9}{'Jeu max':>9}   Plage capteur ESP32")
    for col, (lo, hi) in SENSOR_COLS.items():
        out(f"{col:<16}{df[col].min():>9.2f}{df[col].max():>9.2f}   [{lo}, {hi}]")
    out("-> Si la plage du capteur dépasse celle du jeu, borner les valeurs")
    out("   avant la prédiction ou restreindre la simulation Wokwi.")


def correlations(df, num_cols):
    section("6. Corrélation (Spearman) avec la cible ordinale")
    y = df[TARGET].map({k: i for i, k in enumerate(ORDER)})
    corr = df[num_cols].corrwith(y, method="spearman").sort_values(key=abs, ascending=False)
    out(corr.round(3).to_string())
    return corr


def importance(df, num_cols, cat_cols, n=100_000):
    section("7. Importance préliminaire des variables")
    sub = df.sample(min(n, len(df)), random_state=0)
    y = sub[TARGET]
    X = sub[num_cols].copy()
    for col in cat_cols:
        X[col] = sub[col].astype("category").cat.codes

    discrete = [c in cat_cols for c in X.columns]
    mi = mutual_info_classif(X, y, discrete_features=discrete, random_state=0)
    mi = pd.Series(mi, index=X.columns)

    rf = RandomForestClassifier(
        n_estimators=100,
        min_samples_leaf=5,
        class_weight="balanced",
        n_jobs=-1,
        random_state=0,
    ).fit(X, y)
    rf_imp = pd.Series(rf.feature_importances_, index=X.columns)

    table = pd.DataFrame(
        {"info_mutuelle": mi.round(4), "importance_RF": rf_imp.round(4)}
    ).sort_values("importance_RF", ascending=False)
    out(table.to_string())
    out()
    out("Variables à faible importance sur les deux colonnes : candidates à retirer.")
    return table


def plots(df, num_cols, corr_all, outdir):
    try:
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError:
        out("\n(matplotlib absent : graphiques ignorés. pip install matplotlib)")
        return

    # Distribution de la cible
    counts = df[TARGET].value_counts().reindex(ORDER)
    plt.figure(figsize=(5, 4))
    plt.bar(counts.index, counts.values, color=["#4c9f70", "#e0a030", "#c0392b"])
    plt.title("Distribution de Irrigation_Need")
    plt.ylabel("Observations")
    plt.tight_layout()
    plt.savefig(outdir / "target_distribution.png", dpi=120)
    plt.close()

    # Boxplots des variables capteurs par classe
    cols = list(SENSOR_COLS) + ["Rainfall_mm", "Sunlight_Hours"]
    fig, axes = plt.subplots(2, 3, figsize=(12, 7))
    for ax, col in zip(axes.ravel(), cols):
        data = [df.loc[df[TARGET] == k, col] for k in ORDER]
        ax.boxplot(data, showfliers=False)
        ax.set_xticks(range(1, len(ORDER) + 1))
        ax.set_xticklabels(ORDER)
        ax.set_title(col)
    plt.tight_layout()
    plt.savefig(outdir / "features_by_class.png", dpi=120)
    plt.close()

    # Matrice de corrélation
    corr = df[num_cols].corr(method="spearman")
    plt.figure(figsize=(8, 7))
    plt.imshow(corr, cmap="coolwarm", vmin=-1, vmax=1)
    plt.xticks(range(len(num_cols)), num_cols, rotation=90)
    plt.yticks(range(len(num_cols)), num_cols)
    plt.colorbar(label="Spearman")
    plt.title("Corrélations entre variables numériques")
    plt.tight_layout()
    plt.savefig(outdir / "correlation_matrix.png", dpi=120)
    plt.close()

    out(f"\nGraphiques enregistrés dans {outdir}/")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--path", default="data/train.csv")
    parser.add_argument("--sample", type=int, default=0, help="taille d'échantillon (0 = tout)")
    args = parser.parse_args()

    outdir = Path("reports")
    outdir.mkdir(exist_ok=True)

    df = load(args.path, args.sample)
    num_cols = [
        c for c in df.select_dtypes(include="number").columns if c != "id"
    ]
    cat_cols = [
        c for c in df.select_dtypes(exclude="number").columns if c != TARGET
    ]

    overview(df)
    target_distribution(df)
    numeric_summary(df, num_cols)
    categorical_summary(df, cat_cols)
    sensor_domain_check(df)
    corr = correlations(df, num_cols)
    importance(df, num_cols, cat_cols)
    plots(df, num_cols, corr, outdir)

    (outdir / "exploration.txt").write_text("\n".join(REPORT_LINES), encoding="utf-8")
    print(f"\nRapport enregistré : {outdir / 'exploration.txt'}")


if __name__ == "__main__":
    main()
