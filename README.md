# Agriculture intelligente — Prédiction et optimisation de l'irrigation

Projet IoT de bout en bout : des capteurs simulés (Wokwi) mesurent l'état d'une parcelle, les données transitent par Firebase, un serveur Python entraîne des modèles d'IA, et un tableau de bord web affiche l'état du sol, l'historique et les prédictions. À terme, le système estimera le besoin en irrigation et commandera automatiquement une vanne.

> **État d'avancement :** la chaîne d'acquisition, l'historique, la prédiction de température/humidité, le tableau de bord de base et la commande de vanne (côté ESP32) sont en place. Le jeu de données d'irrigation (Kaggle) est analysé et quatre algorithmes ont été comparés ; le modèle final (Gradient Boosting, 6 variables) est entraîné et la décision de la vanne est intégrée au serveur et au tableau de bord (à valider en simulation). L'historique agricole est écrit dans Firestore par le serveur et affiché par le tableau de bord, avec des règles Firestore en lecture seule (à valider avec la base réelle)  ; une API en lecture seule (FastAPI) les expose. Docker et l'intégration continue sont à venir (voir la [feuille de route](#8-feuille-de-route)).

---

## 1. Objectif du projet

Développer un système agricole connecté capable de :

- **mesurer** en continu la température, l'humidité de l'air, l'humidité du sol, le pH et la luminosité,
- **estimer** les besoins en irrigation grâce à un modèle d'IA, en comparant plusieurs algorithmes,
- **commander** automatiquement un système d'arrosage (vanne simulée par un servomoteur), avec un mode manuel,
- **visualiser** l'état de la parcelle, l'historique des mesures et des recommandations générées automatiquement.

Ce projet correspond au sujet 10 : *Agriculture intelligente pour la prédiction et l'optimisation de l'irrigation*.

---

## 2. Architecture (4 couches)

```
┌─────────────────────────────────────────────────────────────────┐
│ 1. COUCHE IoT (Wokwi)                                           │
│    ESP32 + DHT22 + 2 potentiomètres (sol, pH) + luminosité      │
│    + servomoteur (vanne)                                        │
└───────────────┬──────────────────────────────▲──────────────────┘
        mesures │                              │ commande vanne
                ▼                              │
┌─────────────────────────────────────────────────────────────────┐
│ 3. COUCHE BASE DE DONNÉES                                       │
│    Firebase Realtime Database : mesures et commandes temps réel │
│    Firestore : historique agricole (événements, résumés)        │
└───────────────┬──────────────────────────────▲──────────────────┘
       lecture  │                              │ écriture
                ▼                              │
┌─────────────────────────────────────────────────────────────────┐
│ 2. COUCHE SERVEUR (Python, local)                               │
│    Entraînement des modèles, prédictions, décision d'irrigation │
└─────────────────────────────────────────────────────────────────┘
                ▲
                │ lecture temps réel + commandes manuelles
┌─────────────────────────────────────────────────────────────────┐
│ 4. COUCHE INTERFACE (web HTML/CSS/JS)                           │
│    Tableau de bord : mesures, courbes, historique, vanne        │
└─────────────────────────────────────────────────────────────────┘
```

Firebase sert de point de communication central : l'ESP32, le serveur Python et le tableau de bord ne se parlent jamais directement.

### Flux de données

1. L'ESP32 lit les capteurs toutes les 2 secondes et écrit la dernière mesure dans `/sensors`.
2. Une fois par minute, il ajoute une entrée datée dans `/history`.
3. Le serveur Python lit les dernières mesures de `/history`, entraîne un modèle et écrit sa prédiction dans `/ai/prediction`. Il lit aussi `/sensors`, `/weather` et `/field`, calcule le besoin d'irrigation et l'écrit dans `/ai/irrigation`.
4. La commande de la vanne est écrite dans `/valve/command` (par le serveur en mode automatique, par le tableau de bord en mode manuel).
5. L'ESP32 lit cette commande, positionne le servomoteur et confirme l'état réel dans `/valve/state`.
6. Le tableau de bord écoute Firebase et se met à jour en temps réel.
7. Le serveur Python consigne l'historique agricole dans Firestore : un événement à chaque fermeture de la vanne et un résumé journalier des mesures, fusionné toutes les 10 minutes.

---

## 3. Nouveautés de cette version

**Jeu de données**
- Jeu d'irrigation retenu : Kaggle *Playground Series S6E4 — Predicting Irrigation Need* (630 000 observations, cible Low / Medium / High). Analyse de ses plages de valeurs, de l'équilibre des classes et de sa correspondance avec les capteurs de l'ESP32 (voir la section [4.5](#45-jeu-de-données-dirrigation)).
- Script d'exploration ([ai/explore_dataset.py](ai/explore_dataset.py)) : qualité des données, importance des variables, comparaison des plages avec les capteurs de l'ESP32.
- Stratégie de modélisation resserrée après l'exploration : deux jeux de variables (« capteurs seuls » et « capteurs + contexte à 4 variables ») et plusieurs algorithmes comparés.
- Script de comparaison ([ai/train_irrigation.py](ai/train_irrigation.py)) : 3 jeux de variables x 4 algorithmes, ablation, matrices de confusion et sauvegarde du meilleur modèle de chaque jeu. Résultat : Gradient Boosting sur « capteurs + contexte » (balanced accuracy de 0,965), contre 0,731 avec les capteurs seuls.
- Modèle final ([ai/train_final.py](ai/train_final.py)) : 6 variables, validation croisée à 5 plis sur les 630 000 lignes, entraînement sur toutes les données et sauvegarde avec ses métadonnées. Balanced accuracy de 0,969 (± 0,001).
- Module de prédiction ([ai/irrigation_model.py](ai/irrigation_model.py)) : bornage des valeurs hors plage et refus de décider en cas de donnée manquante ou invalide.
- Décision de la vanne ([ai/valve_controller.py](ai/valve_controller.py)) : machine à états avec ouverture courte, durée maximale, délai minimal et fermeture de sécurité, couverte par 16 tests ([ai/test_valve_controller.py](ai/test_valve_controller.py)).

**Couche IoT**
- Trois nouvelles mesures : humidité du sol (%), pH (0 à 14) et luminosité (%), lues sur des entrées analogiques de l'ADC1 (compatibles avec le WiFi).
- Une vanne simulée par un servomoteur (0° fermée, 90° ouverte), pilotée depuis Firebase. L'ESP32 signale l'état réel de la vanne.
- Lecture de Firebase allégée : l'ESP32 ne télécharge plus toute la base à chaque cycle, mais seulement les nœuds utiles. Sans cela, la croissance de l'historique finirait par saturer sa mémoire.
- Le schéma Wokwi ([diagram.json](diagram.json)) intègre les nouveaux composants.
- Garde-fous de la vanne dans [src/main.cpp](src/main.cpp), indépendants du serveur : fermeture forcée après 20 min d'ouverture continue et fermeture après 5 min sans lecture Firebase réussie (voir [4.1](#41-microcontrôleur-et-capteurs)).

**Couche serveur**
- Nouveau serveur Python continu ([ai/server.py](ai/server.py)) : il surveille Firebase et réentraîne le modèle dès qu'une nouvelle mesure arrive.
- Modèle corrigé ([ai/sensor_ai.py](ai/sensor_ai.py)) : il prédit désormais la variation jusqu'à la mesure suivante, et non plus la valeur actuelle. Les horodatages de l'ESP32 (en millisecondes) sont correctement pris en compte.
- Évaluation intégrée : l'erreur du modèle est comparée à une référence naïve (« la valeur ne change pas ») et publiée dans `/ai/status`.
- Plus de repli silencieux sur des données fictives : en cas d'erreur Firebase, rien n'est écrit. Le mode `--demo` n'écrit jamais dans la base.
- Décision d'irrigation intégrée à la boucle du serveur ([ai/irrigation_service.py](ai/irrigation_service.py)) : lecture des mesures, de la météo simulée et des réglages de la parcelle, prédiction du besoin, commande de `/valve/command` en mode automatique, publication de `/ai/irrigation`. Une erreur d'irrigation ne bloque pas la prédiction température/humidité, et inversement. Option `--no-irrigation` pour la désactiver.
- Historique agricole dans Firestore ([ai/history_store.py](ai/history_store.py)) : événements d'ouverture de la vanne (durée, mode, besoin prédit, raison) et résumés journaliers des capteurs (min, max, moyenne, minutes d'ouverture). Une panne de Firestore ne bloque ni la prédiction ni la vanne ; options `--no-history` et `--history-flush`. Couvert par 12 tests ([ai/test_history_store.py](ai/test_history_store.py)).
- API REST en lecture seule ([ai/api.py](ai/api.py), FastAPI) : mesures, prédiction, recommandation d'irrigation et historique agricole, dans un processus séparé du serveur IA (voir [4.7](#47-api-rest-en-lecture-seule)). Couverte par 49 tests ([ai/test_api.py](ai/test_api.py)).

**Couche interface**
- Tableau de bord redessiné : mesures actuelles avec variations, graphiques température/humidité avec prédiction en pointillés, statistiques, historique consultable (20, 50 ou 200 dernières mesures), contrôle des LED.
- Nouveaux panneaux : humidité du sol, pH et luminosité ; recommandation d'irrigation avec scores du modèle ; état réel de la vanne, choix du mode automatique ou manuel et commande manuelle ; réglages de la parcelle (stade de croissance, paillage) et météo simulée (pluie, vent) saisis à la main.
- Panneau « Historique agricole » lu dans Firestore : résumés journaliers sur 7, 14 ou 30 jours (température, humidités, minutes d'ouverture, arrosages), totaux de la période et 20 dernières ouvertures de la vanne.

---

## 4. Composants du projet

### 4.1 Microcontrôleur et capteurs
Le fichier [src/main.cpp](src/main.cpp) contient la logique de l'ESP32.

| Composant | Broche | Rôle |
|---|---|---|
| DHT22 | D15 | Température et humidité de l'air |
| Potentiomètre 1 | D34 | Humidité du sol |
| Potentiomètre 2 | D35 | pH |
| Capteur de luminosité (AO) | D32 | Luminosité |
| Servomoteur | D18 | Vanne d'irrigation |
| LED 1 / LED 2 | D22 / D23 | Sorties de test |

**Comportement de la vanne côté ESP32 :**
- Au démarrage, l'ESP32 écrit `/valve` avec `mode = "auto"` et `command = false` : la vanne est fermée et le mode repasse en automatique (un choix « manuel » ne survit donc pas à un redémarrage). Cette écriture efface aussi `/valve/state`, que l'ESP32 republie dès le premier cycle.
- Il lit `command` toutes les 2 secondes et ne tient pas compte du mode : c'est le serveur (automatique) ou le tableau de bord (manuel) qui décide.
- Garde-fous locaux (structure `ValveSafety`) : fermeture forcée après 20 min d'ouverture continue, y compris en mode manuel, et fermeture si aucune lecture Firebase n'a réussi depuis 5 min. Après une fermeture forcée, un verrou ignore la commande « ouvrir » tant qu'elle n'est pas repassée à `false`. Après une fermeture pour durée maximale, l'ESP32 remet aussi `/valve/command` à `false`. Les constantes `VALVE_MAX_OPEN_MS` et `VALVE_COMM_LOSS_MS` se règlent dans `src/main.cpp`.
- Le serveur ferme normalement la vanne avant (15 min maximum) : ces garde-fous servent quand le serveur ou le réseau tombe.

### 4.2 Interface web
Le fichier [index.html](index.html) est le front-end. Il initialise Firebase, écoute les changements en temps réel et affiche les mesures, les courbes, l'historique, la prédiction IA et les LED. Il affiche aussi l'état du sol (humidité, pH, luminosité), la recommandation d'irrigation du serveur, l'état réel de la vanne, le choix du mode (automatique ou manuel) et les réglages de la parcelle et de la météo simulée. Un panneau « Historique agricole » lit en direct les collections Firestore `daily_summaries` et `irrigation_events` (lecture seule). Si les règles Firestore ne sont pas publiées, le panneau affiche un message d'erreur.

### 4.3 Base de données Firebase
Realtime Database. Chemins utilisés :

| Chemin | Contenu | Écrit par |
|---|---|---|
| `/sensors` | `temperature`, `humidity`, `soil_moisture`, `ph`, `light` (dernière mesure) | ESP32 |
| `/history` | mêmes champs + `timestamp`, une entrée par minute | ESP32 |
| `/valve/mode` | `"auto"` ou `"manual"` (remis à `"auto"` par l'ESP32 à chaque démarrage) | tableau de bord, ESP32 au démarrage |
| `/valve/command` | `true` ouvre la vanne, `false` la ferme | serveur (auto), tableau de bord (manuel), ESP32 (fermeture forcée) |
| `/valve/state` | `open`, `angle` : état réel de la vanne | ESP32 |
| `/ai/prediction` | prédiction de la prochaine mesure + `updated_at` | serveur Python |
| `/ai/status` | `samples`, `mae`, `baseline_mae` : qualité du modèle | serveur Python |
| `/weather` | `rainfall` (mm), `wind` (km/h) : météo simulée | tableau de bord |
| `/field` | `growth_stage` (`Sowing`, `Vegetative`, `Flowering`, `Harvest`), `mulching` (booléen) : réglages de la parcelle | tableau de bord |
| `/ai/irrigation` | `need`, `probabilities`, `action`, `reason`, `error`, `mode`, `command`, `inputs`, `updated_at` | serveur Python |
| `/led_1`, `/led_2` | état des LED | tableau de bord |

**Attention aux noms de nœuds racine.** Pour ne pas télécharger l'historique, l'ESP32 ne lit que les nœuds dont le nom, classé par ordre alphabétique (ASCII), est compris entre `led_1` et `valve`. Les nœuds `ai`, `field`, `history` et `weather` sont en dehors de cet intervalle. Un nouveau nœud racine dont le nom s'y situe (par exemple `meteo`, `parcelle` ou `stats`) serait téléchargé à chaque cycle : choisir un nom hors de l'intervalle.

Exemple de mesure envoyée par l'ESP32 :

```json
{
  "temperature": 23.4,
  "humidity": 58.1,
  "soil_moisture": 41.2,
  "ph": 6.8,
  "light": 72.5
}
```

#### Firestore : historique agricole

La Realtime Database garde l'état courant et l'historique minute par minute. Firestore, dans le même projet Firebase, conserve l'historique agricole à plus long terme. Seul le serveur Python y écrit (compte de service, qui contourne les règles).

| Collection / document | Contenu | Écrit quand |
|---|---|---|
| `irrigation_events/{id}` | `day`, `opened_at`, `closed_at`, `duration_s`, `mode` (`auto` ou `manual`), `need`, `reason`, `approximate` | à la fermeture de la vanne |
| `daily_summaries/{AAAA-MM-JJ}` | `date`, `samples`, `sensors` (par capteur : `n`, `sum`, `min`, `max`, `avg`), `valve_open_s`, `irrigation_count`, `updated_at` | toutes les 10 min (fusion avec le document du jour) |

Précisions :
- Le jour est celui de l'heure locale du serveur.
- Une mesure n'est comptée que si `/history` a reçu une nouvelle entrée : une simulation arrêtée ne fausse pas les statistiques.
- Les durées d'ouverture sont exactes à un cycle du serveur près (60 s par défaut). `approximate` vaut `true` quand la vanne était déjà ouverte au démarrage du serveur : l'heure d'ouverture est alors inconnue.
- En cas de panne de Firestore, les données restent en attente et sont renvoyées au cycle suivant. Elles sont perdues si le serveur s'arrête avant : un arrêt par Ctrl+C déclenche une dernière écriture.
- Les événements en cours (vanne ouverte) ne sont écrits qu'à la fermeture.

**Règles Firestore** ([firestore.rules](firestore.rules)) : les deux collections sont lisibles par le tableau de bord (sans authentification) et aucune écriture n'est autorisée aux clients ; le serveur écrit avec le compte de service, qui contourne les règles. Tout le reste de la base est fermé. La lecture publique est acceptable pour ce TP, mais elle expose l'historique à toute personne qui connaît l'identifiant du projet : une vraie mise en production demande d'authentifier le tableau de bord (voir la [section 7](#7-sécurité-et-bonnes-pratiques)).

### 4.4 Serveur Python et IA
Le dossier [ai](ai) contient :

- [ai/server.py](ai/server.py) : boucle continue (une vérification par minute par défaut). Elle lit `/history`, entraîne le modèle s'il y a une nouvelle mesure et écrit les résultats dans Firebase. Elle appelle ensuite le service d'irrigation (voir [4.6](#46-décision-de-la-vanne)).
- [ai/irrigation_service.py](ai/irrigation_service.py) : accès REST à Firebase, suivi de la fraîcheur des mesures et cycle de décision d'irrigation.
- [ai/history_store.py](ai/history_store.py) : historique agricole dans Firestore (suivi des ouvertures de la vanne, résumés journaliers, accès `firebase-admin`), appelé par `server.py` à chaque cycle.
- [ai/sensor_ai.py](ai/sensor_ai.py) : chargement et nettoyage des données, entraînement (Random Forest), évaluation sur les 20 % de mesures les plus récentes, prédiction. Il peut aussi être lancé seul pour un entraînement ponctuel.

Au moins 20 mesures sont nécessaires avant le premier entraînement. L'évaluation de l'erreur demande 30 mesures.

### 4.5 Jeu de données d'irrigation

**Source :** Kaggle, *Playground Series S6E4 — Predicting Irrigation Need* (https://www.kaggle.com/competitions/playground-series-s6e4). Fichier utilisé : `ai/data/train.csv` (non versionné, voir [6.4](#64-récupérer-le-jeu-de-données)).

**Contenu :**
- 630 000 observations, 21 colonnes (`id`, 19 variables explicatives, cible `Irrigation_Need`). Une ligne correspond à une observation sans horodatage : ce ne sont pas des séries temporelles.
- Cible : `Low` 58,7 %, `Medium` 37,9 %, `High` 3,3 %. Les classes sont fortement déséquilibrées.
- Jeu de type Playground, donc très probablement généré artificiellement (les écarts-types des variables numériques sont proches de ceux d'une loi uniforme ; à confirmer sur la page *Data* de Kaggle). Il sert à entraîner et comparer des modèles, pas à représenter des mesures de terrain. Ce point doit être indiqué dans le rapport.

**Résultats de l'exploration** (script [ai/explore_dataset.py](ai/explore_dataset.py), échantillon de 100 000 lignes, rapport dans `ai/reports/exploration.txt`) :
- Données propres : aucune valeur manquante, aucun doublon, identifiants uniques.
- Variables les plus déterminantes : `Soil_Moisture` (corrélation de Spearman de −0,45 avec la cible, importance Random Forest de 0,28), `Crop_Growth_Stage` (0,20), `Temperature_C` (0,14), `Wind_Speed_kmh` (0,11), `Rainfall_mm` (0,11) et `Mulching_Used` (0,10).
- `Rainfall_mm` a une faible corrélation linéaire (−0,08) mais une forte information mutuelle : son effet est non linéaire (la classe `High` apparaît surtout avec peu de pluie). Les modèles à base d'arbres sont donc adaptés.
- Variables quasi sans effet (importance d'environ 0,01 ou moins) : `Humidity`, `Soil_pH`, `Sunlight_Hours`, `Previous_Irrigation_mm`, `Organic_Carbon`, `Electrical_Conductivity`, `Field_Area_hectare`, `Soil_Type`, `Crop_Type`, `Season`, `Region`, `Water_Source`, `Irrigation_Type`.
- Limite : l'importance provient d'un seul Random Forest avec des variables catégorielles codées en entiers. Elle sera confirmée par une ablation (retrait d'une variable à la fois) lors de la comparaison des modèles.

**Plages des variables mesurées par l'ESP32 :**

| Variable du jeu | Min | Max | Capteur ESP32 | Plage du capteur simulé |
|---|---|---|---|---|
| `Soil_Moisture` | 8 | 65 | `soil_moisture` (potentiomètre D34) | 0 à 100 |
| `Soil_pH` | 4,8 | 8,2 | `ph` (potentiomètre D35) | 0 à 14 |
| `Temperature_C` | 12 | 42 | `temperature` (DHT22) | -40 à 80 |
| `Humidity` | 25 | 95 | `humidity` (DHT22) | 0 à 100 |

Toutes les plages du jeu sont plus étroites que celles des capteurs simulés : les valeurs sont bornées côté serveur avant la prédiction.

**Variables retenues :**

| Groupe | Variables | Source dans le projet | Modèles |
|---|---|---|---|
| Mesurées par l'ESP32 | `Soil_Moisture`, `Temperature_C`, `Humidity`, `Soil_pH` | Firebase `/sensors` | A et B |
| Météo simulée | `Rainfall_mm`, `Wind_Speed_kmh` | Module de météo simulée (à venir) | B |
| Réglages de la parcelle | `Crop_Growth_Stage`, `Mulching_Used` | Tableau de bord | B |
| Écartées | toutes les autres | — | — |

La luminosité (`light`) reste mesurée et affichée, mais n'entre pas dans le modèle : `Sunlight_Hours` n'a aucun effet sur la cible, donc aucune conversion d'unité n'est nécessaire.

**Stratégie de modélisation :**
- **Modèle A, capteurs seuls** : les 4 variables mesurées. Branché directement sur l'ESP32. Seules l'humidité du sol et la température pèsent vraiment, la précision attendue est donc plus faible, surtout sur la classe `High`. Il sert de référence.
- **Modèle B, capteurs + contexte** : A plus pluie, vent, stade de croissance et paillage. Plus précis, mais dépendant de la météo simulée et de deux réglages du tableau de bord.
- **Modèle de référence « toutes variables »** : vérifie que l'abandon des variables écartées ne coûte rien en performance.
- **Algorithmes comparés** : Régression logistique (point de comparaison linéaire), Arbre de décision, Random Forest, Gradient Boosting.
- **Métriques** : balanced accuracy et F1 macro (l'accuracy seule est trompeuse avec 3,3 % de classe `High`), plus la matrice de confusion. Déséquilibre traité par des poids de classes.
- **Bornage** : avant toute prédiction, `Soil_Moisture` est ramenée à [8, 65], `Temperature_C` à [12, 42], `Humidity` à [25, 95] et `Soil_pH` à [4,8, 8,2].
- Le modèle de décision de la vanne ne doit utiliser que des variables réellement disponibles au moment de la décision.

**Résultats de la comparaison des modèles** (script [ai/train_irrigation.py](ai/train_irrigation.py), rapport dans `ai/reports/model_comparison.txt`) :

Évaluation sur un échantillon aléatoire de 200 000 lignes : 160 000 pour l'entraînement, 40 000 pour le test (découpage stratifié, graine 42, un seul découpage).

| Jeu de variables | Meilleur algorithme | Balanced accuracy | F1 macro | Rappel `High` |
|---|---|---|---|---|
| A, capteurs seuls (4 variables) | Gradient Boosting | 0,731 | 0,601 | 0,847 |
| B, capteurs + contexte (8 variables) | Gradient Boosting | 0,965 | 0,961 | 0,931 |
| ALL, toutes les variables (19) | Gradient Boosting | 0,963 | 0,961 | 0,925 |

Comparaison des algorithmes sur le jeu B :

| Algorithme | Balanced accuracy | F1 macro | Rappel `High` |
|---|---|---|---|
| Régression logistique | 0,843 | 0,742 | 0,872 |
| Arbre de décision | 0,958 | 0,927 | 0,929 |
| Random Forest | 0,961 | 0,965 | 0,914 |
| Gradient Boosting | 0,965 | 0,961 | 0,931 |

Ablation (Gradient Boosting, jeu B, perte de balanced accuracy quand on retire la variable) :

| Variable retirée | Perte |
|---|---|
| `Soil_Moisture` | -0,140 |
| `Crop_Growth_Stage` | -0,106 |
| `Temperature_C` | -0,062 |
| `Rainfall_mm` | -0,061 |
| `Mulching_Used` | -0,052 |
| `Wind_Speed_kmh` | -0,045 |
| `Soil_pH` | -0,0004 (nul) |
| `Humidity` | +0,0012 (nul) |

**Conclusions :**
- Les capteurs seuls (A) ne suffisent pas : la balanced accuracy passe de 0,731 à 0,965 avec le contexte. Avec A, 27 % des cas `Medium` sont prédits `Low` et 19 % sont prédits `High` : ce modèle n'est pas assez fiable pour piloter la vanne seul.
- B et ALL sont équivalents (0,965 contre 0,963) : les variables écartées n'apportent rien.
- Les modèles à base d'arbres dépassent nettement la régression logistique (0,96 contre 0,84), ce qui confirme l'effet non linéaire de la pluie.
- Gradient Boosting, Random Forest et Arbre de décision sont à moins de 0,01 d'écart : sur un seul découpage, cette différence n'est pas significative. Gradient Boosting est retenu provisoirement (meilleure balanced accuracy et meilleur rappel de `High`, entraînement en 7 s) et l'arbre de décision reste l'alternative la plus explicable.
- L'ablation montre que `Humidity` et `Soil_pH` n'influencent pas la décision, dans A comme dans B. Ces capteurs restent mesurés et affichés sur le tableau de bord, mais le modèle final peut se limiter à 6 variables : `Soil_Moisture`, `Temperature_C`, `Rainfall_mm`, `Wind_Speed_kmh`, `Crop_Growth_Stage` et `Mulching_Used`.
- Sur la classe `High`, 6,9 % des cas sont prédits `Medium` et aucun n'est prédit `Low`.

**Limites :** un seul découpage et un échantillon de 200 000 lignes (levées par la validation croisée sur le jeu complet, voir « Modèle final » ci-dessous) ; le jeu étant synthétique, l'importance des variables reflète sa règle de génération et non une vérité agronomique.

**Modèle final** (script [ai/train_final.py](ai/train_final.py), rapport dans `ai/reports/final_model.txt`) :

Validation croisée stratifiée à 5 plis sur les 630 000 lignes, avec les 6 variables retenues (`Soil_Moisture`, `Temperature_C`, `Rainfall_mm`, `Wind_Speed_kmh`, `Crop_Growth_Stage`, `Mulching_Used`) :

| Algorithme | Balanced accuracy | F1 macro | Rappel `High` | Temps par pli |
|---|---|---|---|---|
| Arbre de décision | 0,9659 ± 0,0007 | 0,9426 | 0,9450 | 3 s |
| Random Forest | 0,9654 ± 0,0007 | 0,9695 | 0,9265 | 86 s |
| **Gradient Boosting (retenu)** | **0,9693 ± 0,0008** | 0,9589 | 0,9468 | 28 s |

- Gradient Boosting est retenu : meilleure balanced accuracy et meilleur rappel de `High`. L'écart avec l'arbre de décision (0,003) est faible en pratique : l'arbre reste une alternative très explicable et 10 fois plus rapide.
- Le modèle est entraîné sur toutes les données et sauvegardé dans `ai/models/irrigation_final.joblib` avec ses métadonnées (variables, classes, plages de bornage, modalités autorisées, résultats de validation croisée, version de scikit-learn).
- Plages de bornage : `Soil_Moisture` [8, 64,99], `Temperature_C` [12, 42], `Rainfall_mm` [0,38, 2 499,69], `Wind_Speed_kmh` [0,5, 20].
- Modalités autorisées : `Crop_Growth_Stage` parmi `Sowing`, `Vegetative`, `Flowering`, `Harvest` ; `Mulching_Used` parmi `Yes`, `No`.
- Le module [ai/irrigation_model.py](ai/irrigation_model.py) charge ce fichier. Il accepte les noms du projet (`soil_moisture`, `temperature`, `rainfall`, `wind`, `growth_stage`, `mulching`), borne les valeurs numériques hors plage et lève une `ValueError` si une valeur manque, n'est pas numérique ou si une modalité est inconnue. Dans ce cas, le serveur ne doit pas commander la vanne.
- Les probabilités renvoyées ne sont pas calibrées (poids de classes équilibrés) : elles servent à comparer les classes entre elles.

### 4.6 Décision de la vanne

Règles du mode automatique, implémentées dans [ai/valve_controller.py](ai/valve_controller.py) :

| Besoin prédit | Action |
|---|---|
| `Low` | Vanne fermée |
| `Medium` | Ouverture courte, puis réévaluation |
| `High` | Ouverture tant que le besoin reste `High`, fermeture dès qu'il redescend à `Medium` ou `Low` |

Paramètres par défaut (modifiables via `ValveConfig`) :

| Paramètre | Valeur par défaut |
|---|---|
| Ouverture courte (`Medium`) | 5 min |
| Durée maximale d'ouverture continue | 15 min |
| Délai minimal entre deux ouvertures | 10 min |
| Âge maximal des mesures | 5 min |

Comportements de sécurité :
- Sans décision fiable du modèle (donnée manquante, erreur) ou avec des mesures trop anciennes, la vanne est fermée.
- Une ouverture courte qui devient `High` se prolonge ; une ouverture `High` se ferme quand le besoin redescend.
- Au redémarrage du serveur, une vanne déjà ouverte est reprise comme une ouverture courte (`sync`).
- En mode manuel, le serveur ne décide rien et réinitialise le contrôleur.

Le contrôleur ne dépend ni de Firebase ni du modèle : il reçoit le besoin prédit et l'heure, et renvoie une décision. 

**Intégration au serveur** ([ai/irrigation_service.py](ai/irrigation_service.py), appelé par [ai/server.py](ai/server.py) à chaque cycle) :
1. Lecture de `/valve/mode`, `/sensors`, `/weather`, `/field` et `/valve/state`.
2. Prédiction du besoin par le modèle (`soil_moisture` et `temperature` viennent de l'ESP32, `rainfall` et `wind` de la météo simulée, `growth_stage` et `mulching` des réglages de la parcelle).
3. Mode `auto` : le contrôleur décide et le serveur écrit `/valve/command` à chaque cycle (la commande reste ainsi cohérente avec la décision). Mode `manual`, ou mode absent : aucune commande n'est envoyée, le contrôleur est réinitialisé, mais la recommandation reste publiée.
4. Publication dans `/ai/irrigation` : besoin, scores, action, raison, éventuelle erreur, valeurs utilisées et horodatage.

**Fraîcheur des mesures :** l'ESP32 écrit une entrée dans `/history` chaque minute. Le serveur surveille la signature de la dernière entrée. Tant qu'aucun changement n'a été observé (par exemple juste après son démarrage), ou si plus rien ne change depuis plus de 5 minutes, les mesures sont jugées trop anciennes et la vanne est fermée. Après un démarrage, il faut donc compter une à deux minutes avant la première décision.

**Réglages manquants :** si la pluie, le vent, le stade de croissance ou le paillage ne sont pas définis, le modèle refuse de décider, la vanne reste fermée en mode automatique et le tableau de bord indique les valeurs manquantes.

**Accès à Firebase :** le service utilise l'API REST sans jeton, ce qui suppose les règles ouvertes actuelles. Avec des règles restreintes, il faudra ajouter l'authentification dans `FirebaseRest._params()`.

Limite de la simulation : dans Wokwi, l'humidité du sol est un potentiomètre réglé à la main, elle ne remonte pas quand la vanne s'ouvre. Tant que le sol n'est pas simulé, un besoin `High` persistant produit des cycles « ouverture maximale, attente, réouverture ».

Si le serveur ou le réseau tombe, la vanne ne reste pas ouverte : l'ESP32 applique ses propres garde-fous (durée maximale de 20 min, perte de liaison de 5 min), voir [4.1](#41-microcontrôleur-et-capteurs).

### 4.7 API REST en lecture seule

[ai/api.py](ai/api.py) expose avec FastAPI ce que l'ESP32 et le serveur IA publient dans Firebase, ainsi que l'historique agricole de Firestore. C'est un processus **séparé** de `server.py` : l'API n'écrit jamais rien et ne commande jamais la vanne, donc une panne de l'API ne touche pas à l'irrigation. Les commandes (mode, vanne manuelle, réglages) restent réservées au tableau de bord.

| Route | Contenu | Source |
|---|---|---|
| `GET /health` | état de l'API, de la Realtime Database (`firebase`) et de la configuration Firestore (`firestore`) ; répond 503 si Firebase est injoignable | Firebase |
| `GET /sensors` | dernière mesure : température, humidité, humidité du sol, pH, luminosité | `/sensors` |
| `GET /prediction` | prédiction température/humidité, `age_s` (âge en secondes) et qualité du modèle (`status`) | `/ai/prediction`, `/ai/status` |
| `GET /irrigation` | besoin, scores, action de la vanne, raison, mode, `age_s` | `/ai/irrigation` |
| `GET /history/daily?days=7` | résumés journaliers, du plus récent au plus ancien (`days` de 1 à 90) | Firestore `daily_summaries` |
| `GET /history/events?limit=20` | ouvertures de la vanne, de la plus récente à la plus ancienne (`limit` de 1 à 200) | Firestore `irrigation_events` |

Codes d'erreur : 404 si la donnée n'existe pas encore (serveur IA jamais lancé), 422 si un paramètre est hors limites, 502 si Firebase ou Firestore est injoignable, 503 si l'historique n'est pas configuré (`FIRESTORE_CREDENTIALS` absent). Toute autre méthode que `GET` donne 405. La documentation interactive est générée sur `/docs`.

Limite : l'API n'a **aucune authentification** et n'écoute par défaut que sur la machine locale (`127.0.0.1`). Il faut l'authentifier avant de l'exposer sur un réseau.

---

## 5. Structure des fichiers

```
.
├── src/main.cpp          Code de l'ESP32
├── diagram.json          Schéma du circuit Wokwi
├── platformio.ini        Configuration PlatformIO
├── index.html            Tableau de bord web
├── firebase.json         Configuration Firebase Hosting et Firestore
├── firestore.rules       Règles Firestore (lecture seule de l'historique)
├── firestore.indexes.json Index Firestore (aucun index composite nécessaire)
├── .gitignore            Exclut .venv, .env, clés, modèles générés, jeux de données et rapports
├── .venv/                Environnement virtuel Python (non versionné)
└── ai/
    ├── server.py         Serveur d'entraînement en continu
    ├── sensor_ai.py      Données, modèle, prédiction
    ├── explore_dataset.py  Exploration du jeu d'irrigation Kaggle
    ├── train_irrigation.py Comparaison des modèles d'irrigation
    ├── train_final.py    Validation croisée et entraînement du modèle final
    ├── irrigation_model.py Prédiction du besoin (bornage, validation des entrées)
    ├── valve_controller.py Décision de la vanne (machine à états)
    ├── test_valve_controller.py Tests PyTest de la décision de la vanne
    ├── irrigation_service.py Service d'irrigation (Firebase REST, fraîcheur, cycle de décision)
    ├── test_irrigation_service.py Tests PyTest du service et de l'accès REST
    ├── history_store.py  Historique agricole dans Firestore (événements de vanne, résumés)
    ├── test_history_store.py Tests PyTest de l'historique (Firestore simulé)
    ├── test_irrigation_model.py Tests PyTest de la prédiction d'irrigation (bornage, validation, cohérence)
    ├── test_sensor_ai.py Tests PyTest de la prédiction température/humidité (lecture, entraînement, écriture)
    ├── api.py            API REST en lecture seule (FastAPI)
    ├── test_api.py       Tests PyTest de l'API (Firebase et Firestore simulés)
    ├── service-account.json Clé de compte de service Firestore (non versionnée)
    ├── requirements.txt  Dépendances Python
    ├── data/             Jeux de données Kaggle (train.csv), non versionné
    ├── reports/          Rapports et graphiques (exploration, comparaison), non versionné
    ├── models/           Modèles entraînés (.joblib), non versionné
    ├── .env              Configuration locale (non versionné)
    └── .env.example      Modèle de configuration
```

---

## 6. Installation et lancement

### 6.1 Prérequis
- Python 3.12+ et un environnement virtuel
- Une Realtime Database Firebase active, et une base Firestore créée dans le même projet
- PlatformIO (ou Wokwi) pour l'ESP32
- Un compte Kaggle pour télécharger le jeu de données d'irrigation

### 6.2 Dépendances de l'ESP32
Dans `platformio.ini`, sous la section `[env:...]` :

```ini
lib_deps =
    adafruit/DHT sensor library
    adafruit/Adafruit Unified Sensor
    madhephaestus/ESP32Servo
```

### 6.3 Configuration du serveur
Le fichier `ai/.env` doit contenir :

```env
FIREBASE_DATABASE_URL=https://oct-stage-default-rtdb.firebaseio.com
FIREBASE_API_KEY=your-firebase-api-key
FIRESTORE_CREDENTIALS=service-account.json
```

`FIRESTORE_CREDENTIALS` désigne la clé de compte de service (chemin relatif au dossier `ai/`). Pour la générer : console Firebase, Paramètres du projet, Comptes de service, « Générer une nouvelle clé privée », puis l'enregistrer sous `ai/service-account.json`. Ce fichier donne un accès complet au projet : il ne doit jamais être versionné (voir [la section 7](#7-sécurité-et-bonnes-pratiques)). Sans cette variable, le serveur démarre quand même, sans historique Firestore.

### 6.4 Récupérer le jeu de données
1. Se connecter à Kaggle, ouvrir la page de la compétition `playground-series-s6e4` et accepter ses règles (condition du téléchargement).
2. Onglet **Data**, puis **Download All**, et dézipper.
3. Placer `train.csv` dans `ai/data/`. Le fichier `test.csv` n'a pas de colonne cible et n'est pas utilisé.

Alternative en ligne de commande (nécessite un jeton d'API Kaggle, à ne jamais versionner) :

```powershell
python -m pip install kaggle
kaggle competitions download -c playground-series-s6e4
Expand-Archive playground-series-s6e4.zip -DestinationPath ai\data
```

Vérification rapide :

```powershell
cd ai
python -c "import pandas as pd; df = pd.read_csv('data/train.csv'); print(df.shape); print(df['Irrigation_Need'].value_counts(normalize=True))"
```

Résultat attendu : `(630000, 21)` et environ 58,7 % de `Low`, 37,9 % de `Medium`, 3,3 % de `High`.

Exploration complète (nécessite `pandas`, `scikit-learn` et `matplotlib`) :

```powershell
python explore_dataset.py --sample 100000
```

Le rapport est écrit dans `ai/reports/exploration.txt` et les graphiques dans `ai/reports/`. Sans `--sample`, tout le fichier est analysé (plus lent).

Comparaison des modèles :

```powershell
python train_irrigation.py --sample 200000
```

Sans `--sample`, le jeu complet est utilisé (plusieurs minutes). Options : `--no-ablation` pour ignorer l'ablation, `--no-save` pour ne pas sauvegarder les modèles. Résultats dans `ai/reports/model_comparison.txt` et `.csv`, matrices de confusion dans `ai/reports/confusion_*.png`, modèles dans `ai/models/`.

Modèle final et prédiction :

```powershell
python train_final.py --sample 200000   # essai rapide
python train_final.py                   # jeu complet (plusieurs minutes)
python irrigation_model.py              # test de la prédiction
```

Logique de la vanne :

```powershell
python valve_controller.py              # démonstration de scénarios
python -m pip install pytest
python -m pytest -v                     # tous les tests (vanne, service d'irrigation, historique, modèles, API)
```

### 6.5 Lancer le serveur IA

```powershell
.\.venv\Scripts\Activate.ps1
cd ai
python -m pip install -r requirements.txt
python server.py
```

Le venv se trouve à la racine du projet. Toujours installer avec `python -m pip` : un venv contient des chemins en dur, donc après le renommage du dossier du projet, `pip.exe` ne fonctionne plus. Dans ce cas, recréer le venv (`python -m venv .venv`) puis réinstaller les dépendances.

Entraînement ponctuel : `python sensor_ai.py`. Test sans Firebase : `python sensor_ai.py --demo`.

Historique Firestore : le message « Historique Firestore activé » doit apparaître au démarrage. Le résumé journalier n'est écrit que toutes les 10 minutes ; pour tester plus vite, lancer `python server.py --history-flush 60`. Les documents apparaissent ensuite dans la console Firebase (Firestore Database, collections `irrigation_events` et `daily_summaries`). `--no-history` désactive cette partie.

### 6.6 Lancer la simulation et le tableau de bord
- Simulation : ouvrir le projet dans Wokwi et la démarrer. Elle doit rester active pour que les mesures arrivent.
- Règles Firestore, à publier une première fois puis à chaque modification de `firestore.rules` : `firebase deploy --only firestore`. Tant qu'elles ne sont pas publiées, la base garde les règles choisies à sa création (mode test : ouvert pour une durée limitée) et le panneau « Historique agricole » peut afficher une erreur d'accès.
- Tableau de bord : ouvrir `index.html` dans un navigateur, ou le publier avec `firebase deploy --only hosting`.

### 6.7 Essai de bout en bout de l'irrigation

1. Lancer le serveur (il charge `ai/models/irrigation_final.joblib`) : `python server.py`. Le message « Décision d'irrigation activée » doit apparaître. `python server.py --no-irrigation` désactive cette partie.
2. Démarrer la simulation Wokwi et ouvrir le tableau de bord.
3. Dans « Parcelle et météo simulée », renseigner le stade de croissance, le paillage, la pluie et le vent. Tant qu'une valeur manque, la vanne reste fermée en mode automatique.
4. Le mode passe automatiquement à **Automatique** à chaque démarrage de l'ESP32. Le panneau « Irrigation » permet de passer en Manuel et de revenir en Automatique. Sans mode défini, le serveur ne commande rien.
5. Dans Wokwi, régler une humidité du sol basse et une température élevée.
6. Attendre une à deux minutes : le serveur doit d'abord observer une nouvelle entrée de `/history`. La recommandation, puis l'ouverture de la vanne, apparaissent ensuite sur le tableau de bord.
7. Passer en mode **Manuel** : le serveur n'envoie plus de commande et le bouton de commande manuelle devient actif.
8. Test des garde-fous : en mode manuel, ouvrir la vanne. Au bout de 20 min, elle se ferme seule et le moniteur série affiche « SECURITE : duree maximale d'ouverture atteinte ». Pour un essai plus court, réduire temporairement `VALVE_MAX_OPEN_MS` dans `src/main.cpp`.

Rappel : les potentiomètres de Wokwi dépassent la plage d'entraînement du modèle. Les valeurs hors plage sont bornées (`Soil_Moisture` à [8, 64,99], `Temperature_C` à [12, 42]).

### 6.8 Lancer l'API

Dans un second terminal, avec le venv activé et le serveur IA lancé ou non (l'API est indépendante) :

```powershell
cd ai
python -m pip install -r requirements.txt
python -m uvicorn api:create_app --factory --port 8000
```

`python api.py` est équivalent ; l'adresse et le port se règlent avec les variables `API_HOST` (127.0.0.1 par défaut) et `API_PORT` (8000). Ouvrir ensuite http://127.0.0.1:8000/docs pour essayer les routes, ou par exemple :

```powershell
curl http://127.0.0.1:8000/health
curl "http://127.0.0.1:8000/history/daily?days=3"
```

Sans `FIRESTORE_CREDENTIALS` dans `ai/.env`, les routes `/history/*` répondent 503 ; les autres fonctionnent.

---

## 7. Sécurité et bonnes pratiques

- Les règles actuelles de la base sont ouvertes, ce qui convient à un TP mais pas à une utilisation réelle. Elles doivent être restreintes avant tout déploiement, ce qui impose d'authentifier l'ESP32, le serveur et le tableau de bord.
- Ne jamais versionner `ai/.env`, une clé de compte de service Firebase ni le jeton d'API Kaggle (`kaggle.json`) : le `.gitignore` doit les exclure.
- Ne pas versionner `ai/data/` : le fichier est volumineux et sa redistribution dépend de la licence de Kaggle. Chaque utilisateur le télécharge lui-même.
- `firebase.json` doit n'héberger que la page web : `.venv`, `ai/` et `src/` sont exclus du déploiement, ainsi que `firestore.rules`, `firestore.indexes.json` et tout fichier `service-account*.json`.
- L'API (`ai/api.py`) est en lecture seule, mais sans authentification : ne pas la publier hors de la machine locale (`API_HOST=0.0.0.0`, Docker, réseau) avant d'y ajouter une authentification.
- Les règles Firestore ferment toute écriture aux clients. La lecture de l'historique reste publique tant que le tableau de bord n'est pas authentifié.
- Utiliser un environnement virtuel pour les dépendances Python.

Entrées à ajouter au `.gitignore` :

```
ai/data/
ai/reports/
ai/models/
ai/service-account.json
kaggle.json
```

---

## 8. Feuille de route

| Élément | État |
|---|---|
| Acquisition DHT22 + sol, pH, luminosité | Fait (simulation à valider) |
| Vanne pilotée par servomoteur | Fait (côté ESP32) |
| Garde-fous de la vanne côté ESP32 (durée maximale, perte de liaison) | Fait, à valider en simulation : logique testée hors carte (5 scénarios) |
| Historique Firebase et tableau de bord de base | Fait |
| Prédiction température/humidité | Fait |
| Jeu de données d'irrigation (Kaggle) | Fait : Playground Series S6E4, 630 000 lignes, cible Low/Medium/High (jeu synthétique, classes déséquilibrées) |
| Exploration du jeu (valeurs manquantes, importance des variables) | Fait : données propres, variables clés identifiées (humidité du sol, stade de croissance, température, vent, pluie, paillage) |
| Comparaison des algorithmes et des jeux de variables (A, B, ALL) avec ablation | Fait : Gradient Boosting sur B retenu provisoirement (balanced accuracy 0,965 ; 0,731 avec les capteurs seuls) |
| Modèle final : 6 variables, validation croisée, jeu complet, module de prédiction avec bornage | Fait : Gradient Boosting, balanced accuracy 0,969 ± 0,001 |
| Logique de décision de la vanne (règles, garde-fous, tests) | Fait : `valve_controller.py`, 16 tests |
| Intégration au serveur : nœuds `/weather`, `/field`, `/ai/irrigation`, commande de la vanne | Fait, à valider en simulation : `irrigation_service.py` intégré à `server.py`, 15 tests |
| Tableau de bord : état du sol, météo simulée, vanne, recommandations | Fait, à valider en simulation : météo et réglages de parcelle saisis à la main |
| Météo simulée automatique et simulateur de sol (humidité qui remonte quand la vanne s'ouvre) | À venir (optionnel) |
| Firestore pour l'historique agricole (événements de vanne, résumés journaliers) | Fait côté serveur, à valider avec la base réelle : `history_store.py` intégré à `server.py`, 12 tests. Panneau « Historique agricole » du tableau de bord et règles `firestore.rules` faits, à valider avec la base réelle |
| API du serveur (FastAPI) et tests API | Fait : API en lecture seule (`api.py`, 6 routes) et 49 tests ; authentification et routes de commande non faites |
| Tests PyTest et validation du modèle | Fait : 167 tests (vanne 16, service d'irrigation et accès REST 15, historique Firestore 12, prédiction d'irrigation 35 dont 4 qui exigent `models/irrigation_final.joblib`, prédiction température/humidité 40, API 49) |
| Docker et intégration continue GitHub | À venir |