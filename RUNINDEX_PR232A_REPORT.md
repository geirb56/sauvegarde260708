# PR232A — Training execution bridge + suppression feedback manuel

## Objectif

Brancher PR230 (`training_v2.performed_workout`) à l'API Training et
supprimer définitivement le feedback manuel "Réalisé / Manqué".

## 1. Backend — exécution factuelle par prescription

Nouveau module pur `backend/training_v2/week_execution.py` :

- `build_week_execution(user_id, reference_date, week_start, sessions, garmin_docs)`
  reconcilie les `WorkoutPrescription` d'un `WeeklyPlan` avec les vraies
  activités Garmin (`db.garmin_activities`), via le moteur PR230
  (`training_v2.performed_workout.build_performed_workouts` +
  `garmin.domain_adapter.mongo_garmin_to_observed_activities`).
- Aucune dépendance MongoDB/HTTP directe — le module reste PUR ; l'appelant
  (le endpoint) fournit les documents déjà récupérés.
- Source unique de `actual` : Garmin, via la frontière PR230. Aucun repli sur
  `db.workouts`.
- `None` reste `None` (jamais `0`).
- Une session future reste `planned`.
- Une situation `ambiguous` n'est jamais dégradée en `matched`/`missed`.
- Les activités Garmin non attribuées restent visibles
  (`matching_status == unmatched_actual`), jamais supprimées.

`GET /training/v2/week` expose désormais, pour chaque session :

```
planned_date, workout_type, distance_km, duration_minutes,   # planned
matching_status, adherence_status,                           # PR230 état factuel
actual: { activity_id, distance_km, duration_minutes,        # actual (Garmin only)
          pace_min_per_km, activity_type, start_time }
```

ainsi qu'une liste `week.unmatched_actuals` pour les activités Garmin de la
semaine qui n'ont pu être attribuées à aucune prescription.

Aucun état `DONE`/`MISSED` n'est fabriqué en dehors du vocabulaire PR230
(`MatchingStatus` / `AdherenceStatus`).

## 2. Suppression du feedback manuel

- `POST /api/training/feedback` supprimé de `backend/server.py`
  (aucun consommateur restant).
- Entrée retirée de `backend/access_control.py`.
- `backend/test_interactive_plan.py` (script manuel testant l'ancien
  endpoint) supprimé.
- Frontend (`frontend/src/pages/Dashboard.jsx`) :
  - boutons "Réalisé" / "Manqué" supprimés,
  - `handleFeedback` et l'appel `axios.post(`${API}/training/feedback`, …)`
    supprimés,
  - états `feedbackSubmitting` / `sessionFeedback` supprimés,
  - imports désormais inutilisés (`Check`, `X`, `Button`, `toast`) retirés.

## 3. `/training/v2/week`

Le endpoint ne renvoie plus un plan seul : chaque session porte désormais son
état d'exécution factuel issu de PR230 (voir §1). Le endpoint ne fabrique
jamais `DONE`/`MISSED` — il délègue entièrement au moteur PR230.

## 4. Tests

`backend/tests/test_pr232a_week_execution.py` (15 tests, tous verts) :

- past session sans Garmin ≠ done (`missed`, jamais `completed_as_planned`)
- Garmin compatible → `matched` / `completed_as_planned`
- Garmin modifié → `completed_modified`
- aucun candidat compatible après fenêtre → `missed`
- deux candidats équivalents → `ambiguous` (jamais résolu, même après coup)
- run supplémentaire → `unmatched_actual`, toujours visible
- isolation multi-utilisateur (activité d'un autre user jamais attribuée)
- no-lookahead : session future reste `planned` ; activité future ignorée
- jour de repos : `not_applicable`, jamais `missed`
- `None` jamais remplacé par `0`
- suppression effective de `/training/feedback` (AST sur `server.py`) et de
  l'entrée `access_control.py`
- `week_execution.py` n'a aucune dépendance I/O (pymongo/motor/httpx/fastapi)
  ni appel `datetime.now()`/`date.today()`

Frontend : `frontend/src/__tests__/access-control-v2.test.jsx` vérifie déjà
`axios.post` vers `training/feedback` == 0 appel (passe après suppression).

## Validation

- `python -m pytest backend/tests/ -n 2 --dist loadscope`: 380 failed / 2034
  passed (baseline pré-existant sans ce PR : 382 failed / 2032 passed — les
  échecs restants sont des erreurs d'environnement préexistantes, sans
  rapport avec ce changement : modules `httpx`/`dotenv` absents, tests
  nécessitant un serveur live).
- `npx craco test --watchAll=false --forceExit --testPathPattern="access-control-v2|Dashboard"`:
  5 suites / 108 tests passés.

## Non modifié

Le redesign visuel #232B n'a pas été touché.

---

# Addendum — C231 : corrections d'audit (même PR, non mergée)

L'audit C231 a identifié 5 catégories de correctifs sur le pont d'exécution
PR232A. Tous sont livrés dans cette même PR (non fusionnée).

## C231.1 — TrainingPlanV2 lit le vrai contrat

`frontend/src/pages/TrainingPlanV2.jsx` :

- `getSessionStatusKey()` réécrit intégralement pour lire
  `session.matching_status` / `session.adherence_status` (le vrai contrat
  `/training/v2/week`), plus aucune lecture de faux champs
  `status`/`state`/`completion_status`/`execution_status`.
- Mapping UI appliqué exactement comme spécifié :
  - `workout_type === "rest"` → `rest`
  - `matching_status == planned` (+ `not_applicable`) → `planned`
  - `matching_status == matched` + `completed_as_planned` → `done`
  - `matching_status == matched` + `completed_modified` → `modified`
  - `matching_status == matched` + `completed_unverified` → `unverified`
  - `matching_status == missed` → `missed`
  - `matching_status == ambiguous` → `ambiguous`
  - autre / non résolu → aucun état (jamais fabriqué)
- Suppression définitive du fallback `past day => done` dans
  `WeekSessionRow` : `timelineState` ne dépend plus de la position du jour
  dans la semaine, seulement de `statusKey` (ou `"today"`/`"absent"`).
- `SessionStatePill` étendu avec les états `modified` / `unverified` /
  `ambiguous` (+ clés i18n `en`/`fr`/`es` dans `frontend/src/lib/i18n.js`).
- `frontend/src/__tests__/training-v2-page.test.jsx` réécrit avec le VRAI
  payload backend (`matching_status`/`adherence_status`/`actual`, plus
  `status: DONE/MISSED/...` supprimé) ; nouveaux tests pour `modified`,
  `unverified`, `ambiguous`, l'absence d'appel `/training/feedback`, et le
  cas "session passée non résolue ≠ done".

## C231.2 — `unmatched_actuals` borné à la semaine courante

`backend/training_v2/week_execution.py` : les lignes `unmatched_actual`
(`extra_rows`) sont désormais filtrées à
`week_start <= local_date <= week_start + 6 jours` (date locale Garmin,
via la liste d'`ObservedActivity`). Les activités des 90 jours qui tombent
hors de cette fenêtre ne sont plus jamais exposées.

Tests : `test_unmatched_actual_from_previous_week_is_not_exposed`,
`test_unmatched_actual_from_next_week_is_not_exposed`
(`test_pr232a_week_execution.py`), et test d'intégration endpoint
(`test_pr232a_c231_week_endpoint.py::test_unmatched_actuals_excludes_previous_week_activity`).

## C231.3 — Snapshot immuable de la prescription (BLOCKER architecture)

Nouveau module pur `backend/training_v2/prescription_snapshot.py` :

- `PrescriptionSnapshot` (pydantic frozen) : capture `user_id`,
  `prescription_id`, `planned_date`, `day`, `workout_type`,
  `intensity_class`, `distance_km`, `duration_minutes`.
- `is_freezable(planned_date, reference_date)` : `planned_date <=
  reference_date` (aujourd'hui ou passé). Le futur n'est jamais figé.
- `snapshot_from_prescription(...)` / `resolve_effective_session(...)` :
  résout la prescription EFFECTIVE (figée si un snapshot existe, sinon la
  version live).

Câblage dans `backend/server.py` (`get_training_v2_week`) :

- lecture de `db.training_prescription_snapshots` (par `user_id`, filtrage
  de la fenêtre semaine fait en Python, jamais côté requête Mongo — le faux
  DB de test ignore les filtres `$gte`/`$lte`) ;
- persistance **insert-only** via
  `update_one({...}, {"$setOnInsert": ...}, upsert=True)` — un snapshot une
  fois écrit n'est **jamais** réécrit, même si le plan est recalculé plus
  tard ;
- `week_execution.build_week_execution` construit désormais chaque session
  affichée/matchée à partir de la prescription EFFECTIVE (`SessionExecution.session`),
  pas de la prescription live recalculée — corrige aussi un bug d'affichage
  (le contrat affichait la valeur live même quand le matching utilisait déjà
  le snapshot).
- aucune source `db.workouts` introduite.

Tests (`test_pr232a_prescription_snapshot.py`, 8 tests,
`test_pr232a_week_execution.py` +6 tests) :

- lundi planifié 8 km, moteur recalculé plus tard à 10 km → snapshot reste
  8 km (`test_frozen_snapshot_overrides_a_recomputed_live_prescription`,
  scénario BLOCKER exact du problem statement) ;
- adherence comparée au snapshot, jamais au live ;
- replay à J+N → résultat identique une fois figé
  (`test_replay_at_j_plus_n_gives_identical_result_once_frozen`) ;
- session future jamais proposée à la persistance
  (`test_future_session_is_never_proposed_for_persistence`).

## C231.4 — Date de référence locale cohérente Garmin

Nouveau module pur `backend/training_v2/local_reference_date.py` :

- `resolve_local_reference_date(now_utc, garmin_activities)` dérive le
  décalage UTC à partir de la dernière activité Garmin ayant une paire
  `start_time_gmt`/`start_time_local` valide (même ordre de résolution que
  `garmin.domain_adapter.garmin_local_start_time`), l'applique à `now_utc`,
  et renvoie `.date()`.
- Repli sur la date UTC brute uniquement en l'absence de toute preuve
  Garmin (nouvel utilisateur / payload dégradé) — un repli d'horloge, jamais
  un repli de donnée.
- Bornage de sécurité ±14h sur le décalage dérivé.

`backend/server.py` (`get_training_v2_week`) : `reference_date` est
maintenant calculé via ce module (les activités Garmin sont récupérées
avant), plus jamais via `now_utc.date()` brut.

Tests (`test_pr232a_local_reference_date.py`, 6 tests) : bascule de
frontière autour de minuit UTC+, UTC-, activité la plus récente qui
l'emporte, déterminisme, repli sans activité.

## C231.5 — Suppression legacy `training_feedback` de `/training/today`

`backend/server.py` : le bloc `feedback_cursor =
db.training_feedback.find(...)` et la clé de réponse `recent_feedback` sont
supprimés de `/training/today`. Aucun consommateur runtime restant (le
frontend ne lit déjà plus ce champ depuis PR232A). L'historique en base
n'est pas migré (pas de nécessité de migration destructive ici).

Test : `test_pr232a_c231_week_endpoint.py::test_training_today_has_no_recent_feedback_field`.

## C231.6 — Synthèse des tests ajoutés/mis à jour

| Fichier | Contenu |
| --- | --- |
| `test_pr232a_week_execution.py` | 21 tests (15 existants + 6 nouveaux : week-scoping ×2, snapshot freeze/replay ×4) |
| `test_pr232a_prescription_snapshot.py` | 8 tests (nouveau) |
| `test_pr232a_local_reference_date.py` | 6 tests (nouveau) |
| `test_pr232a_c231_week_endpoint.py` | 4 tests endpoint (nouveau, fake DB + httpx ASGITransport) |
| `test_goal_truth_pr226.py` | mock DB étendu pour stubber `training_prescription_snapshots` (régression corrigée, 62 tests verts) |
| `training-v2-page.test.jsx` | réécrit avec le vrai contrat + 5 nouveaux tests (modified/unverified/ambiguous/no-feedback/past-unresolved) |

Suites ciblées : `test_pr232a_*`, `test_goal_truth_pr226.py`,
`test_handlers_pr228.py`, `test_pr167_training_v2_week_api.py`,
`test_weekly_unification_pr228.py`, `test_dashboard_v2_pr128.py` — **0 échec
imputable à ce changement** (les échecs résiduels constatés sur la suite
complète `backend/tests/` sont un bruit de fond préexistant : fixtures
`redis`/`dotenv` absentes du bac à sable, appels `requests` vers des URLs
relatives sans schéma, tests datés flaky non liés à PR232A/C231 — vérifié
par comparaison avant/après sur les mêmes fichiers).

## Non modifié (C231)

Le redesign visuel #232B n'a pas été touché.

