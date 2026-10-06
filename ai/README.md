# Intégration IA pour le dashboard IoT

Ce dossier contient le pipeline IA qui lit l'historique des mesures Firebase, entraîne un petit modèle de régression sur les données de température et d'humidité, puis publie une prédiction dans la base de données afin qu'elle soit affichée dans le dashboard web.

## Prérequis

- Python 3.12+
- Virtual environment avec les dépendances du projet

## Installation

```powershell
cd ai
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

## Configuration Firebase

Copiez le fichier d'exemple puis renseignez vos valeurs Firebase :

```powershell
Copy-Item .env.example .env
```

Remplissez :
- `FIREBASE_DATABASE_URL` : URL de votre base Firebase
- `FIREBASE_API_KEY` : clé API Firebase

## Exécution

Version de démonstration (sans accès Firebase) :

```powershell
python sensor_ai.py --demo
```

Version réelle (avec Firebase) :

```powershell
python sensor_ai.py
```

Le script écrit la prédiction sous la clé `ai/prediction` dans la base de données.
