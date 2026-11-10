# TODO — Aperçu animé de la parcelle

## Objectif

Ajouter au tableau de bord un aperçu visuel, animé et accessible de la parcelle. La scène doit résumer les mesures et états déjà disponibles dans Firebase : humidité, pH et luminosité du sol, stade de croissance, paillage, pluie, vent, recommandation d'irrigation et état de la vanne.

L'illustration doit rester une représentation indicative : elle ne remplace ni les valeurs chiffrées ni l'état confirmé par l'ESP32. Ne pas inventer de mesure ou présenter une commande comme une confirmation physique.

## 1. Préparer l'intégration

- [x] Repérer dans `index.html` l'emplacement du nouvel aperçu. Le placer près de « Parcelle et météo simulée » et de « Irrigation », pour que les commandes et leur effet visuel soient faciles à comparer.
- [x] Ajouter une section dédiée, avec un titre tel que « Aperçu de la parcelle », un sous-titre explicatif et un conteneur SVG responsive.
- [x] Réutiliser les abonnements Firebase déjà présents dans `index.html`, sans créer de seconde connexion ni de seconde logique métier.
- [x] Créer une fonction unique de mise à jour visuelle, appelée lorsque les valeurs pertinentes changent. Elle reçoit les dernières données disponibles et met à jour les éléments SVG et les libellés associés.
- [x] Garder le SVG dans le HTML (SVG en ligne) afin de pouvoir modifier ses éléments depuis JavaScript, appliquer les styles CSS et fournir des libellés accessibles.
- [x] Donner des identifiants stables aux éléments qui changent d'état (sol, plante, nuages, pluie, vent, vanne, eau). Éviter de reconstruire tout le SVG à chaque mise à jour. *(ids : `sceneSvg`, `soil1-3`, `stage-*`, `mulch`, `sceneRainG`, `sceneWindG`, `valveLever`, `valvePending`…)*
- [x] Conserver les cartes, graphiques et commandes existants ; l'aperçu les complète et ne les remplace pas.
- [x] Ne pas ajouter de dépendance externe pour les illustrations ou animations.

## 2. Définir la scène SVG

- [x] Dessiner une scène de parcelle lisible sur fond clair ou sombre et cohérente avec le thème actuel du tableau de bord.
- [x] Organiser le SVG en groupes logiques : ciel, météo, plantes, surface, couches de sol, paillage, réseau d'irrigation, vanne et eau.
- [x] Créer les formes avec des tracés simples et reconnaissables, des contours nets et une palette limitée. Prévoir un contraste suffisant avec le fond du tableau de bord.
- [x] Utiliser un `viewBox` stable et des dimensions CSS fluides (`width: 100%`, hauteur adaptée) afin que la scène reste nette sur écrans haute densité et s'adapte à la largeur disponible.
- [x] Ajouter une légende ou des libellés courts pour les états dont le sens n'est pas évident. Ne pas compter uniquement sur la couleur ou le mouvement pour communiquer une information.
- [x] Prévoir un état neutre « données en attente » : scène immobile, couleurs neutres et texte explicite lorsque les mesures ne sont pas encore disponibles.

## 3. Dessiner et représenter le sol

- [x] Dessiner une coupe de terrain avec une surface de parcelle et plusieurs couches de terre différenciées par des aplats et de légères variations de texture.
- [x] Représenter l'humidité du sol (`/sensors/soil_moisture`) de façon progressive : sol plus clair/sec aux faibles valeurs, plus sombre et plus riche en couleur aux valeurs élevées. Afficher aussi la valeur en pourcentage.
- [x] Définir des seuils visuels explicites et centralisés pour les états « sec », « intermédiaire » et « humide ». Les seuils doivent être ajustables après essai avec les mesures réelles ; ne pas les présenter comme des seuils agronomiques validés. *(constante `VIZ` dans `index.html` : `soil`, `light`, `rain`, `wind`, `phScale`)*
- [x] Modifier l'apparence du sol progressivement, sans bascule brutale entre couleurs lorsque la mesure varie légèrement.
- [x] Représenter le pH (`/sensors/ph`) par un indicateur ou une petite échelle dédiée plutôt que de suggérer qu'une couleur de terre correspond à une valeur de pH précise. Afficher « en attente » si la mesure manque.
- [x] Représenter le paillage (`/field/mulching`) par une couche visible de paille ou de couverture à la surface du sol ; le retirer visuellement lorsque le paillage est désactivé.
- [x] Afficher un état distinct quand une donnée est manquante ou invalide : ne pas réutiliser la dernière valeur comme si elle était actuelle.
- [x] Ne pas simuler une remontée de l'humidité après arrosage tant que le simulateur de sol n'est pas implémenté et qu'aucune nouvelle mesure ne le confirme.

## 4. Dessiner et représenter les plantes

- [x] Créer une plante SVG simple, composée de formes réutilisables (tige, feuilles, racines et éventuellement fleur/fruits), placée au-dessus et sous la surface.
- [x] Faire correspondre `/field/growth_stage` aux apparences suivantes :
  - [x] `Sowing` : semis ou jeune pousse, très peu développée.
  - [x] `Vegetative` : plante feuillue en croissance, tige et feuilles visibles.
  - [x] `Flowering` : plante développée avec fleurs stylisées.
  - [x] `Harvest` : plante mature, avec fruits/récolte stylisés si cela correspond à la culture choisie.
- [x] Ajouter un libellé français du stade sous ou à côté de la scène, avec un état « non défini » si la valeur n'est pas renseignée.
- [x] Garder les formes schématiques et génériques : ne pas faire croire que le système identifie une espèce végétale si aucune culture n'est configurée.
- [x] Animer éventuellement un très léger mouvement des feuilles, sans mouvement permanent excessif. *(feuilles animées uniquement quand un vent est saisi, par paliers)*

## 5. Dessiner et représenter le ciel et la météo

- [x] Ajouter un ciel, un soleil et un ou plusieurs nuages en SVG, avec un contraste compatible avec le thème sombre.
- [x] Faire varier l'aspect du ciel selon la luminosité (`/sensors/light`) si cette mesure est disponible ; sinon, garder un état neutre et ne pas inventer d'heure ou de conditions météorologiques.
- [x] Représenter la pluie cumulée (`/weather/rainfall`) par des gouttes visibles seulement lorsque la valeur est supérieure à zéro. Afficher la valeur numérique en millimètres.
- [x] Distinguer visuellement « pluie saisie/simulée » de « pluie mesurée par une station météo » dans un libellé, puisque la météo actuelle est saisie à la main.
- [x] Faire varier l'intensité ou le nombre de gouttes par paliers visuels, sans tenter de représenter chaque millimètre à l'échelle.
- [x] Représenter le vent (`/weather/wind`) avec de légères lignes de flux et un mouvement des feuilles proportionnel par paliers. Afficher la vitesse en km/h.
- [x] Garder les nuages décoratifs si leur état n'est pas issu d'une donnée. Ne pas attribuer automatiquement un type de nuage ou une prévision météo au cumul de pluie et au vent. *(les nuages dérivent lentement et s'estompent avec la luminosité ; aucun type de nuage n'est déduit)*
- [x] Prévoir les états « météo non renseignée » et « météo simulée » afin que l'absence de pluie ne soit pas confondue avec une mesure réelle de temps sec.

## 6. Dessiner et représenter la vanne et l'arrosage

- [x] Dessiner une vanne reconnaissable sur un tuyau d'irrigation, avec deux positions ou états visuels distincts : fermée et ouverte.
- [x] Utiliser l'état réel confirmé par `/valve/state` comme source principale de l'illustration de la vanne.
- [x] Lorsque seul `/valve/command` est connu, afficher « ouverture/fermeture demandée » ou « en attente de confirmation » ; ne pas montrer une ouverture physique comme confirmée.
- [x] Distinguer clairement les états « ouverte », « fermée », « état inconnu » et « commande en attente ». Ajouter un libellé textuel en plus de la couleur.
- [x] Dessiner un arroseur ou des goutteurs raccordés au tuyau. Le style doit rester schématique et clairement explicatif, pas photoréaliste.
- [x] Montrer des jets ou gouttes d'arrosage uniquement quand `/valve/state` confirme que la vanne est ouverte. Les arrêter lorsque la vanne est confirmée fermée.
- [x] Si la vanne est commandée mais pas encore confirmée, utiliser au besoin une animation d'attente discrète différente des jets d'eau (par exemple un contour pulsé de la vanne) et un libellé explicite.
- [x] Mettre en évidence le trajet de l'eau dans le tuyau et les gouttes qui atteignent le sol pendant l'arrosage confirmé.
- [x] Ne pas faire évoluer artificiellement le niveau d'humidité du sol en réponse à l'animation. L'humidité affichée doit toujours correspondre à la dernière mesure reçue.
- [x] Afficher si possible le mode automatique ou manuel et le besoin d'irrigation (faible, moyen, élevé) près de la scène, sans confondre recommandation du modèle et commande effective.
- [x] Respecter les garde-fous existants : l'illustration ne doit jamais écrire dans Firebase ni commander la vanne.

## 7. Brancher les données et gérer les états

- [x] Relier les éléments visuels aux sources existantes :
  - [x] Humidité du sol : `/sensors/soil_moisture`.
  - [x] pH : `/sensors/ph`.
  - [x] Luminosité : `/sensors/light`.
  - [x] Stade et paillage : `/field/growth_stage` et `/field/mulching`.
  - [x] Pluie et vent : `/weather/rainfall` et `/weather/wind`.
  - [x] État confirmé de la vanne : `/valve/state`.
  - [x] Commande et mode : `/valve/command` et `/valve/mode`.
  - [x] Recommandation : `/ai/irrigation`.
- [x] Vérifier les noms exacts et le format des champs capteurs dans le code avant l'intégration ; réutiliser les références Firebase déjà présentes plutôt que supposer un nouveau schéma. *(`/valve/state` = `{open, angle}` ; seul un `open` booléen est traité comme confirmation)*
- [x] Initialiser chaque état à « inconnu/en attente » avant la première réponse Firebase.
- [x] Gérer les abonnements qui ne renvoient pas encore de valeur, les champs `null`, les nombres non finis et les valeurs hors plage avec un état visuel neutre et un message explicite.
- [x] Ne pas conserver une apparence active après une déconnexion ou une donnée devenue indisponible sans indiquer que l'information est ancienne/inconnue. *(hors ligne : scène grisée, animations coupées, bandeau d'alerte. Limite : sans horodatage de mesure, une valeur ancienne laissée dans la base par un ESP32 arrêté ne peut pas être détectée)*
- [x] Mettre à jour la scène sans interrompre les contrôles manuels ni réinitialiser les champs de saisie.
- [x] Éviter d'injecter dans le SVG du contenu provenant de Firebase comme du balisage HTML ; utiliser des attributs et du texte contrôlés par l'application.

## 8. Animation, accessibilité et performance

- [x] Réaliser les animations avec CSS (transitions ou keyframes) appliqué aux groupes SVG ; réserver JavaScript aux changements d'état induits par les données.
- [x] Animer avec modération : pluie, flux d'eau, rotation/mouvement léger d'un arroseur ou des feuilles. Les animations doivent rester lentes et non distrayantes.
- [x] Respecter `prefers-reduced-motion: reduce` : désactiver les mouvements décoratifs et transitions non essentielles tout en gardant visibles les états. *(vérifié par l'utilisateur dans le navigateur)*
- [x] Ajouter un titre et une description SVG accessibles (`<title>` et `<desc>`) et un nom accessible à la section.
- [x] Rendre la scène compréhensible au clavier et par lecteur d'écran ; l'illustration informative ne doit pas être totalement masquée aux technologies d'assistance. *(implémenté : `role="img"` + `<desc>` mis à jour + libellés en texte ; vérifié par l'utilisateur)*
- [x] Assurer le contraste des libellés et des états, y compris les couleurs d'alerte et les états désactivés. *(textes ≥ 5,6:1 ; éléments purement décoratifs — pluie sur ciel très clair, nuages, racines sur terre sèche — autour de 2,4 à 2,8:1, l'information étant aussi donnée en texte)*
- [x] Vérifier l'affichage sur mobile, tablette et grand écran ; éviter les textes coupés, le débordement horizontal et les éléments trop petits. *(vérifié par l'utilisateur dans le navigateur ; grille en une colonne sous 900 px, `viewBox` fluide)*
- [x] Vérifier que les animations ne dégradent pas les performances et ne déclenchent pas de rendu complet permanent. *(vérifié par l'utilisateur dans le navigateur ; animations limitées à `stroke-dashoffset`/`transform`/`opacity`, mises en pause hors écran)*

## 9. Vérification et critères d'acceptation

- [x] Vérifier la scène sans données Firebase : elle affiche un état d'attente cohérent et aucune fausse mesure. *(vérifié avec Firebase simulé, rendu statique et navigateur par l'utilisateur)*
- [x] Vérifier séparément les valeurs basses, intermédiaires et hautes d'humidité, de luminosité, de pluie et de vent. *(vérifié avec Firebase simulé : humidité 10/75, pluie 0/120/600, vent 0/8/15, luminosité 30/80/85)*
- [x] Vérifier chacun des quatre stades de croissance, paillage activé/désactivé, et pH absent/présent.
- [x] Vérifier vanne fermée, ouverte confirmée, commande en attente, état inconnu et mode automatique/manuel. *(y compris mode manuel et mode absent)*
- [x] Vérifier que seule une vanne réellement confirmée ouverte déclenche l'animation d'arrosage.
- [x] Vérifier que l'humidité affichée ne change qu'à réception d'une nouvelle mesure, pas en raison des seules animations.
- [x] Vérifier l'apparence en cas de perte de connexion, de données manquantes ou invalides et de retour de connexion. *(logique testée avec Firebase simulé et rendu vérifié par l'utilisateur dans le navigateur)*
- [x] Vérifier la lisibilité sur mobile et avec la réduction des animations activée dans le système. *(vérifié par l'utilisateur dans le navigateur)*
- [x] Vérifier qu'aucun contrôle existant du tableau de bord n'a régressé et que l'aperçu ne modifie aucune donnée Firebase. *(absence d'écriture par l'aperçu vérifiée dans le code ; contrôles existants retestés par l'utilisateur)*
- [x] Tester sur le déploiement Firebase Hosting après validation locale. *(validation confirmée par l'utilisateur)*

## Ordre d'implémentation réalisé

1. Construire la scène SVG statique et sa mise en page responsive.
2. Relier les valeurs et ajouter les états en attente/manquants.
3. Ajouter les variantes du sol, de la plante, du ciel et du paillage.
4. Ajouter la vanne, puis l'arrosage basé exclusivement sur l'état confirmé.
5. Ajouter les animations réduites, l'accessibilité et effectuer les vérifications de bout en bout.

## Notes d'implémentation

- Section « Aperçu de la parcelle » insérée entre « Irrigation / Parcelle et météo simulée » et « Historique des mesures » dans `index.html`. Tout est en lecture seule : l'aperçu n'appelle jamais `set()`.
- Les abonnements existants appellent `setViz(clé, valeur)` ; la scène est redessinée par la seule fonction `updateScene()` (au plus une fois par image).
- `undefined` = pas encore de réponse Firebase (« en attente »), `null` = réponse sans donnée (« pas de mesure »), valeur non finie ou hors plage = « invalide ». Aucune dernière valeur n'est réutilisée comme si elle était actuelle.
- Arrosage animé = `/valve/state.open === true` et connexion active. `/valve/command` seul affiche un anneau ambre pointillé et « demandée, en attente de confirmation ».
- À ajuster après essai réel : `VIZ` (seuils sol, luminosité, paliers de pluie et de vent, bornes de l'échelle de pH).