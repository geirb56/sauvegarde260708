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
