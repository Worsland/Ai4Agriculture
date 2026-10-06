# TP IoT — Système de surveillance connectée avec IA

## Objectif du projet

Ce projet met en œuvre une architecture IoT complète pour surveiller des mesures environnementales en temps réel puis les exploiter avec un modèle d’intelligence artificielle. Il associe :

- un capteur de température et d’humidité DHT22,
- un microcontrôleur ESP32,
- une base de données Firebase en temps réel,
- un tableau de bord web pour visualiser les données,
- un moteur d’IA pour prédire les prochaines valeurs.

L’objectif principal est de démontrer un flux de données complet : acquisition, stockage, visualisation, automatisation et intelligence artificielle.

---

## 1. Architecture globale

Le système suit le schéma fonctionnel suivant :

1. L’ESP32 lit les mesures du DHT22.
2. Le microcontrôleur envoie les valeurs vers Firebase.
3. Le tableau de bord web affiche les données en direct.
4. Un script Python récupère l’historique Firebase.
5. Le modèle IA prédit la prochaine température et humidité.
6. La prédiction est écrite dans Firebase et affichée dans le dashboard.

---

## 2. Composants du projet

### 2.1 Capteur et périphériques embarqués
Le fichier [src/main.cpp](src/main.cpp) contient la logique du microcontrôleur ESP32.

Il permet de :
- se connecter au réseau Wi‑Fi,
- initialiser le capteur DHT22,
- lire la température et l’humidité,
- transmettre les données à Firebase,
- lire les états des LEDs depuis la base,
- piloter les sorties numériques selon les commandes reçues.

### 2.2 Interface web
Le fichier [index.html](index.html) constitue le front-end du système.

Sa responsabilité est de :
- initialiser l’application Firebase,
- écouter les changements de données en temps réel,
- afficher les valeurs actuelles de température et d’humidité,
- afficher les états des LED 1 et LED 2,
- afficher la prédiction IA sous forme de valeurs estimées.

### 2.3 Base de données Firebase
La base de données est une Realtime Database Firebase. Elle centralise l’état du système et les mesures enregistrées.

Les principales clés utilisées sont :
- `/led_1` : état logique de la LED 1
- `/led_2` : état logique de la LED 2
- `/sensors` : dernière mesure de température/humidité envoyée par l’ESP32
- `/history` : historique des mesures
- `/ai/prediction` : prédiction calculée par le script Python

### 2.4 Intelligence artificielle
Le dossier [ai](ai) contient le module IA. Le script [ai/sensor_ai.py](ai/sensor_ai.py) réalise les tâches suivantes :

- récupère les historiques Firebase,
- nettoie et structure les données,
- entraîne un modèle de régression à partir de l’historique,
- calcule une prédiction pour la prochaine mesure,
- envoie la prédiction vers Firebase dans `/ai/prediction`.

L’implémentation actuelle utilise une approche légère et robuste adaptée à un contexte pédagogique et embarqué.

---

## 3. Flux de données détaillé

### Acquisition
L’ESP32 lit le DHT22 et envoie les valeurs sous cette forme JSON :

```json
{
  "temperature": 23.4,
  "humidity": 58.1
}
```

Ces valeurs sont enregistrées dans `/sensors`.

### Synchronisation
Le front-end écoute Firebase en temps réel. Toute modification des données déclenche automatiquement la mise à jour de l’interface.

### Prédiction IA
Le script Python reprend l’historique disponible dans `/history` ou, si la base n’est pas accessible, utilise des données synthétiques en mode démo. Un modèle de régression est ensuite entraîné puis utilisé pour estimer la prochaine mesure.

La sortie prédictive est envoyée dans `/ai/prediction` afin d’être visible dans le tableau de bord.

---

## 4. Structure des fichiers

- [src/main.cpp](src/main.cpp) : code de l’ESP32
- [index.html](index.html) : interface web du dashboard
- [diagram.json](diagram.json) : schéma du circuit Wokwi
- [platformio.ini](platformio.ini) : configuration PlatformIO
- [firebase.json](firebase.json) : configuration Firebase Hosting
- [ai/sensor_ai.py](ai/sensor_ai.py) : script Python de prédiction
- [ai/requirements.txt](ai/requirements.txt) : dépendances Python
- [ai/.env](ai/.env) : configuration locale Firebase
- [ai/.env.example](ai/.env.example) : modèle de configuration
- [ai/README.md](ai/README.md) : documentation spécifique au module IA

---

## 5. Configuration requise

### 5.1 Prérequis
- Python 3.12+
- Environnement virtuel Python
- Accès à Firebase avec une Realtime Database active
- Module ESP32 avec Wi‑Fi actif
- Capteur DHT22

### 5.2 Variables d’environnement
Le fichier [ai/.env](ai/.env) doit contenir les informations suivantes :

```env
FIREBASE_DATABASE_URL=https://oct-stage-default-rtdb.firebaseio.com
FIREBASE_API_KEY=your-firebase-api-key
```

Ces variables permettent au script Python d’écrire directement dans la base Firebase.

---

## 6. Installation et lancement

### 6.1 Créer ou activer l’environnement virtuel
```powershell
cd ai
.\.venv\Scripts\Activate.ps1
```

### 6.2 Installer les dépendances
```powershell
python -m pip install -r requirements.txt
```

### 6.3 Lancer le script de prédiction
Version réelle :
```powershell
python sensor_ai.py
```

Version démo (sans Firebase) :
```powershell
python sensor_ai.py --demo
```

### 6.4 Démarrer le dashboard
Le tableau de bord est hébergé dans le fichier [index.html](index.html). Il suffit de l’ouvrir dans un navigateur web moderne.

Pour un déploiement réel, il peut également être publié sur Firebase Hosting en fonction de la configuration de [firebase.json](firebase.json).

---

## 7. Sécurité et bonnes pratiques

Quelques points importants à prendre en compte :

- ne jamais exposer la clé API Firebase dans un contexte public si l’application n’est pas conçue pour l’être,
- limiter les permissions réelles de la base de données,
- éviter les accès non sécurisés à des données sensibles,
- séparer les paramètres de configuration de la logique applicative,
- utiliser un environnement virtuel pour gérer les dépendances Python.

---

## 8. Évolutions possibles

Le projet peut être étendu avec plusieurs fonctionnalités :

- historique visuel sous forme de courbes,
- alertes automatiques selon des seuils de température ou d’humidité,
- prédictions plus avancées avec des modèles temporels,
- intégration d’actions automatiques sur les LEDs ou autres capteurs,
- ajout de relais, de ventilateurs ou de serres intelligentes,
- tableau de bord plus complet avec indicateurs et graphiques.

---

## 9. Résumé fonctionnel

Ce projet illustre parfaitement un système IoT complet, où :

- les capteurs collectent des données,
- l’ESP32 agit comme nœud d’acquisition,
- Firebase sert de couche de synchronisation,
- le dashboard donne une vue temps réel,
- l’IA ajoute une dimension prédictive et analytique.

Il constitue une base solide pour développer des applications IoT plus avancées, connectées et intelligentes.
