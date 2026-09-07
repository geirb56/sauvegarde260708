# RUNINDEX — PR #233 — Training UX V3 (reprise propre)

## 1. Head de départ

- Base : `copilot/dev`
- Commit de départ : `4f0be2d` (HEAD de `copilot/dev` au moment du travail, correspondant au merge de PR #231 / C231).
- PR #232 a été fermée sans merge et **aucun code de #232 n'a été repris**. Le travail est reparti du HEAD réel de `copilot/dev`.
- Branche de travail : `copilot/training-ux-v3-reprise-propre`.

## 2. Fichiers modifiés

Aucun fichier backend n'a été touché. Seuls 3 fichiers frontend ont été modifiés :

- `frontend/src/pages/TrainingPlanV2.jsx` — refonte de la page Training V3.
- `frontend/src/lib/i18n.js` — nouvelles clés de traduction (en/fr/es) pour les nouveaux textes UI.
- `frontend/src/__tests__/training-v2-page.test.jsx` — fixtures alignées sur le contrat réel + ~15 nouveaux tests.

Aucun fichier backend, aucune migration, aucun nouveau endpoint.

## 3. Décisions UX

### 3.1 Vue semaine
- Le volume planifié (`planned_km` ou `planned_duration_minutes` selon `target_basis`) et le nombre de séances proviennent exclusivement de `WeekV2PlanResponse` / `WeekV2TargetResponse`.
- Un nouveau bloc **`WeekVolumeSummary`** sépare explicitement :
  - le volume **planifié** (`planned_km` / `planned_duration_minutes`),
  - le volume **réellement accompli selon le plan** (somme des `actual` des séances dont `matching_status === "matched"` uniquement),
  - le volume **Garmin supplémentaire** (`unmatched_actuals`), affiché à part avec une note explicite indiquant qu'il n'est jamais compté comme séance planifiée accomplie.
- Le nombre de séances "accomplies" (`completedSessionCount`) est dérivé uniquement du nombre d'actuals **matched**, jamais d'une logique "jour passé = fait".

### 3.2 Cartes séances
- Chaque `WeekSessionRow` reste une vue compacte (jour/date, type réel, distance ou durée, statut).
- Une allure n'est affichée **que si elle existe déjà** dans les données réelles (`actual.pace_min_per_km` pour l'accompli, ou une valeur de pace canonique existante pour la prescription — jamais inventée pour une "quality").
- Un panneau de détail dépliable (bouton, pas un lien systématique) a été ajouté : au clic, affiche prescribed vs actual (distance, durée, allure réelle Garmin) et un lien vers l'analyse **uniquement** si `actual.activity_id` existe réellement.
- Le déploiement du détail est désactivé pour les jours de repos explicites et pour les séances `prescription_unavailable` (rien à montrer).

### 3.3 États
- Le mapping des statuts (`planned`, `matched`+`completed_as_planned`/`completed_modified`/`completed_unverified`, `missed`, `ambiguous`, `prescription_unavailable`, `rest`) était déjà géré par le code existant issu de #231/PR232A et a été conservé tel quel — aucune redéfinition, aucun statut inventé.
- Aucune auto-complétion "jour passé ⇒ fait" n'a été ajoutée ni ne préexistait.
- Aucun bouton Done/Missed manuel n'existe dans le code (vérifié et couvert par un test dédié).

### 3.4 Unmatched Garmin
- Nouveau composant **`UnmatchedActualsSection`** : section séparée listant `unmatched_actuals` (type, distance/durée, date). Ces activités ne sont jamais rattachées à une séance planifiée — elles n'apparaissent dans aucune `WeekSessionRow`.
- Un état vide explicite est affiché quand `unmatched_actuals` est vide.

### 3.5 Units (metric/imperial)
- Ajout de `minPerKmToFormattedPace` (helper partagé) qui convertit un `min_per_km` brut vers le format d'affichage correct selon `unitSystem`, via `formatPace` (déjà présent dans `utils/units.js`, non modifié).
- La carte **Paces** utilisait auparavant `${pace_str} /km` codé en dur — corrigé pour utiliser `min_per_km` (déjà exposé par `/training/v2/paces`) reformaté selon l'unité active. En imperial, si seul `pace_str` (texte déjà formaté "mm:ss/km") est disponible sans `min_per_km`, la valeur n'est **pas affichée** plutôt que d'afficher une unité fausse.
- Aucun `/km` n'est codé en dur dans un contexte imperial (vérifié par tests).

### 3.6 Today
- La carte Today utilise strictement les champs déjà renvoyés par `/training/today` (`daily_runtime_helpers.prescription_to_runtime_session`) ; aucun champ frontend inventé n'a été ajouté à cette carte.

## 4. Source de vérité de chaque donnée affichée

| Donnée affichée | Champ backend source | Endpoint |
|---|---|---|
| Volume planifié semaine | `target_km` / `target_duration_minutes` (selon `target_basis`) | `GET /training/v2/week` (`WeekV2TargetResponse`) |
| Nombre de séances planifiées | `session_count` | `GET /training/v2/week` |
| Volume accompli (plan) | somme de `sessions[].actual.distance_km` / `.duration_minutes` où `matching_status === "matched"` | `GET /training/v2/week` (`WeekV2SessionResponse.actual`) |
| Volume Garmin supplémentaire | `unmatched_actuals[].distance_km` / `.duration_minutes` | `GET /training/v2/week` |
| Statut de chaque jour | `matching_status`, `adherence_status`, `execution_status` | `GET /training/v2/week` |
| Distance/durée réelle séance | `sessions[].actual.distance_km` / `.duration_minutes` | `GET /training/v2/week` |
| Allure réelle Garmin | `sessions[].actual.pace_min_per_km` | `GET /training/v2/week` |
| Identifiant pour lien analyse | `sessions[].actual.activity_id` | `GET /training/v2/week` |
| Allures canoniques (carte Paces) | `min_per_km` / `pace_str` par zone | `GET /training/v2/paces` |
| Prescription Today | champs runtime tels que renvoyés | `GET /training/today` |

Aucune de ces valeurs n'est recalculée, interpolée ou inventée côté frontend.

## 5. Tests réellement exécutés et résultats

Commandes exécutées dans `frontend/` (après `npm install --legacy-peer-deps`) :

```
CI=true npx craco test --watchAll=false --forceExit                     # suite complète
CI=true npx craco test --watchAll=false --forceExit training-v2-page    # ciblé Training
npm run build                                                            # build production
```

Résultats :
- Suite complète : **17 suites, 254 tests, 254 passés, 0 échec**.
- Fichier ciblé `training-v2-page.test.jsx` : **37/37 passés**, incluant les nouveaux cas :
  - future planned
  - matched + completed_as_planned / completed_modified / completed_unverified
  - missed
  - ambiguous
  - prescription_unavailable (neutre, non expansible)
  - rest (non expansible)
  - unmatched_actual affiché dans une section séparée, jamais rattaché à une séance
  - aucun champ `None`/vide affiché brut
  - aucune structure de séance inventée pour une "quality" (pas de "3×2km", pas de splits)
  - aucune allure inventée quand elle n'existe pas dans le contrat
  - volume planifié vs volume Garmin réel strictement séparés dans l'UI
  - rendu correct en metric (km, min/km)
  - rendu correct en imperial (miles, min/mile) **sans** `/km` codé en dur
  - rendu correct en viewport mobile étroit (375px)
  - absence de tout bouton "Done"/"Missed"
- `dashboard-training-v2.test.jsx` (consommateur existant) : **32/32 passés**, non affecté.
- `npm run build` : **succès**, aucune erreur de compilation.
- Scan de secrets (`runtime-tools-secret_scanning`) sur les fichiers modifiés : **aucun secret détecté**.
- `parallel_validation` (Code Review + CodeQL) exécuté à plusieurs reprises pendant le développement ; tous les retours substantiels ont été traités (nommage camelCase, dérivation unique du compteur de séances accomplies depuis les actuals matched, clés React stables pour la liste unmatched, exclusion des jours de repos de l'expansion, extraction d'un helper `minPerKmToFormattedPace` partagé, remplacement des `.replace()` simples par un helper `formatTemplate` remplaçant toutes les occurrences d'un placeholder).

Consommateurs existants audités (aucune régression, aucun contrat cassé) :
- `Dashboard.jsx` / `dashboard-training-v2.test.jsx` — inchangé, tests toujours verts.
- `Sessions.jsx` — non modifié ; convention de route `/workout/:id` reprise à l'identique pour la cohérence.
- `Settings.jsx` — non modifié, aucune dépendance sur les champs touchés.
- Routes Training (`App.js`) — inchangées (`/training/today` via TodayPage, `/training` via TrainingPlanV2, `/workout/:id`, `/sessions/:id`).

## 6. Éléments volontairement NON implémentés (faute de prescription canonique)

Conformément à la règle **PRESCRIPTION ≠ PRÉSENTATION**, les éléments suivants n'ont **pas** été implémentés car le backend actuel (WorkoutGenerator/PR230/C231) ne fournit pas ces données :

- Aucun `session_structure.py` ni structure de séance inventée (pas de répétitions, longueur, récupération générées côté frontend).
- Aucune transformation d'une séance "quality" en structure du type "3×2km threshold".
- Aucun warmup/cooldown/récupération inventé pour aucune séance.
- Aucun bloc marathon inventé dans les séances `long_easy`.
- Aucun recalcul de prescription historique avec les Training Paces actuelles (les séances passées restent figées via le snapshot C231, `primary_pace` reste `None` pour les séances passées/aujourd'hui — comportement backend préexistant, non modifié).
- Aucune allure spécifique affichée pour une "quality" en l'absence d'un champ de pace canonique réellement prescrit dans la réponse backend.
- Aucun feedback manuel Done/Missed (aucun bouton, aucun état ajouté).
- Aucune modification de PR230, DailyAdaptation, WorkoutGenerator, ni de la logique de snapshot C231.
- Aucune modification de contrat backend, additive ou non (tous les champs nécessaires existaient déjà : `min_per_km` sur `/training/v2/paces`, `actual.pace_min_per_km`/`activity_id` sur `/training/v2/week`).

## 7. Statut

PR créée en **draft** à partir de `copilot/dev`, **non mergée**, conformément à la consigne "STOP après création de la PR et rapport de validation".

---

## 8. CORRECTION C233 (round de correction post-review)

### 8.1 Head de départ de la correction

- Commit de départ de la correction : `13bea88` (commit initial de PR #233 ci-dessus, sur la branche `copilot/training-ux-v3-reprise-propre`).
- Aucun élargissement de scope : uniquement les 5 blockers listés ci-dessous ont été traités, dans les mêmes 2 fichiers frontend déjà touchés par #233 (`TrainingPlanV2.jsx`, `training-v2-page.test.jsx`). Aucun fichier backend modifié.

### 8.2 Corrections exactes

**C233 #1 — Liens analyse Garmin cassés**
- Bug : `actual.activity_id` (et `unmatched_actuals[].activity_id`) est l'`external_id` Garmin brut, mais `db.workouts.id` est construit côté backend comme `f"garmin-{external_id}"` (`backend/garmin/service.py:544`, `activity_to_workout()`). Le frontend liait vers `/workout/${activity_id}` (sans le préfixe), donc un lien mort.
- Correction : nouveau helper `buildWorkoutDetailPath(activityId)` construisant `/workout/garmin-${activityId}`, utilisé à la fois pour le lien d'analyse d'une séance matched et pour la ligne d'un `unmatched_actual`. Aucun nouveau contrat backend introduit — uniquement l'application de la convention `garmin-` déjà existante et stable.
- Test cross-layer ajouté : `activity_id = "12345"` → lien attendu `/workout/garmin-12345`, pour une séance matched **et** pour un unmatched actual.

**C233 #2 — Today alignée sur le vrai contrat backend**
- Bug : les fixtures/mocks et le code de la carte Today utilisaient des champs fictifs (`workout_type`, `duration_minutes` numérique, `prescription` texte libre type "3 × 10 min", `pace_target`, `target_zone`) qui n'existent pas dans la réponse réelle de `/training/today`.
- Réalité backend confirmée (`backend/training_v2/daily_runtime_helpers.py::prescription_to_runtime_session`, lignes 116-138, utilisée identiquement pour `served_prescription`/`adapted_prescription`/`adaptive_session`/`planned_session`/`original_prescription` dans `backend/server.py:3496-3573`) : `{day, type, duration ("Xmin" ou sentinel "0min"), intensity, distance_km (0 = sentinel "pas de distance"), estimated_tss}`.
- Correction :
  - `served_prescription` est désormais la clé prioritaire dans la chaîne de fallback (déjà présente, mais mal exploitée par les champs fictifs en aval).
  - Nouveaux helpers `getTodayDurationLabel(session)` / `getTodayDistanceKm(session)` : `"0min"` n'est jamais affiché comme une vraie durée ; `distance_km === 0` n'est jamais affiché comme "0 km".
  - Nouvelle table `RUNTIME_TYPE_TO_WORKOUT_TYPE` (copie exacte de l'enum backend `daily_runtime_helpers.py:27-34` : `rest→rest, recovery→recovery, endurance→easy, tempo→steady, threshold→quality, long_run→long_easy`) pour traduire le vocabulaire runtime de Today (`type`) vers le vocabulaire domaine de Week (`workout_type`) utilisé par les clés i18n existantes — sans quoi la plupart des types Today s'affichaient comme "type inconnu".
  - Suppression totale de l'affichage `today-session-prescription` et `today-session-pace-zone` : aucune prescription texte ni pace/zone n'est inventée pour Today (le contrat réel n'en fournit pas).
  - Fixtures de test (`todoData()`) réécrites intégralement sur la forme réelle, y compris pour le cas C231-round-2-item-1.

**C233 #3 — Badge "Today" indépendant de l'horloge navigateur**
- Bug : `getTodayDayKey()` utilisait `new Date().getDay()` (horloge/fuseau du navigateur), en violation de la règle "aucune dépendance timezone/clock".
- Correction : `getTodayDayKey` supprimée, remplacée par `resolveTodayDayKey(weekData)` qui :
  1. cherche la session dont `planned_date === weekData.reference_date` (correspondance exacte) ;
  2. à défaut, retombe sur un calcul pur de jour de semaine à partir de `reference_date` (`Date.UTC` + `getUTCDay()`, aucune horloge locale) ;
  3. retourne `null` si `reference_date` est absent (jamais de devinette basée sur le navigateur).
- Tests ajoutés : un test avec `jest.useFakeTimers()` + `jest.setSystemTime()` + un fuseau navigateur simulé différent de UTC, prouvant que le badge Today reste sur le jour correspondant à `reference_date` ; un test de repli déterministe quand aucune session ne correspond exactement ; un test vérifiant qu'une seule carte reçoit le badge Today.

**C233 #4 — Jour + date sur chaque carte semaine**
- Ajout de `session.planned_date` affiché sur chaque `WeekSessionRow`, sous forme "Wednesday · 26 Aug" (jour traduit + date jour-mois, jamais reconstruite depuis l'horloge navigateur — dérivée uniquement de la chaîne ISO `planned_date`).
- Le nom du mois est traduit via `Intl` (respecte `en`/`fr`/`es`), mais l'ordre jour-puis-mois est forcé manuellement pour éviter l'inversion "Aug 26" que produirait `Intl` par défaut en `en-US`.
- Si `planned_date` est absent pour une séance, seul le jour de semaine est affiché (aucune date fabriquée).
- Tests ajoutés : libellé "Wednesday · 26 Aug" correct ; traduction correcte en `fr` ("Mercredi · 26 août") ; aucune date affichée quand `planned_date` est absent.

### 8.3 Distinction contrat backend réel vs. mocks précédents (fautifs)

| Champ | Mock précédent (fautif, supprimé) | Réalité backend confirmée |
|---|---|---|
| Type de séance Today | `workout_type` (vocabulaire Week) | `type` (vocabulaire runtime distinct : `rest/recovery/endurance/tempo/threshold/long_run`), traduit via `RUNTIME_TYPE_TO_WORKOUT_TYPE` |
| Durée Today | `duration_minutes` (nombre) | `duration` (chaîne `"Xmin"`, sentinel `"0min"` = absence) |
| Distance Today | implicite / absente | `distance_km` (nombre, `0` = sentinel absence) |
| Prescription texte | `prescription: "3 × 10 min"` | **n'existe pas** dans le contrat réel — supprimé |
| Allure/zone Today | `pace_target`, `target_zone` | **n'existent pas** dans le contrat réel — supprimés |
| Lien analyse Garmin | `/workout/${activity_id}` | `/workout/garmin-${activity_id}` (convention `activity_to_workout()`, `backend/garmin/service.py:544`) |
| Jour "Today" | `new Date().getDay()` (navigateur) | `weekData.reference_date` (+ `sessions[].planned_date` exact match, fallback calendaire pur) |

### 8.4 Tests réellement exécutés (round C233)

Commandes exécutées dans `frontend/` :
```
npm install --legacy-peer-deps                                                    # réinstallation (node_modules absent, session fraîche)
CI=true npx craco test --watchAll=false --forceExit training-v2-page              # ciblé Training
CI=true npx craco test --watchAll=false --forceExit                               # suite complète
npm run build                                                                       # build production
```

Résultats :
- `training-v2-page.test.jsx` (ciblé) : **48/48 passés** (contre 37 avant la correction — 11 tests nouveaux/réécrits pour C233, dont les 10 tests C233 dédiés + la précision du test "highlights today").
- Suite complète : **17 suites, 264 tests, 264 passés, 0 échec** (contre 254 avant la correction, cohérent avec les +10 nouveaux tests C233).
- `npm run build` : **succès**, aucune erreur de compilation.
- `runtime-tools-secret_scanning` sur les fichiers modifiés : **aucun secret détecté**.
- `parallel_validation` (Code Review + CodeQL) : Code Review — aucun commentaire ; CodeQL (javascript) — **0 alerte**.

### 8.5 Statut

Corrections poussées sur la branche existante `copilot/training-ux-v3-reprise-propre` (PR #233, toujours en **draft**, base `copilot/dev`). **Aucun merge effectué.** STOP après push, conformément à la consigne.
