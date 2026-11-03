# TODO — Aperçu animé de la parcelle

## Objectif

Ajouter au tableau de bord un aperçu visuel, animé et accessible de la parcelle. La scène doit résumer les mesures et états déjà disponibles dans Firebase : humidité, pH et luminosité du sol, stade de croissance, paillage, pluie, vent, recommandation d'irrigation et état de la vanne.

L'illustration doit rester une représentation indicative : elle ne remplace ni les valeurs chiffrées ni l'état confirmé par l'ESP32. Ne pas inventer de mesure ou présenter une commande comme une confirmation physique.

## 1. Préparer l'intégration

- [ ] Repérer dans `index.html` l'emplacement du nouvel aperçu. Le placer près de « Parcelle et météo simulée » et de « Irrigation », pour que les commandes et leur effet visuel soient faciles à comparer.
- [ ] Ajouter une section dédiée, avec un titre tel que « Aperçu de la parcelle », un sous-titre explicatif et un conteneur SVG responsive.
- [ ] Réutiliser les abonnements Firebase déjà présents dans `index.html`, sans créer de seconde connexion ni de seconde logique métier.
- [ ] Créer une fonction unique de mise à jour visuelle, appelée lorsque les valeurs pertinentes changent. Elle reçoit les dernières données disponibles et met à jour les éléments SVG et les libellés associés.
- [ ] Garder le SVG dans le HTML (SVG en ligne) afin de pouvoir modifier ses éléments depuis JavaScript, appliquer les styles CSS et fournir des libellés accessibles.
- [ ] Donner des identifiants stables aux éléments qui changent d'état (sol, plante, nuages, pluie, vent, vanne, eau). Éviter de reconstruire tout le SVG à chaque mise à jour.
- [ ] Conserver les cartes, graphiques et commandes existants ; l'aperçu les complète et ne les remplace pas.
- [ ] Ne pas ajouter de dépendance externe pour les illustrations ou animations.

## 2. Définir la scène SVG

- [ ] Dessiner une scène de parcelle lisible sur fond clair ou sombre et cohérente avec le thème actuel du tableau de bord.
- [ ] Organiser le SVG en groupes logiques : ciel, météo, plantes, surface, couches de sol, paillage, réseau d'irrigation, vanne et eau.
- [ ] Créer les formes avec des tracés simples et reconnaissables, des contours nets et une palette limitée. Prévoir un contraste suffisant avec le fond du tableau de bord.
- [ ] Utiliser un `viewBox` stable et des dimensions CSS fluides (`width: 100%`, hauteur adaptée) afin que la scène reste nette sur écrans haute densité et s'adapte à la largeur disponible.
- [ ] Ajouter une légende ou des libellés courts pour les états dont le sens n'est pas évident. Ne pas compter uniquement sur la couleur ou le mouvement pour communiquer une information.
- [ ] Prévoir un état neutre « données en attente » : scène immobile, couleurs neutres et texte explicite lorsque les mesures ne sont pas encore disponibles.

## 3. Dessiner et représenter le sol

- [ ] Dessiner une coupe de terrain avec une surface de parcelle et plusieurs couches de terre différenciées par des aplats et de légères variations de texture.
- [ ] Représenter l'humidité du sol (`/sensors/soil_moisture`) de façon progressive : sol plus clair/sec aux faibles valeurs, plus sombre et plus riche en couleur aux valeurs élevées. Afficher aussi la valeur en pourcentage.
- [ ] Définir des seuils visuels explicites et centralisés pour les états « sec », « intermédiaire » et « humide ». Les seuils doivent être ajustables après essai avec les mesures réelles ; ne pas les présenter comme des seuils agronomiques validés.
- [ ] Modifier l'apparence du sol progressivement, sans bascule brutale entre couleurs lorsque la mesure varie légèrement.
- [ ] Représenter le pH (`/sensors/ph`) par un indicateur ou une petite échelle dédiée plutôt que de suggérer qu'une couleur de terre correspond à une valeur de pH précise. Afficher « en attente » si la mesure manque.
- [ ] Représenter le paillage (`/field/mulching`) par une couche visible de paille ou de couverture à la surface du sol ; le retirer visuellement lorsque le paillage est désactivé.
- [ ] Afficher un état distinct quand une donnée est manquante ou invalide : ne pas réutiliser la dernière valeur comme si elle était actuelle.
- [ ] Ne pas simuler une remontée de l'humidité après arrosage tant que le simulateur de sol n'est pas implémenté et qu'aucune nouvelle mesure ne le confirme.

## 4. Dessiner et représenter les plantes

- [ ] Créer une plante SVG simple, composée de formes réutilisables (tige, feuilles, racines et éventuellement fleur/fruits), placée au-dessus et sous la surface.
- [ ] Faire correspondre `/field/growth_stage` aux apparences suivantes :
  - [ ] `Sowing` : semis ou jeune pousse, très peu développée.
  - [ ] `Vegetative` : plante feuillue en croissance, tige et feuilles visibles.
  - [ ] `Flowering` : plante développée avec fleurs stylisées.
  - [ ] `Harvest` : plante mature, avec fruits/récolte stylisés si cela correspond à la culture choisie.
- [ ] Ajouter un libellé français du stade sous ou à côté de la scène, avec un état « non défini » si la valeur n'est pas renseignée.
- [ ] Garder les formes schématiques et génériques : ne pas faire croire que le système identifie une espèce végétale si aucune culture n'est configurée.
- [ ] Animer éventuellement un très léger mouvement des feuilles, sans mouvement permanent excessif.

## 5. Dessiner et représenter le ciel et la météo

- [ ] Ajouter un ciel, un soleil et un ou plusieurs nuages en SVG, avec un contraste compatible avec le thème sombre.
- [ ] Faire varier l'aspect du ciel selon la luminosité (`/sensors/light`) si cette mesure est disponible ; sinon, garder un état neutre et ne pas inventer d'heure ou de conditions météorologiques.
- [ ] Représenter la pluie cumulée (`/weather/rainfall`) par des gouttes visibles seulement lorsque la valeur est supérieure à zéro. Afficher la valeur numérique en millimètres.
- [ ] Distinguer visuellement « pluie saisie/simulée » de « pluie mesurée par une station météo » dans un libellé, puisque la météo actuelle est saisie à la main.
- [ ] Faire varier l'intensité ou le nombre de gouttes par paliers visuels, sans tenter de représenter chaque millimètre à l'échelle.
- [ ] Représenter le vent (`/weather/wind`) avec de légères lignes de flux et un mouvement des feuilles proportionnel par paliers. Afficher la vitesse en km/h.
- [ ] Garder les nuages décoratifs si leur état n'est pas issu d'une donnée. Ne pas attribuer automatiquement un type de nuage ou une prévision météo au cumul de pluie et au vent.
- [ ] Prévoir les états « météo non renseignée » et « météo simulée » afin que l'absence de pluie ne soit pas confondue avec une mesure réelle de temps sec.

## 6. Dessiner et représenter la vanne et l'arrosage

- [ ] Dessiner une vanne reconnaissable sur un tuyau d'irrigation, avec deux positions ou états visuels distincts : fermée et ouverte.
- [ ] Utiliser l'état réel confirmé par `/valve/state` comme source principale de l'illustration de la vanne.
- [ ] Lorsque seul `/valve/command` est connu, afficher « ouverture/fermeture demandée » ou « en attente de confirmation » ; ne pas montrer une ouverture physique comme confirmée.
- [ ] Distinguer clairement les états « ouverte », « fermée », « état inconnu » et « commande en attente ». Ajouter un libellé textuel en plus de la couleur.
- [ ] Dessiner un arroseur ou des goutteurs raccordés au tuyau. Le style doit rester schématique et clairement explicatif, pas photoréaliste.
- [ ] Montrer des jets ou gouttes d'arrosage uniquement quand `/valve/state` confirme que la vanne est ouverte. Les arrêter lorsque la vanne est confirmée fermée.
- [ ] Si la vanne est commandée mais pas encore confirmée, utiliser au besoin une animation d'attente discrète différente des jets d'eau (par exemple un contour pulsé de la vanne) et un libellé explicite.
- [ ] Mettre en évidence le trajet de l'eau dans le tuyau et les gouttes qui atteignent le sol pendant l'arrosage confirmé.
- [ ] Ne pas faire évoluer artificiellement le niveau d'humidité du sol en réponse à l'animation. L'humidité affichée doit toujours correspondre à la dernière mesure reçue.
- [ ] Afficher si possible le mode automatique ou manuel et le besoin d'irrigation (faible, moyen, élevé) près de la scène, sans confondre recommandation du modèle et commande effective.
- [ ] Respecter les garde-fous existants : l'illustration ne doit jamais écrire dans Firebase ni commander la vanne.

## 7. Brancher les données et gérer les états

- [ ] Relier les éléments visuels aux sources existantes :
  - [ ] Humidité du sol : `/sensors/soil_moisture`.
  - [ ] pH : `/sensors/ph`.
  - [ ] Luminosité : `/sensors/light`.
  - [ ] Stade et paillage : `/field/growth_stage` et `/field/mulching`.
  - [ ] Pluie et vent : `/weather/rainfall` et `/weather/wind`.
  - [ ] État confirmé de la vanne : `/valve/state`.
  - [ ] Commande et mode : `/valve/command` et `/valve/mode`.
  - [ ] Recommandation : `/ai/irrigation`.
- [ ] Vérifier les noms exacts et le format des champs capteurs dans le code avant l'intégration ; réutiliser les références Firebase déjà présentes plutôt que supposer un nouveau schéma.
- [ ] Initialiser chaque état à « inconnu/en attente » avant la première réponse Firebase.
- [ ] Gérer les abonnements qui ne renvoient pas encore de valeur, les champs `null`, les nombres non finis et les valeurs hors plage avec un état visuel neutre et un message explicite.
- [ ] Ne pas conserver une apparence active après une déconnexion ou une donnée devenue indisponible sans indiquer que l'information est ancienne/inconnue.
- [ ] Mettre à jour la scène sans interrompre les contrôles manuels ni réinitialiser les champs de saisie.
- [ ] Éviter d'injecter dans le SVG du contenu provenant de Firebase comme du balisage HTML ; utiliser des attributs et du texte contrôlés par l'application.

## 8. Animation, accessibilité et performance

- [ ] Réaliser les animations avec CSS (transitions ou keyframes) appliqué aux groupes SVG ; réserver JavaScript aux changements d'état induits par les données.
- [ ] Animer avec modération : pluie, flux d'eau, rotation/mouvement léger d'un arroseur ou des feuilles. Les animations doivent rester lentes et non distrayantes.
- [ ] Respecter `prefers-reduced-motion: reduce` : désactiver les mouvements décoratifs et transitions non essentielles tout en gardant visibles les états.
- [ ] Ajouter un titre et une description SVG accessibles (`<title>` et `<desc>`) et un nom accessible à la section.
- [ ] Rendre la scène compréhensible au clavier et par lecteur d'écran ; l'illustration informative ne doit pas être totalement masquée aux technologies d'assistance.
- [ ] Assurer le contraste des libellés et des états, y compris les couleurs d'alerte et les états désactivés.
- [ ] Vérifier l'affichage sur mobile, tablette et grand écran ; éviter les textes coupés, le débordement horizontal et les éléments trop petits.
- [ ] Vérifier que les animations ne dégradent pas les performances et ne déclenchent pas de rendu complet permanent.

## 9. Vérification et critères d'acceptation

- [ ] Vérifier la scène sans données Firebase : elle affiche un état d'attente cohérent et aucune fausse mesure.
- [ ] Vérifier séparément les valeurs basses, intermédiaires et hautes d'humidité, de luminosité, de pluie et de vent.
- [ ] Vérifier chacun des quatre stades de croissance, paillage activé/désactivé, et pH absent/présent.
- [ ] Vérifier vanne fermée, ouverte confirmée, commande en attente, état inconnu et mode automatique/manuel.
- [ ] Vérifier que seule une vanne réellement confirmée ouverte déclenche l'animation d'arrosage.
- [ ] Vérifier que l'humidité affichée ne change qu'à réception d'une nouvelle mesure, pas en raison des seules animations.
- [ ] Vérifier l'apparence en cas de perte de connexion, de données manquantes ou invalides et de retour de connexion.
- [ ] Vérifier la lisibilité sur mobile et avec la réduction des animations activée dans le système.
- [ ] Vérifier qu'aucun contrôle existant du tableau de bord n'a régressé et que l'aperçu ne modifie aucune donnée Firebase.
- [ ] Tester sur le déploiement Firebase Hosting après validation locale.

## Ordre suggéré

1. Construire la scène SVG statique et vérifier sa mise en page responsive.
2. Relier les valeurs et ajouter les états en attente/manquants.
3. Ajouter les variantes du sol, de la plante, du ciel et du paillage.
4. Ajouter la vanne, puis l'arrosage basé exclusivement sur l'état confirmé.
5. Ajouter les animations réduites, l'accessibilité et les vérifications de bout en bout.
