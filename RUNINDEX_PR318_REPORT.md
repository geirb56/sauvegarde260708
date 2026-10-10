# RUNINDEX — PR318 — Restructuration UX WorkoutDetail avant bêta

## Références exactes

- Base et HEAD de départ de `copilot/dev` : `65524421948976502cd51f108d8e427d9bd67f29`.
- HEAD canonique vérifié directement avec `git ls-remote origin refs/heads/copilot/dev`, identique au clone au départ.
- Branche de travail : `copilot/restructuration-ux-workout-detail`.
- HEAD d’implémentation testé : `d69dbaf7f94f2598ac3bc19cf1dedae152e850a6`.
- Ce rapport est ajouté après les vérifications ; le HEAD de livraison, incluant ce rapport, est indiqué dans la description de la PR.
- Une seule PR vers `copilot/dev` ; aucun merge automatique.

## Audit lecture seule et fichiers modifiés

Audit effectué avant modification : WorkoutDetail, Sessions, routes App, tests frontend existants, traductions, modèles et service Workout Analysis V2, roadmap canonique et documentation de déploiement.

Fichiers modifiés :

- `frontend/src/pages/WorkoutDetail.jsx`
- `frontend/src/lib/i18n.js`
- `frontend/src/lib/i18n.test.js`
- `frontend/src/__tests__/workout-analysis-v2-pages.test.jsx`
- `RUNINDEX_PR318_REPORT.md`

Aucun backend, moteur Workout Analysis, Training V2, prescription, calcul LT1/LT2 ou recalcul historique modifié. Aucun changement de `DetailedAnalysis.jsx`, `SessionDetail.jsx`, `Sessions.jsx` ou des routes.

## Structure avant / après

Avant : résumé V2, trois cartes intensité/volume/type, allure, comparaison récente, comparaison similaire, bouton Coach, puis interprétation/conseil/zones/splits/preuves/limites dans un bloc repliable.

Hiérarchie proposée avant modification puis implémentée :

1. **Résumé de séance** : nom, date, type, distance, durée, allure moyenne et FC moyenne disponible ; résumé V2 ou état explicite de chargement/indisponibilité/erreur.
2. **Ce qu’il faut retenir** : texte `meaning` visible ; volume/type existants et intensité uniquement si `available === true`.
3. **Allure et régularité** : valeurs `pacing` existantes, score et variabilité sans recalcul ; splits enregistrés immédiatement accessibles.
4. **Réponse cardiaque** : FC moyenne/maximale observées et distribution Z1–Z5 avec avertissement explicite de provenance/bornes inconnues et absence d’équivalence LT1/LT2.
5. **Comparaison historique** : références récente et similaire regroupées, périodes et effectifs distincts, différences descriptives, comparabilité et limites d’échantillons visibles.
6. **Conseil du coach** : texte `advice` visible et action conservée vers `/coach?analyze={id}`.
7. **Détails avancés** : preuves, version disponible et limitation technique d’intensité repliables, sans répéter interprétation/conseil/splits/comparaisons.

## Données réutilisées

Uniquement les requêtes existantes :

- `GET /workouts/{id}` : identité, date/type, distance, durée, allure moyenne, FC moyenne/maximale, `km_splits`.
- `GET /coach/workout-analysis/{id}?language={lang}` : résumé, signaux, interprétation, conseil, pacing, physiologie, comparaisons, preuves et version.

Les FC d’activité sont prioritaires lorsqu’exploitables, sinon les faits disponibles du moteur sont utilisés. Aucune conclusion physiologique supplémentaire ; aucune nouvelle dérive cardiaque affichée.

L’API V2 ne fournit pas la source ni les bornes des zones : l’interface le dit explicitement au lieu de leur attribuer une provenance Garmin ou des seuils individuels. Les descriptions « endurance », « seuil » etc. ont été retirées du graphique Z1–Z5.

Absence et erreur de chargement sont distinctes ; les métriques principales absentes ont un libellé explicatif, les écarts absents sont omis plutôt que convertis en zéro. Les signaux indisponibles ne sont pas présentés comme fiables.

Les deux requêtes restent indépendantes ; les splits et métriques restent consultables pendant un chargement/échec de l’analyse. AbortController et vérification du signal avant toute mise à jour protègent des réponses obsolètes, même si le transport ignore l’annulation.

## Mobile

- Conteneur limité en largeur, contenu textuel pouvant revenir à la ligne.
- Métriques et allure sur deux colonnes ; titres principaux lisibles et hiérarchie sémantique.
- Bouton Coach et ouverture des détails d’au moins 44 px.
- Splits sur lignes de 44 px, toutes les fractions valides conservées ; région à défilement vertical, accessible au clavier, sans interaction dépendant du survol.
- Splits invalides omis avec explication ; pas de moyenne historique recalculée.

Ces dispositions sont vérifiées dans les composants/tests DOM, mais ne constituent pas une validation visuelle à 360/390 px.

## Tests réellement exécutés

Depuis `frontend/`, dépendances existantes restaurées avec :

`npm ci --legacy-peer-deps --no-audit --no-fund`

Vérification finale au HEAD d’implémentation indiqué ci-dessus :

`CI=true npm test -- --watchAll=false --runInBand --forceExit --runTestsByPath src/__tests__/workout-analysis-v2-pages.test.jsx src/lib/i18n.test.js src/__tests__/app-legacy-redirects.test.jsx src/__tests__/sessions-page.test.jsx`

**Résultat : 4 suites réussies, 107 tests réussis, 0 échec.**

Couverture : métriques visibles, interprétation/conseil non repliés, preuves repliées, chargement et échec d’analyse, activité introuvable vs erreur réseau, analyse nulle, absence FC/splits/historique, données complètes, intensité strictement disponible, splits invalides et longues activités, réponses obsolètes après changement de route, contextes Coach, routes secondaires, références distinctes, arrondis et absence de fabrication.

Traductions FR/EN/ES : tests des titres, faits et avertissements, parité des clés et paramètres d’interpolation. Les textes du moteur restent réutilisés tels quels, sans analyse de leur contenu.

`npm run build`

**Résultat : compilation frontend réussie.** Avertissement existant : base Browserslist/caniuse-lite ancienne ; aucun package mis à jour dans cette PR.

`git diff --check`

**Résultat : aucun problème d’espacement.**

Les premières exécutions ont échoué sur les anciennes attentes de présentation repliée ; ces attentes liées à WorkoutDetail ont été adaptées, puis la commande finale ci-dessus a réellement réussi. Aucun test sans lien avec cette restructuration supprimé.

Contrôles :

- Scan de secrets sur les quatre fichiers frontend modifiés : aucun secret détecté.
- CodeQL JavaScript : exécuté, **0 alerte**.
- Revue automatique de `parallel_validation` : **indisponible** malgré son statut global de succès, car le modèle configuré n’existe pas dans le registre.
- Revue complémentaire en lecture seule par l’agent `code-review` : aucun problème significatif identifié.

## Limitations et risques de régression

- Pas de validation runtime Emergent, ni de test visuel réel sur mobile dans cette session.
- La provenance détaillée des zones ne peut pas être certifiée avec le contrat actuel ; aucune modification backend pour contourner cette limite.
- Les chaînes `reason_unavailable` viennent du moteur ; leur traduction dépend du langage de réponse du moteur, sans traduction ni interprétation locale.
- La variabilité est affichée comme valeur enregistrée du moteur, sans unité inventée.
- Aucun nouveau moteur ni indicateur scientifique calculé. Les conclusions existantes du moteur ne sont pas réécrites.
- Déplacement de sections et longueur des textes peuvent affecter la densité mobile : validation visuelle obligatoire.
- Les tests DOM ne démontrent pas l’absence de débordement horizontal dans un navigateur réel.
- Les journaux de tests incluent les avertissements existants de configuration backend en environnement de test et la notice Jest liée à `--forceExit`.

## Validation Emergent requise avant merge

- [ ] Sessions → `/workout/:id`, retour Sessions.
- [ ] Rendu mobile réel à 360 px et 390 px ; lisibilité, aucun débordement, défilement tactile des splits.
- [ ] Activité endurance.
- [ ] Activité fractionnée.
- [ ] Activité sans données cardiaques.
- [ ] Activité sans splits et sans historique.
- [ ] Activité avec comparaison historique : périodes/effectifs et limites visibles, pas de progrès implicite.
- [ ] Navigation Coach avec contexte exact de la séance.
- [ ] Routes `/workout/:id/analysis` et `/sessions/:id` toujours fonctionnelles.
- [ ] Chargement, absence de données et erreur réseau en environnement déployé.

Ne pas merger avant ces validations runtime.

## Corrections finales avant validation bêta — 10 octobre 2026

### HEAD et périmètre exacts

- Base cible inchangée : `copilot/dev`, `65524421948976502cd51f108d8e427d9bd67f29`.
- HEAD avant correction : `d75c0f689b72848dc7c7bbc5c8e314ea7879560a`.
- HEAD après correction fonctionnelle, correspondant au code testé : `0ca993a922b017051ddb5a13779e84d8f4ee3ad5`.
- Le commit suivant ajoute uniquement cette mise à jour documentaire ; son HEAD de livraison sera publié dans un commentaire sur la PR318 existante.
- Fichiers de cette correction : `frontend/src/pages/WorkoutDetail.jsx`, `frontend/src/lib/i18n.js`, `frontend/src/__tests__/workout-analysis-v2-pages.test.jsx`, `RUNINDEX_PR318_REPORT.md`.
- Aucun nouveau PR, aucun merge, aucun changement backend, Workout Analysis V2, Training V2 ou routes secondaires.

### P1 — Affichage selon le sport

**Cause :** la métrique du résumé utilisait toujours `avg_pace_min_km`, indépendamment de `workout.type`.

**Audit des types :** `WorkoutCreate.validate_type` dans `backend/server.py` autorise `run`, `cycle`, `swim`. `backend/garmin/service.py` normalise running/trail_running/treadmill_running vers `run`, cycling/biking vers `cycle`, swimming vers `swim`. Les traductions frontend comprennent aussi trail, marche, randonnée, renforcement et cardio ; ces libellés ne constituent pas une extension du contrat de création backend. Sessions distingue notamment `cycle`.

**Correctif :** pour `cycle`, le résumé affiche la vitesse moyenne en km/h : priorité à `workout.avg_speed_kmh` fini et strictement positif, sinon `pacing.average_speed_kmh` fini et strictement positif uniquement si le moteur le marque disponible. Sans vitesse exploitable, une explication FR/EN/ES remplace la valeur. Aucune vitesse dérivée de l’allure, distance ou durée. Le formateur existant `frontend/src/utils/units.js::formatSpeed` est réutilisé explicitement en unités métriques.

La section d’analyse moyenne du vélo privilégie également la vitesse et porte le titre « Vitesse et régularité ». La course conserve l’allure en min/km ; aucun changement de calcul ou nouvelle convention de natation.

### P2 — Allures absolues invalides

**Cause :** `Number.isFinite` acceptait zéro et les valeurs négatives ; le fallback vitesse limité à `== null` ignorait NaN, l’infini, zéro et les valeurs négatives.

**Correctif :** validation locale explicite `Number.isFinite(value) && value > 0` pour l’allure moyenne du résumé, l’allure moyenne du moteur, les fractions les plus rapides/lentes et l’allure moyenne des références similaires. Les splits avaient déjà cette protection. Une allure moteur invalide autorise le fallback vers une vitesse moteur disponible, finie et positive. Une carte sans métrique exploitable est remplacée par l’explication existante.

Les écarts d’allure ne sont pas des allures absolues : zéro et les différences négatives finies restent valides et conservent leur sens descriptif. Aucun recalcul de métriques du moteur ; le formateur partagé d’allure n’est pas modifié, afin de limiter le périmètre à WorkoutDetail.

### P2 — Vérification des zones cardiaques

Les zones ne sont affichées que lorsque `physiology.available === true` et qu’au moins une des clés Z1–Z5 possède un pourcentage fini, strictement positif et inférieur ou égal à 100. Les lignes invalides sont omises ; les distributions absentes, entièrement invalides, entièrement nulles ou ne contenant que des clés inconnues sont masquées.

L’avertissement de provenance/bornes non fournies reste visible, en `text-sm`, dans un conteneur autorisant le retour à la ligne. Aucune attribution aux seuils LT1/LT2 ni nouvelle interprétation physiologique. Tests DOM ajoutés pour le texte et les données invalides ; sa lisibilité réelle sur mobile reste à valider par Emergent.

### Vérifications effectivement exécutées après correction

Depuis `frontend/` :

- `npm ci --legacy-peer-deps --no-audit --no-fund` : restauration réussie des dépendances verrouillées, sans modification des manifests/lockfiles.
- `CI=true npm test -- --watchAll=false --runInBand --forceExit --runTestsByPath src/__tests__/workout-analysis-v2-pages.test.jsx src/lib/i18n.test.js src/__tests__/sessions-page.test.jsx src/__tests__/app-legacy-redirects.test.jsx` : **4 suites réussies, 138 tests réussis, 0 échec**.
- `npm run build` : **compilation réussie** ; avertissement Browserslist existant.
- `git diff --check` : aucun problème d’espacement.
- Scan de secrets des trois fichiers frontend modifiés : aucun secret.
- `parallel_validation` : CodeQL JavaScript exécuté, **0 alerte**. Revue automatique indisponible à cause du modèle configuré absent du registre ; ne pas considérer le statut global « succès » comme une revue exécutée.
- Revue complémentaire `code-review`, en lecture seule, du diff de correction : aucun problème significatif identifié.

Les tests couvrent course avec allure valide, vélo avec vitesse observée et fallback moteur disponible, vélo sans vitesse exploitable, allures nulles/zéro/négatives/NaN/infinies et non numériques, fallback vitesse, absence de FC, zones invalides/indisponibles, FR/EN/ES et le parcours des vrais composants Sessions → WorkoutDetail → Coach avec `workout_id: "w1"`. Les tests existants d’écarts négatifs/zéro et des routes secondaires restent exécutés.

Une exécution intermédiaire a échoué sur le sélecteur du nouveau test de navigation, car Sessions utilise le type et les métriques comme nom accessible plutôt que le nom d’activité. Le sélecteur a été adapté ; le résultat final de 138 tests ci-dessus a réellement été obtenu.

### Limitations restantes et checklist runtime Emergent

- Pas de test visuel ou runtime sur l’application réelle dans cette session.
- La disponibilité frontend n’établit pas une qualité physiologique nouvelle : seules les données et disponibilités existantes sont exploitées.
- L’API ne certifie toujours pas la provenance/bornes des zones.
- Le résumé vélo peut afficher une indisponibilité pendant que l’analyse est encore en cours si la vitesse d’activité est absente, puis afficher la vitesse moteur disponible.
- Les valeurs moteur, textes et fractions historiques ne sont pas recalculés ; les autres types sportifs et le formateur partagé restent inchangés.

Avant merge, Emergent doit valider :

- [ ] Mobile réel 360 px et 390 px, avertissement des zones lisible.
- [ ] Séance endurance.
- [ ] Séance fractionnée.
- [ ] Activité vélo si disponible : km/h ou explication d’indisponibilité.
- [ ] Activité sans FC.
- [ ] Activité avec splits et historique.
- [ ] Navigation Sessions → Détail → Coach et contexte de séance.
- [ ] Chargement et erreur API.
- [ ] Absence de débordement horizontal.

Corrections livrées dans PR318 uniquement ; attendre la revue et ces validations avant merge.

## Vérification complémentaire — 10 octobre 2026

### Références exactes et cause résiduelle

- PR existante : #318, branche `copilot/restructuration-ux-workout-detail`.
- Base cible vérifiée avec `git ls-remote origin refs/heads/copilot/dev` : `65524421948976502cd51f108d8e427d9bd67f29`.
- HEAD avant cette vérification : `91181d575aa2af1819997f789ce517709d3c39e9`.
- HEAD après correction fonctionnelle, code effectivement testé : `7e179acafe0eeb36b84de5b666175c5cb28d5eb8`.
- Le commit documentaire suivant ne change pas le code testé ; son HEAD exact sera publié dans le commentaire de livraison sur #318.

Les corrections sportives, numériques et cardiaques décrites précédemment étaient déjà présentes au HEAD de départ. L’inspection du code a identifié un dernier écart : lorsque l’allure d’activité était invalide, le résumé affichait « non enregistré » même si une vitesse existante était exploitable. Le fallback était appliqué à la carte d’analyse mais pas au résumé hors vélo.

Le résumé réutilise maintenant la vitesse existante, finie et strictement positive, lorsque son allure est invalide : priorité à `workout.avg_speed_kmh`, sinon `pacing.average_speed_kmh` uniquement avec `available === true`. Une allure de course valide reste prioritaire, même en présence d’une vitesse. Sans vitesse exploitable, l’état d’absence reste explicite. Aucun calcul distance/durée/allure, aucun nouveau champ ni modification des moteurs.

L’audit confirme les types backend `run`, `cycle`, `swim` et les normalisations Garmin décrites ci-dessus ; les libellés frontend ne changent pas ce contrat. Les allures absolues, splits et références similaires restent protégés par une validation finie et positive. Les écarts signés restent inchangés.

Les zones sont toujours conditionnées par la disponibilité et des pourcentages exploitables Z1–Z5 ; les données invalides ou absentes sont masquées. L’avertissement FR/EN/ES reste visible et repliable sur plusieurs lignes en `text-sm`, sans présentation des zones comme seuils LT1/LT2 ni interprétation nouvelle. Cela ne démontre pas sa lisibilité dans l’application réelle.

### Fichiers modifiés dans cette vérification

- `frontend/src/pages/WorkoutDetail.jsx`
- `frontend/src/__tests__/workout-analysis-v2-pages.test.jsx`
- `RUNINDEX_PR318_REPORT.md`

Les traductions existantes sont réutilisées sans modification. Aucun backend, Workout Analysis V2, Training V2 ou route secondaire modifié.

### Exécutions effectives

Depuis `frontend/` :

- `npm ci --legacy-peer-deps --no-audit --no-fund` : réussi, manifests et lockfile inchangés.
- `CI=true npm test -- --watchAll=false --runInBand --forceExit --runTestsByPath src/__tests__/workout-analysis-v2-pages.test.jsx src/lib/i18n.test.js src/__tests__/sessions-page.test.jsx src/__tests__/app-legacy-redirects.test.jsx` : **4 suites réussies, 148 tests réussis, aucun échec**, code de sortie 0.
- `npm run build` : **Compiled successfully**, code de sortie 0 ; avertissement Browserslist existant.
- `git diff --check` : réussi.
- Scan de secrets des fichiers frontend modifiés : aucun secret détecté.
- `parallel_validation` après commit fonctionnel : CodeQL JavaScript exécuté, **0 alerte**. La revue automatique reste indisponible (modèle absent du registre), malgré son statut global de succès.
- Agent complémentaire `code-review`, lecture seule du diff courant et des corrections WorkoutDetail contre la base : aucun bug fonctionnel significatif identifié.

Les dix tests ajoutés vérifient FR/EN/ES pour course avec allure valide malgré une vitesse présente, vélo sans vitesse exploitable, fallback du résumé vers vitesse d’activité prioritaire et refus d’une vitesse moteur indisponible. Les cas existants null, zéro, négatif, NaN, infini et non numérique vérifient maintenant également le fallback vitesse du résumé. Absence FC, zones invalides/indisponibles, traductions et parcours des vrais composants Sessions → WorkoutDetail → Coach restent exécutés.

### Limitations et validation runtime Emergent avant merge

Les résultats précédents du rapport sont des snapshots historiques ; les résultats ci-dessus correspondent au code de cette vérification. Les avertissements de configuration backend des tests et de sortie forcée Jest restent présents. Aucun linter autonome n’est configuré dans les scripts frontend ; le build existant a été exécuté.

Aucune URL Emergent ni session authentifiée de test n’a été fournie pour cette exécution. La validation de l’application réelle n’a donc **pas été effectuée** ; les tests DOM ne prouvent ni la lisibilité mobile ni l’absence de débordement horizontal. La provenance et les bornes des zones restent non certifiées par le contrat API.

- [ ] Mobile réel 360 px et 390 px : avertissement des zones lisible.
- [ ] Séance endurance.
- [ ] Séance fractionnée.
- [ ] Activité vélo si disponible : vitesse km/h ou indisponibilité explicite.
- [ ] Activité sans FC : absence des zones lorsque les données sont indisponibles.
- [ ] Activité avec splits et historique.
- [ ] Navigation Sessions → Détail → Coach, contexte exact de séance.
- [ ] Chargement et erreur API.
- [ ] Absence de débordement horizontal.

PR318 uniquement, aucune nouvelle PR et aucun merge. Attendre la revue et la validation runtime Emergent.
