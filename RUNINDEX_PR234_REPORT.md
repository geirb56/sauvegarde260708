# RUNINDEX — PR #234 — Structured Workout Prescription V1

## 1. Head / base

- Base (obligatoire) : `copilot/dev`
- Source de vérité distante attendue au départ : `0d144397e77ce08e7e2ddfa7ad2c33bb5b554a20`
- Branche de travail : `copilot/pr-234-structured-workout-prescription` (déjà créée depuis ce commit avant le début de cette session — vérifié via `git log -1` = `0d14439...`)
- **Aucun merge n'a été effectué.** Cette PR reste en DRAFT vers `copilot/dev`.

## 2. Fichiers modifiés

Nouveaux fichiers uniquement (aucun fichier existant modifié) :

- `backend/training_v2/structured_workout.py` — StructuredWorkoutPrescriptionEngine (nouveau moteur, ~950 lignes dont documentation extensive).
- `backend/tests/test_structured_workout_pr234.py` — 64 tests unitaires/domain.
- `RUNINDEX_PR234_REPORT.md` — ce rapport.

Aucun fichier de `training_v2/` existant (`workout_generator.py`, `daily_adaptation.py`, `periodization.py`, `plan_goal.py`, `training_paces.py`, `weekly_target.py`, `week_plan_bridge.py`, `today_prescription.py`, `prescription_snapshot.py`, etc.) n'a été touché. Aucun fichier `server.py` ni frontend n'a été touché.

## 3. Architecture retenue

Nouveau module `backend/training_v2/structured_workout.py`, nommé **StructuredWorkoutPrescriptionEngine** (docstring du module), exposant la fonction d'entrée `build_structured_workout_prescription(...)` — cohérent avec la convention existante du repo où chaque "moteur" V2 est un module portant son nom (`daily_adaptation.py` → `build_daily_adaptation`, `periodization.py` → `build_periodization`, etc.), et non une classe.

Le moteur consomme (jamais ne recalcule) :
- `WorkoutPrescription` (WorkoutGenerator, #131) — workout_type + volume déjà décidés.
- `PlanGoal` (#05) — `goal_type`.
- `PeriodizationSnapshot` — `phase`.
- `TrainingPaces` (#194, optionnel) — zones E/M/T/I/R.

Il ne recalcule ni WeeklyTarget, ni Periodization, ni Training Paces, ni les garde-fous amont (1 quality/semaine, caps long run, etc. — déjà appliqués par WorkoutGenerator). Il n'introduit aucun second planificateur : c'est une fonction pure `WorkoutPrescription -> StructuredWorkoutPrescription`.

## 4. Emplacement exact dans le pipeline

Pipeline conceptuel documenté dans le docstring du module :

```
WorkoutGenerator (WeeklyPlan, une WorkoutPrescription/jour)
    -> DailyAdaptation (TODAY ONLY : KEEP / EASY_DOWNGRADE / SHORTEN / REST)
    -> StructuredWorkoutPrescriptionEngine (structuration)
    -> StructuredWorkoutPrescription (prescription exécutable)
```

**Décision : la structuration a lieu APRÈS DailyAdaptation, jamais avant.**

Concrètement : le moteur doit être appelé avec la `WorkoutPrescription` **FINALE** du jour :
- Pour AUJOURD'HUI : `adaptation_result.adapted_workout` retourné par `daily_adaptation.build_daily_adaptation` (jamais la prescription planifiée brute).
- Pour tout autre jour de la semaine : la session brute du `WeeklyPlan` reconcilié (DailyAdaptation ne s'applique jamais à ces jours — règle déjà en vigueur, documentée dans `today_prescription.py` : "DailyAdaptation is Today-only").

Justification (3 garanties demandées) :
1. **Cohérence** : les steps sont toujours construits à partir du total réellement servi. Il n'existe jamais de combinaison "parent adapté / steps issus de l'ancien parent" (voir §12 Daily Adaptation ci-dessous et tests M/N/O/P).
2. **Déterminisme** : la structuration est une fonction pure de (workout_type, volume total, goal, phase, paces). Alimentée par l'état FINAL, elle produit toujours la même structure pour un état final donné, indépendamment du chemin d'adaptation emprunté.
3. **Absence de structure périmée après adaptation** : structurer AVANT puis tenter d'adapter une *structure* obligerait DailyAdaptation à comprendre et réécrire des steps (dupliquant la logique de ce moteur, avec risque de steps ne correspondant plus aux totaux adaptés). En structurant APRÈS, ce problème ne peut pas exister par construction.
4. **Compatibilité snapshot #235** : une fois un jour figé (`prescription_snapshot.py`), la `WorkoutPrescription` finale ne change plus — appeler ce moteur dessus est idempotent et son résultat est sérialisable tel quel pour un futur snapshot.

**Important — portée de cette PR** : le moteur n'est PAS câblé dans `server.py` ni dans `today_prescription.py`/`week_plan_bridge.py` dans cette PR. Le sujet 18 du problem statement autorise (sans l'exiger) l'ajout du contrat API "si indispensable" ; le câblage dans les endpoints existants a été volontairement laissé hors scope pour :
- respecter strictement "ne pas refaire l'UX Training" et "aucune régression UX" (#233 doit continuer de fonctionner à l'identique) ;
- éviter d'élargir le diff sur des fichiers `server.py`/`today_prescription.py` très sensibles (partagés Week + Today) sans nécessité fonctionnelle immédiate ;
- garder cette PR strictement backend/domain-engine, testable en isolation.

Ce choix est documenté ici comme limite connue (voir §19) et recommandation pour une PR de câblage ultérieure (potentiellement #235/#236).

## 5. Contrat Structured Workout

```python
class StructuredWorkoutRecovery:
    kind: str                      # "jog" | "rest"
    duration_seconds: Optional[int]
    distance_m: Optional[float]    # toujours None en V1 (jamais fabriqué)

class StructuredWorkoutStep:
    step_type: StructuredStepType  # warmup | work | recovery | cooldown | continuous | rest
    repetitions: int = 1
    distance_m: Optional[float]        # PAR répétition
    duration_seconds: Optional[int]    # PAR répétition
    recovery: Optional[StructuredWorkoutRecovery]
    pace_zone: Optional[str]           # "E"|"M"|"T"|"I"|"R"|None
    pace_min_per_km: Optional[float]        # zones single-value (M/T/R)
    pace_min_per_km_min/max: Optional[float]  # zones range (E/I)
    reason_codes: tuple[str, ...]

class StructuredWorkoutPrescription:
    workout_type: str
    target_basis: str              # "distance" | "duration" | "none"
    total_distance_km / total_duration_minutes: Optional  # miroir EXACT du parent, jamais recalculé
    steps: tuple[StructuredWorkoutStep, ...]
    steps_distance_km_sum / steps_duration_seconds_sum: Optional
    distance_invariant_applicable / distance_closes_total: bool
    duration_invariant_applicable / duration_closes_total: bool
    reason_codes: tuple[str, ...]
```

`StructuredWorkoutStep.recovery` est **embarqué** dans le step `work` auquel il appartient — jamais un step frère avec sa propre distance. C'est la clé de la résolution du bug #232 (voir §9).

## 6. Règles goal-aware

Table de sélection `_select_quality_kind(goal_type, phase)` (une seule fonction, testée par goal × phase) :

| Goal          | base                | build               | specific              |
|---------------|---------------------|---------------------|------------------------|
| maintenance   | tempo_continuous     | tempo_continuous     | tempo_continuous       |
| 5k            | threshold_intervals  | vo2_intervals        | vo2_intervals          |
| 10k           | tempo_continuous     | threshold_intervals  | race_specific_steady   |
| half_marathon | tempo_continuous     | threshold_intervals  | race_specific_steady   |
| marathon      | tempo_continuous     | threshold_intervals  | race_specific_steady (zone M) |
| ultra         | tempo_continuous     | threshold_intervals  | race_specific_steady   |

`taper` / `race` / `consolidation` → toujours `tempo_continuous`, quel que soit le goal (aucune session dure/incohérente proche de la course, retour contrôlé). `maintenance` → toujours `tempo_continuous`, quelle que soit la phase.

Garde défensive explicite : `ultra` ne reçoit jamais `vo2_intervals` (même si la table venait à changer par erreur), conformément à la doctrine "priorité endurance/durability, pas d'intervalles VO2 injectés artificiellement".

`race_specific_steady` résout sa zone par goal : `marathon` → `M` (allure marathon spécifique) ; tout autre goal concerné (`10k`, `half_marathon`, `ultra`) → `T` (le seuil est la meilleure approximation "spécifique course" disponible dans la bibliothèque V1 sans introduire de pseudo-science supplémentaire).

## 7. Règles phase-aware

Le moteur **consomme** `PeriodizationSnapshot.phase` (enum réel du repo : `base|build|specific|taper|race|consolidation`), il ne le décide jamais. Le même goal produit une structure différente selon la phase (testé explicitement — test F "phase-aware").

## 8. Sélection des types de qualité (bibliothèque V1)

4 structures fermées et testables : `tempo_continuous`, `threshold_intervals`, `vo2_intervals`, `race_specific_steady`. Chacune a :
- une zone Training Paces associée (T, T, I, M/T) ;
- des paramètres de répétition calibrés et documentés comme "PRODUCT CALIBRATION V1, non loi physiologique" (taille de rep cible, bornes min/max de répétitions, durée de récupération).

Si aucune de ces structures ne peut être posée de façon fiable (volume insuffisant pour au moins 2 répétitions), le moteur **replie** vers un bloc de travail continu unique et ajoute `VOLUME_LIMITED` — jamais une structure inventée.

## 9. Sémantique exacte du total parent (correction du bug #232)

- `total_distance_km` / `total_duration_minutes` du `StructuredWorkoutPrescription` sont des **miroirs exacts** du parent `WorkoutPrescription` — jamais recalculés.
- La récupération (`StructuredWorkoutRecovery`) est **embarquée** dans le step `work`, jamais un step frère : sa distance est **toujours `None`** (jamais fabriquée), donc elle ne peut structurellement jamais gonfler la distance totale.
- **Base distance** : `steps_distance_km_sum` = somme de warmup + work×reps + cooldown (recovery exclue, car sans distance). Par construction, cette somme == `total_distance_km` exactement (`distance_closes_total=True`), car le "reste" (drift d'arrondi) est absorbé dans le cooldown (§10), jamais perdu ni ajouté au-delà du total.
- **Base duration** : la récupération EST comptée (c'est un vrai coût en temps) : `steps_duration_seconds_sum` inclut `reps × (per_rep_s + recovery_s)`. Le budget de répétitions est calculé en **réservant d'abord le temps de récupération total** (`work_budget_s = work_s - reps*recovery_s`) avant de diviser le travail — sans cela, la récupération s'ajoutait AU-DESSUS du budget (bug détecté et corrigé pendant le développement, voir §17 "anomalies corrigées"). Le cooldown absorbe le reste exact en entier (arithmétique entière, jamais de perte).
- Champs `*_invariant_applicable` : `distance_invariant_applicable` est vrai seulement si `target_basis=="distance"` ; `duration_invariant_applicable` seulement si `target_basis=="duration"`. Quand l'un des deux n'est pas applicable, l'écart n'est jamais masqué : le champ le dit explicitement (jamais un faux `True` implicite).
- Invariant testé exhaustivement par fuzzing manuel (voir §16) sur ~35 valeurs de distance et ~195 valeurs de durée × 3 phases × plusieurs goals : **0 échec**.

## 10. Gestion des recoveries

Recovery = métadonnée du step `work` (`kind="jog"`, `duration_seconds` calibré V1), jamais un step indépendant. Distance de récupération toujours `None`.

## 11. Gestion du rounding / reste

- Distance : warmup/cooldown réservés en premier (bornés min/max + fraction, jamais > 60% du total combinés), le travail prend le reste, les répétitions se répartissent uniformément (division entière), et le reste d'arrondi (`work_m - per_rep_m*reps`) est absorbé par le cooldown — jamais par un rep "plus long" arbitraire, jamais perdu.
- Durée : warmup arrondi en premier (entier, borné à `[0, total]`), puis le cooldown est calculé comme **le reste exact** (`total - warmup - reps*(per_rep+recovery)` ou `total - warmup - work`) — ceci garantit la fermeture exacte de l'invariant en toutes circonstances (voir §9), le cooldown ne pouvant jamais devenir négatif (clampé à 0 dans le cas limite adversarial).
- Aucune distance ni durée négative. Aucun step à zéro sauf sémantiquement (ex. `distance_m=None` si volume nul).
- **Garde anti-dégénérescence (ajoutée après revue de code)** : le clamp `reps ∈ [rep_min, rep_max]` peut, pour un volume juste au-dessus du seuil `_MIN_WORK_*_FOR_INTERVALS`, produire un `per_rep` anormalement court une fois le nombre minimal de répétitions imposé (ex. `vo2_intervals` avec `rep_min=4` sur un volume tout juste suffisant). Le moteur vérifie explicitement `per_rep_m`/`per_rep_s` contre un plancher calibré par type (`_MIN_PER_REP_M`/`_MIN_PER_REP_S`) et **replie vers un bloc de travail continu unique + `VOLUME_LIMITED`** plutôt que de présenter une fausse structure d'intervalles dégénérée. Vérifié par fuzzing (aucune régression de l'invariant de fermeture) et par la suite de tests existante.

## 12. Interaction DailyAdaptation

Aucune modification de `daily_adaptation.py`. Le contrat retenu (voir §4) : ce moteur consomme toujours la prescription **finale** (post-adaptation pour Today). Testé explicitement (tests M/N/O/P) :
- **KEEP** : structure cohérente avec le volume conservé.
- **SHORTEN** : la structure finale reflète le volume réellement raccourci (`steps_distance_km_sum` == volume adapté, strictement < volume planifié original).
- **DOWNGRADE** (`EASY_DOWNGRADE`) : `workout_type` devient `"easy"` avant structuration → aucun step `work`/récupération/zone qualité résiduel (vérifié : `all(s.step_type != "work")`, `all(s.recovery is None)`, `all(s.pace_zone in (None,"E"))`).
- **REST** : `workout_type` devient `"rest"` → `steps=()`, aucun total, aucune structure d'effort résiduelle.

## 13. Interaction Training Paces

Consommation uniquement (aucun recalcul VDOT/fractions Daniels). Mapping zone→champ : E/M/T/I/R → `training_paces.easy/marathon/threshold/interval/repetition`. Si `TrainingPaces` est `None` ou `confidence=="insufficient"`, ou si le champ zone est `None` : tous les champs numériques restent `None`, `PACE_UNAVAILABLE` est ajouté, mais **la zone sémantique reste renseignée** (elle est connue — c'est une propriété du type de session, indépendante de la disponibilité des paces).

Durée dérivée d'une pace : uniquement pour les zones **single-value** (M/T/R) — jamais pour une plage (E/I), qui n'a pas d'estimation ponctuelle canonique sans invention.

## 14. Fallback "data insuffisante"

- `workout_type` inconnu → `StructuredWorkoutPrescription` vide (`steps=()`), `reason_codes=("STRUCTURE_UNAVAILABLE",)`.
- Volume insuffisant pour répétitions → repli sur bloc continu + `VOLUME_LIMITED`.
- Ni distance ni durée sur le parent (hors `rest`) → `target_basis="none"`, `STRUCTURE_UNAVAILABLE`.

## 15. Reason codes

Goal : `GOAL_MAINTENANCE`, `GOAL_5K`, `GOAL_10K`, `GOAL_HALF_MARATHON`, `GOAL_MARATHON`, `GOAL_ULTRA`.
Phase : `PHASE_BASE`, `PHASE_BUILD`, `PHASE_SPECIFIC`, `PHASE_TAPER`, `PHASE_RACE`, `PHASE_CONSOLIDATION`.
Quality kind : `QUALITY_TEMPO_SELECTED`, `QUALITY_THRESHOLD_SELECTED`, `QUALITY_VO2_SELECTED`, `QUALITY_RACE_SPECIFIC_SELECTED`.
Pace : `PACE_{ZONE}_AVAILABLE` (ex. `PACE_T_AVAILABLE`), `PACE_UNAVAILABLE`.
Volume/reste : `VOLUME_LIMITED`, `TAPER_REDUCED`.
Continuous : `CONTINUOUS_EASY`, `CONTINUOUS_RECOVERY`, `CONTINUOUS_LONG_EASY`, `CONTINUOUS_STEADY`.
Structure : `WARMUP_RESERVED`, `COOLDOWN_RESERVED`, `STRUCTURE_UNAVAILABLE`, `PLANNED_REST_DAY`.

Tous machine-readable, déduplication déterministe (`dict.fromkeys`), aucun texte marketing.

## 16. Tests ajoutés

`backend/tests/test_structured_workout_pr234.py` — **64 tests**, tous passants (`64 passed`), couvrant :

A. Déterminisme (quality + continuous) — B. Easy — C. Long easy — D. Recovery — E. Quality goal-aware (5k vs ultra, 10k vs marathon) — F. Phase-aware (10k base vs build, taper conservateur tous goals) — G. Total distance (paramétré 6 valeurs + continuous) — H. Total duration (paramétré 5 valeurs + continuous) — I. Recoveries jamais hors total (distance + duration) — J. Rounding (5 distances non-rondes + 4 durées non-rondes, aucune valeur négative) — K. Pace absente (jamais de pace inventée, y compris `confidence="insufficient"` et un champ de zone malformé/inattendu — branche défensive testée explicitement), ainsi qu'un test dédié pour la garde anti-dégénérescence des reps (VOLUME_LIMITED déclenché spécifiquement par le plancher `_MIN_PER_REP_M`, distinct du plancher de volume préexistant) — L. Pace présente (zone et valeur correctes, dérivation durée uniquement sur zones single-value) — M/N/O/P. DailyAdaptation KEEP/SHORTEN/DOWNGRADE/REST — Q. Maintenance (6 phases, jamais race-specific/VO2) — R. Couverture 5K/10K/Half/Marathon/Ultra + non-régression "ultra jamais VO2" (3 phases) — S. Taper (volume non augmenté, aucun intervalle introduit) — T. None != 0 (pace et durée) — U. Sérialisation (round-trip `model_dump`/`model_validate`, y compris jour de repos).

Complété par du fuzz-testing manuel additionnel (hors suite pytest, exécuté pendant le développement) :
- Invariant distance sur ~35 valeurs (1.0 à 40 km, pas 0.37) × 3 phases × marathon → 0 échec.
- Invariant durée sur 195 valeurs (5 à 199 minutes) × 3 phases × 10k → 0 échec.

## 17. Tests existants rejoués

```
python -m pytest tests/test_workout_generator_v2.py tests/test_daily_adaptation_pr133.py \
    tests/test_pr232a_week_execution.py tests/test_pr232a_prescription_snapshot.py \
    tests/test_pr232a_local_reference_date.py -q
→ 175 passed
```

`tests/test_pr232a_c231_week_endpoint.py` n'a pas pu être collecté dans cet environnement (sandbox sans accès réseau pour installer `fastapi`/`httpx`/`pymongo`/`dotenv` — dépendance manquante préexistante, non liée à cette PR ; confirmé car `server.py` n'a pas été touché).

Suite complète du dossier `tests/` exécutée à titre de contrôle large (`pytest tests/ -k "not server"`) : 2079 passed / 386 failed / 75 errors — **tous les échecs sont préexistants et liés à l'environnement sandbox** (paquets réseau manquants : `httpx`, `dotenv`, `pymongo`, `fastapi` ; variable d'env `REACT_APP_BACKEND_URL` absente ; tests `async def` nécessitant `pytest-asyncio` non installé ; échecs `test_training_state_pr04.py` reproduits identiques hors de toute modification de ce module). Aucun test échoue à cause d'un import ou d'un effet de bord de `structured_workout.py` (module entièrement nouveau, non importé par aucun fichier existant).

## 18. Résultats exacts

- Nouveau module : 953 lignes (dont documentation extensive), aucune dépendance circulaire (import uniquement `periodization`, `plan_goal`, `training_paces`, `workout_generator`).
- Tests PR234 : **64/64 passed**.
- Tests de régression ciblés : **175/175 passed**.
- Aucune anomalie détectée lors de la revue finale du diff (une anomalie de calcul — récupération non budgétée dans le total en base durée — a été détectée et corrigée AVANT la version finale, voir §9 et §20).

## 19. Limites connues

- Le moteur n'est pas câblé dans `server.py`/`today_prescription.py`/`week_plan_bridge.py` dans cette PR (décision documentée §4) — nécessaire pour une PR de câblage/API ultérieure, hors scope #234.
- La bibliothèque de structures qualité V1 est volontairement limitée à 4 formes (`tempo_continuous`, `threshold_intervals`, `vo2_intervals`, `race_specific_steady`) — conforme à la demande "bibliothèque volontairement limitée".
- `race_specific_steady` produit un unique bloc continu (pas de découpage en 2 segments avec recovery courte pour les gros volumes half/marathon) — simplification V1 assumée, déterministe et documentée.
- Pour les prescriptions en base durée, aucune distance n'est dérivée de la pace × durée (choix délibéré, §"Target time" du docstring) — évite un second mécanisme de target implicite.
- Snapshot complet (#235) et intégration frontend détaillée (#236) explicitement hors scope, comme demandé.

## 20. Confirmation

**Aucun merge n'a été effectué.** La branche `copilot/pr-234-structured-workout-prescription` a été poussée avec ces changements ; une Pull Request en **DRAFT** vers `copilot/dev` doit être ouverte (ou l'est déjà) sans fusion.
