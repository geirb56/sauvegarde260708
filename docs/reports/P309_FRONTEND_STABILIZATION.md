# P309 — Frontend stabilization and human-readable workout analysis

## Références et périmètre

- Base : `copilot/dev`.
- HEAD de départ réel : `8ecffedc020fd69d5ccb438e501ad038316c9c15`.
- `git fetch origin copilot/dev` exécuté avant toute modification ; `FETCH_HEAD` et le checkout correspondaient exactement à ce SHA. Le diff initial était vide.
- Une seule PR frontend de stabilisation ; aucune fusion automatique.
- HEAD final du code frontend validé : `71908e3d062ab15ac104ec5de83d350056ca6fa9`.
- Le commit de livraison suivant ajoute uniquement ce rapport. Son SHA exact est publié dans la description de la PR et la réponse de livraison ; il ne peut pas être inscrit dans son propre contenu sans changer son SHA.

## Corrections

### Route historique `/messages`

Le routeur authentifié redirige explicitement `/messages` vers `/coach` avec `Navigate` et `replace`. Le test vérifie l'URL finale, le remplacement de l'entrée historique et une page Coach effectivement rendue. Les routes `/guidance`, `/digest` et `/training-v2` restent couvertes.

Aucune page Messages, seconde surface de chat ou API historique n'est réintroduite.

### Settings FREE

`SubscriptionContext` reste l'autorité d'accès. Tant que son chargement n'est pas résolu, aucun appel Plan Premium n'est déclenché. Pour FREE, aucun GET `/training/v2/cycle` ou `/training/v2/week` n'est effectué ; la carte Plan présente un verrouillage inline traduit et un CTA vers `/subscription`, sans erreur de chargement Plan ni Paywall plein écran.

Garmin/status, connexion/reconnexion, déconnexion, langue, unités, compte et abonnement restent accessibles selon leurs règles existantes. Pour TRIAL/PREMIUM, les GET cycle, week et `/user/goal` ainsi que les contrats de mutation existants sont conservés. Aucun GET `/training/v2/preferences` n'est ajouté.

### JSDOM

`HTMLElement.prototype.scrollIntoView` reçoit un no-op uniquement si cette méthode n'existe pas. Le changement concerne exclusivement la configuration de tests, pas les composants produit.

### Hiérarchie WorkoutDetail

1. Résumé factuel de la séance.
2. Signaux structurés utiles.
3. Carte **Allure / Pace / Ritmo**.
4. Comparaison récente, avec sa période et son nombre de séances disponibles.
5. Sorties similaires, à partir de `comparison.similar` uniquement.
6. CTA visible **Poser une question au coach**.
7. **Détails de l’analyse**, repliés par défaut avec un élément HTML `details`.

Les textes déterministes `meaning.text` et `advice.text`, les evidence, les limitations détaillées et les graphiques secondaires sont placés dans les détails. Le titre principal « Conseil coach » disparaît. Les textes du moteur ne sont ni parsés, ni réécrits en nouvelle analyse ou prescription.

Les splits kilométriques proviennent du workout chargé indépendamment : ils restent consultables dans les détails repliés même si l'analyse est en attente ou échoue. Les sections propres à l'analyse ne s'affichent qu'après une réponse réussie, sans fabriquer de contenu en cas d'erreur. Cette régression a été identifiée puis corrigée lors de la revue.

L'intensité indisponible reste signalée sobrement ; le motif technique reste consultable dans les détails. L'ancien badge frontend déduisant easy/hard depuis les proportions de zones est supprimé ; les distributions factuelles restent disponibles.

### Formatage et références distinctes

Le helper frontend de delta d'allure convertit les minutes/km absolues en secondes arrondies, reconstruit `m:ss/km` et conserve le signe :

- `-0.012` → `-0:01/km` ;
- `0.2` → `+0:12/km` ;
- `0` → `0:00/km`.

Les valeurs absentes/non finies restent `--`, jamais zéro. L'arrondi des allures absolues gère également le report des secondes vers la minute suivante.

La **Comparaison récente · 14 jours** utilise les métriques structurées de la référence récente et `baseline_period_days`. Les **Sorties similaires · 180 jours** utilisent leur propre `period_days`, leurs moyennes, écarts et effectifs structurés. Ces périodes viennent du payload, pas de constantes frontend.

Le fixture de régression demandé distingue la référence récente à `-0:01/km` des sorties similaires à `+0:12/km`, avec une allure moyenne similaire de `6:36/km`. Les moyennes/écarts de FC sont arrondis à un bpm pour l'affichage seulement. Les effectifs absents ne sont pas inventés.

Lorsque `comparable === false`, les faits restent visibles avec : **Écart descriptif, pas une conclusion de performance.** Les limitations détaillées restent repliées. Aucun verdict de progression/régression n'est déduit de ces écarts.

### i18n FR / EN / ES

Les labels de distance, durée, FC, allure/vitesse, les deux références, les effectifs, les titres de détails et les garde-fous disposent de traductions explicites dans les trois langues. Aucun label métier important de comparaison n'est hardcodé en anglais dans WorkoutDetail.

## Autorités inchangées

- Aucun fichier backend ni calcul backend n'a changé.
- Training V2 reste la seule autorité de prescription.
- Workout Analysis V2 reste la seule autorité déterministe d'analyse.
- Le Coach conversationnel reste la couche d'interprétation humaine ; le parcours WorkoutDetail → vrai Coach conserve le POST `/coach/analyze` avec `workout_id`.
- Garmin ingestion, les comparables backend, les prompts, le RAG, les quotas, les règles backend d'accès et les autres domaines interdits sont inchangés.

## Validation et livraison

### Fichiers modifiés

- `/home/runner/work/sauvegarde260708/sauvegarde260708/frontend/src/App.js`
- `/home/runner/work/sauvegarde260708/sauvegarde260708/frontend/src/setupTests.js`
- `/home/runner/work/sauvegarde260708/sauvegarde260708/frontend/src/pages/Settings.jsx`
- `/home/runner/work/sauvegarde260708/sauvegarde260708/frontend/src/pages/WorkoutDetail.jsx`
- `/home/runner/work/sauvegarde260708/sauvegarde260708/frontend/src/lib/i18n.js`
- `/home/runner/work/sauvegarde260708/sauvegarde260708/frontend/src/lib/workoutAnalysis.js`
- `/home/runner/work/sauvegarde260708/sauvegarde260708/frontend/src/__tests__/app-legacy-redirects.test.jsx`
- `/home/runner/work/sauvegarde260708/sauvegarde260708/frontend/src/__tests__/settings-page.test.jsx`
- `/home/runner/work/sauvegarde260708/sauvegarde260708/frontend/src/__tests__/workout-analysis-v2-pages.test.jsx`
- `/home/runner/work/sauvegarde260708/sauvegarde260708/docs/reports/P309_FRONTEND_STABILIZATION.md`

### Environnement

Les dépendances existantes ont été installées, puis figées avec `npm ci --legacy-peer-deps` depuis `/home/runner/work/sauvegarde260708/sauvegarde260708/frontend`. Un premier essai avec `npm install --legacy-peer-deps --no-package-lock` avait installé des versions plus récentes et provoqué une erreur de résolution Jest/Radix. La restauration du lockfile existant a résolu cette erreur.

Aucune dépendance ni configuration de résolution Jest n'est modifiée dans la PR. Les validations finales utilisent les commandes standard, sans mapper supplémentaire.

### Commandes réellement exécutées après les dernières corrections

```bash
cd /home/runner/work/sauvegarde260708/sauvegarde260708/frontend
npx craco test \
  src/__tests__/app-legacy-redirects.test.jsx \
  src/__tests__/settings-page.test.jsx \
  src/__tests__/workout-analysis-v2-pages.test.jsx \
  src/__tests__/chat-coach-subscription-status.test.jsx \
  --watchAll=false \
  --forceExit

npm run build

cd /home/runner/work/sauvegarde260708/sauvegarde260708
git diff --check

cd /home/runner/work/sauvegarde260708/sauvegarde260708/frontend
CI=true npx craco test --watchAll=false --forceExit --runInBand
```

Résultats exacts :

| Validation | Résultat |
| --- | --- |
| Quatre suites demandées | **4/4 suites, 87/87 tests réussis**, aucun snapshot |
| Build production | **Compiled successfully**, sortie 0 |
| `git diff --check` | Réussi, sortie 0 |
| Suite frontend complète | **32/33 suites réussies ; 493 tests réussis, 1 échec**, sortie 1 |
| Scan secrets des fichiers modifiés | Aucun secret détecté |
| CodeQL JavaScript, après commit du code final | **0 alerte** |
| Revue indépendante du diff final | Aucun problème significatif restant |

Les tests conservent notamment une seule requête canonical Workout Analysis, l'absence de `/rag/workout` et `/coach/detailed-analysis`, les états sans evidence, l'erreur d'analyse cohérente et l'intégration avec le vrai composant Coach et son POST `/coach/analyze`.

### Échec préexistant et limites restantes

- L'unique échec de la suite complète est l'assertion statique de `/home/runner/work/sauvegarde260708/sauvegarde260708/frontend/src/__tests__/progress-v2-migration.test.jsx:73`, qui cherche littéralement `predictions.predictions?.map`.
- Le test et `/home/runner/work/sauvegarde260708/sauvegarde260708/frontend/src/pages/Progress.jsx` sont byte-identiques à la base. Leurs blobs respectifs sont `429e12e81de4c4889e44399ffdf0964a788ef210` et `e827df5b1da4ed2d73fd63010c2e37d368bba6ba`. La chaîne attendue est déjà absente de Progress à la base. Aucun test ni écran Progress n'a été modifié pour masquer cet échec.
- Le build signale des données Browserslist anciennes et la dépréciation Node `fs.F_OK`, sans erreur de compilation.
- `npm ci` signale **49 vulnérabilités du graphe de dépendances existant** : 12 faibles, 10 modérées, 26 élevées, 1 critique. Aucun changement de dépendance n'est introduit ; leur remédiation n'est pas incluse dans cette PR frontend.
- Le binaire de revue automatique intégré était indisponible. Le contrôle a été remplacé par une revue indépendante en lecture seule ; la régression des splits a été corrigée et le diff re-revu. CodeQL a réellement été exécuté et n'a détecté aucune alerte.
- Les tests frontend utilisent des APIs simulées : aucune validation live Garmin, paiement, navigateur déployé ou modification des autorités backend n'est revendiquée.

**Livraison : une seule PR vers `copilot/dev`, NON MERGÉE.**
