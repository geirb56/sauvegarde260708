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
