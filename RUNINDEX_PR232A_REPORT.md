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

---

# Addendum 2 — C231 : corrections finales (même PR, non mergée)

Ce second round corrige les points relevés lors de l'audit du premier
addendum C231.

## C231-bis.1 — Contrat Garmin RÉEL dans `local_reference_date.py`

`_offset_minutes_from_doc()` lisait à tort `garmin_activity.start_time_gmt`
(champ inexistant dans le sous-document moderne persisté par
`gccli_provider.py`). Corrigé pour lire :
- `garmin_activity.start_time` = GMT canonique (convention du modèle
  `GarminActivity` : GMT en priorité, fallback local uniquement si le GMT
  est absent) ;
- `garmin_activity.start_time_local` = local explicite ;
- fallback legacy top-level (`startTimeGMT`/`startTimeLocal`) uniquement
  pour les documents antérieurs à la convention du sous-document.

Tests : `test_pr232a_local_reference_date.py` réécrit avec la forme RÉELLE
persistée (`garmin_activity: {start_time, start_time_local}`), +1 test pour
le fallback legacy top-level. 7/7 verts.

## C231-bis.2 — `/training/today` et `/training/v2/week` : un seul `reference_date`

Nouvelle fonction `server._resolve_canonical_reference_date(now_utc,
garmin_activities_90)` — délègue à
`training_v2.local_reference_date.resolve_local_reference_date` — appelée
par les DEUX endpoints. `/training/today` n'utilise plus `now_utc.date()`.

Tests (`test_pr231_c231_final_corrections.py`) : déterminisme (même
instant + mêmes activités ⇒ même date), garde AST (les deux handlers
appellent bien le même helper, jamais `now_utc.date()`), cas limites
UTC+/UTC- autour de minuit.

## C231-bis.3 — Snapshot = prescription FINALE réellement servie (BLOCKER)

Nouveau module `training_v2/today_prescription.py` —
`resolve_today_final_prescription()` — exécute
Readiness → ReadinessDecision → DailyAdaptation pour LE jour dont
`planned_date == reference_date`, et retourne
`adaptation_result.adapted_workout` (la prescription FINALE réellement
présentée à l'utilisateur), jamais la séance brute du `WeeklyPlan`.

- `/training/today` délègue désormais à ce module (au lieu de dupliquer
  Readiness/DailyAdaptation en ligne) — comportement inchangé.
- `/training/v2/week` : pour la SEULE session du jour (`reference_date`),
  si aucun snapshot n'existe encore, appelle ce MÊME module (fetch
  Garmin connections/daily_metrics dédié, coût nul les appels suivants
  puisque le snapshot déjà gelé devient alors autoritaire) puis fige le
  snapshot à partir de la prescription ADAPTÉE — jamais la brute.
- Résultat : quel que soit l'endpoint appelé en premier pour "aujourd'hui",
  le snapshot gelé est identique (calcul déterministe partagé), et n'est
  jamais réécrit ensuite (insert-only, `$setOnInsert`).

Tests (`test_pr231_c231_snapshot_adaptation.py`) : long_easy 18 km +
SHORTEN ⇒ snapshot = distance adaptée (jamais la brute) ; VERY_LOW ⇒
snapshot REST ; FAVORABLE ⇒ KEEP (snapshot = original) ; replay à J+3 avec
readiness différente ⇒ snapshot Monday inchangé (immuable).

## C231-bis.4 — Index Mongo UNIQUE via le mécanisme d'init existant

Nouveau `services/prescription_snapshot_index.py` —
`ensure_prescription_snapshot_unique_index(db)` — crée l'index UNIQUE
`(user_id, prescription_id)` sur `training_prescription_snapshots`,
suivant le même patron que `services/subscription_index.py` /
`services/paddle_event_index.py`. Câblé dans `create_db_indexes()`
(événement `startup`), pas de création ad-hoc dans le handler.

Tests : `ensure_prescription_snapshot_unique_index` appelle bien
`create_index([("user_id", 1), ("prescription_id", 1)], unique=True)` ;
garde source confirmant l'absence de création ad-hoc dans
`get_training_v2_week`.

## C231-bis.5 — Fail-fast : invariant PR230 dans `build_week_execution`

`build_week_execution()` lève désormais une `ValueError` explicite si une
prescription n'a pas de ligne correspondante dans le ledger PR230 (au lieu
de la filtrer silencieusement). `/training/v2/week` capture cette
exception (500) et vérifie en plus
`len(execution.sessions) == len(weekly_plan.sessions)` — sinon 500
explicite, jamais de semaine tronquée silencieusement.

## C231-bis.6 — Cleanup `WeekV2ActualResponse`

Docstring précisée (représente UNE activité Garmin réelle, réutilisée pour
`session.actual` ET `unmatched_actuals`) ; `unmatched_actuals` utilise
désormais `Field(default_factory=list)`.

## C231-bis.7 — Validation

Nouveaux fichiers de tests : `test_pr231_c231_final_corrections.py` (10
tests : reference_date unifié, index Mongo, fail-fast, cleanup) et
`test_pr231_c231_snapshot_adaptation.py` (4 tests : SHORTEN/REST/KEEP/
replay). Suites ciblées (`test_handlers_pr228.py`,
`test_pr167_training_v2_week_api.py`, `test_pr232a_week_execution.py`,
`test_pr232a_c231_week_endpoint.py`, `test_goal_truth_pr226.py`,
`test_weekly_unification_pr228.py`, `test_pr232a_local_reference_date.py`,
`test_performed_workout_pr230.py`, `test_daily_runtime_pr137.py`) :
**0 échec imputable à ce round de corrections** (seul échec résiduel :
`test_race_day_exact_phase_and_structure`, un flake de rate-limiting
préexistant, confirmé indépendant en relançant le test isolément).

Frontend `TrainingPlanV2` : contrat inchangé par ce round (aucune
modification frontend nécessaire — la structure `planned/actual/
matching_status/adherence_status` exposée par `/training/v2/week` reste
identique).



---

# C231-ter — corrections round 2 (mêmes PR/branche, NE PAS MERGER)

Objectif : fermer 4 blockers restants du bridge PR230/PR231 et rendre la
vérité Prescribed → Performed réellement fiable.

## C231-ter.1 — P0 : vrai identifiant Garmin `external_id`

Bug découvert : `mongo_garmin_to_domain()` résolvait l'id stable via
`doc.get("activity_id") or doc.get("source_activity_id")` — mais le
document RÉELLEMENT persisté par `_ingest_activities` /
`gccli_provider._normalize()` ne porte **jamais** de champ top-level
`activity_id`/`source_activity_id` : seul `external_id` existe au niveau
racine (le sous-document `garmin_activity` porte sa propre copie dans son
propre champ `activity_id`). Résultat : `source_activity_id` était
**toujours `None`** sur des documents réels, cassant silencieusement tout
le matching Garmin↔prescription (PR230) basé sur l'identité de l'activité.

Fix (`backend/garmin/domain_adapter.py`) : nouvelle fonction
`_resolve_stable_activity_id(doc, sub)` avec l'ordre de priorité exact
demandé :
1. `doc["external_id"]`
2. `doc["activity_id"]` (legacy)
3. `doc["source_activity_id"]` (legacy)
4. `garmin_activity.activity_id` (sous-document normalisé)

Aucune fabrication : si aucun candidat n'est une chaîne non vide (ou un
nombre), retourne `None`.

Tests (`tests/test_pr231_external_id_boundary.py`, 5 tests) : document
construit EXACTEMENT comme `_ingest_activities` (top-level `external_id`,
AUCUN `activity_id` top-level, `source="garmin"`, `user_id`, vrai
`garmin_activity`) ⇒ `mongo_garmin_to_domain()`/
`mongo_garmin_to_observed_activity()` résolvent le bon id ⇒ matching PR230
fonctionne de bout en bout ; document legacy avec `activity_id` top-level
toujours résolu ; absence totale d'id ⇒ `None`, jamais fabriqué.

## C231-ter.2 — P0 : Served Prescription Snapshot canonique

Bug découvert : `/training/today` ne lisait/écrivait JAMAIS
`training_prescription_snapshots` — il recalculait systématiquement sa
propre adaptation, ignorant tout snapshot déjà gelé par
`/training/v2/week`. Et `/training/v2/week` écrivait bien un snapshot
insert-only (`$setOnInsert`) pour "aujourd'hui" mais **ne relisait jamais**
la valeur réellement gagnante après l'upsert — sous concurrence, le
perdant de la course pouvait afficher une valeur différente de celle
réellement persistée.

Fix : nouveau module `backend/training_v2/served_prescription.py` —
`get_or_create_served_prescription(db, *, user_id, prescription_id,
planned_date, served_candidate)` :
1. tente un upsert insert-only (`$setOnInsert`, no-op si le doc existe déjà)
2. relit ensuite INCONDITIONNELLEMENT le document (garanti être la valeur
   gagnante, quel que soit l'appelant qui a réellement gagné la course
   grâce à l'atomicité Mongo par document)
3. retourne la prescription effective (`resolve_effective_session`)

Câblé dans les DEUX endpoints :
- `/training/today` : calcule `today_final` comme avant (pour l'affichage
  readiness), mais utilise désormais le résultat GAGNANT de
  `get_or_create_served_prescription()` pour la prescription réellement
  affichée (distance/durée/type).
- `/training/v2/week` : remplace l'ancien "substitute into
  sessions_for_execution" (écriture sans relecture) par un appel à la même
  fonction ; le résultat alimente `sessions_for_execution` ET
  `frozen_snapshots` avant `build_week_execution`.

Tests (`tests/test_pr231_served_prescription.py`, 6 tests) : premier appel
crée le snapshot ; snapshot existant jamais réécrit (candidat différent
ignoré) ; Week-first→Today identique ; Today-first→Week identique ;
appels concurrents (`asyncio.gather`) ⇒ un seul document Mongo, deux
réponses identiques ; candidat REST préservé.

## C231-ter.3 — P0 : interdiction du snapshot rétroactif inventé

Bug découvert : `build_week_execution()` proposait un nouveau snapshot dès
qu'un jour était "freezable" (`planned_date <= reference_date`), y compris
pour un jour PASSÉ jamais réellement ouvert/servi — fabriquant alors une
prescription à partir du plan recalculé EN DIRECT aujourd'hui, ce qui peut
différer de ce qui aurait vraiment été prescrit à l'époque.

Fix (`backend/training_v2/week_execution.py`) :
- la condition de proposition d'un NOUVEAU snapshot est resserrée à
  `planned_date == reference_date` (aujourd'hui uniquement) ; un jour passé
  sans snapshot existant n'est plus jamais figé rétroactivement.
- pour un jour passé (`planned_date < reference_date`), non-repos, sans
  snapshot existant : exclu du matching PR230 et remplacé par une ligne
  explicite `MatchingStatus.PRESCRIPTION_UNAVAILABLE` /
  `AdherenceStatus.PRESCRIPTION_UNAVAILABLE` (nouveaux membres d'énum dans
  `training_v2/performed_workout.py`) — jamais missed/matched/
  completed_modified.
- les jours de repos (`workout_type == "rest"`) sont exemptés : aucune
  valeur de distance/durée à fabriquer, et PR230 gère déjà le repos de
  façon déterministe (`PLANNED`/`NOT_APPLICABLE`) indépendamment de
  `reference_date`.
- PR230 continue de montrer la vraie activité Garmin (actual/unmatched)
  selon son propre contrat — seule l'invention de ce qui aurait été
  *prescrit* est bannie.

Tests conflictuels mis à jour (6 tests dans
`tests/test_pr232a_week_execution.py` :
`test_past_without_garmin_is_never_done`,
`test_no_compatible_activity_after_window_is_missed`,
`test_two_equivalent_candidates_are_ambiguous`,
`test_extra_run_is_unmatched_actual_and_stays_visible`,
`test_multi_user_isolation`, plus l'invariant fail-fast dans
`test_pr231_c231_final_corrections.py`) : ces scénarios simulent
légitimement "ce jour a déjà été servi/gelé quand il était courant" via un
`frozen_snapshots` explicite, préservant le test du VRAI matching PR230
sous le contrat resserré.

Nouveaux tests (`tests/test_pr231_c231_corrections2.py`, items 3) :
lundi jamais ouvert, plan recalculé différemment mercredi ⇒ aucun
snapshot lundi créé, `PRESCRIPTION_UNAVAILABLE` (jamais missed/matched) ;
replay déterministe à J+8 (statut identique) ; jour de repos jamais
ouvert exempté ; le jour "aujourd'hui" reste normalement gelable.

## C231-ter.4 — P1 : index UNIQUE snapshot = prérequis critique de démarrage

Bug découvert : `_ensure_prescription_snapshot_unique_index(db)` était
appelé À L'INTÉRIEUR du gros bloc `try/except` fail-open de
`create_db_indexes()` — contrairement à
`_ensure_paddle_events_unique_index(db)`, appelé AVANT ce bloc (critique,
fail-fast). Une erreur de création d'index était donc avalée en silence,
laissant le serveur démarrer alors que l'immuabilité des snapshots n'était
plus garantie.

Fix (`backend/server.py`) : `_ensure_prescription_snapshot_unique_index(db)`
déplacé juste après `_ensure_paddle_events_unique_index(db)`, avant le
`try:` du bloc fail-open — exactement le même patron que Paddle.

Tests (`tests/test_pr231_c231_corrections2.py`, items 4) :
`create_db_indexes()` appelle bien le helper avec la bonne db ; une
exception levée par le helper se propage (`pytest.raises`) et le bloc
fail-open (`db.workouts.create_index`, etc.) n'est jamais atteint ;
vérification par inspection de source que l'appel précède bien le `try:`.

## C231-ter.5 — Frontend : ne jamais inventer "done"

Bug découvert : `getSessionStatusKey()` dans
`frontend/src/pages/TrainingPlanV2.jsx` retournait `"done"` par défaut
quand `matching_status === "matched"` mais `adherence_status` était
inconnu/null/invalide.

Fix : le fallback devient `"unverified"` (jamais `"done"`). Mapping
exact préservé : `completed_as_planned → done`,
`completed_modified → modified`, `completed_unverified → unverified`,
autre/null → `unverified` (jamais `"done"` par défaut).

Tests (`frontend/src/__tests__/training-v2-page.test.jsx`, 2 nouveaux
tests) : `matching_status="matched"` + `adherence_status` inconnu ⇒
`session-status-unverified` affiché, jamais `session-status-done` ;
idem avec `adherence_status = null`.

## C231-ter.6 — Validation

Corrections de fixtures de tests pré-existantes (non liées à un bug de
production) : trois harnais de fausse base Mongo partagés
(`tests/test_handlers_pr228.py`, `tests/test_training_source_of_truth_pr216.py`,
`tests/test_goal_truth_pr226.py`) ne géraient pas l'opérateur
`$setOnInsert` dans leur `update_one` simulé — un manque resté invisible
tant que rien ne relisait la valeur persistée. Le nouveau chemin de
lecture-après-écriture de `get_or_create_served_prescription()` l'a
révélé ; corrigé en alignant ces harnais sur le patron déjà utilisé par
`tests/test_pr232a_c231_week_endpoint.py`.

Commandes exécutées :
```
cd backend && python3 -m pytest tests/test_pr231_external_id_boundary.py \
  tests/test_pr231_served_prescription.py \
  tests/test_pr231_c231_corrections2.py \
  tests/test_pr231_c231_final_corrections.py \
  tests/test_pr231_c231_snapshot_adaptation.py \
  tests/test_pr232a_week_execution.py \
  tests/test_pr232a_c231_week_endpoint.py \
  tests/test_pr232a_local_reference_date.py \
  tests/test_performed_workout_pr230.py \
  tests/test_mongo_garmin_boundary_pr137.py \
  tests/test_handlers_pr228.py \
  tests/test_weekly_unification_pr228.py \
  tests/test_goal_truth_pr226.py \
  tests/test_training_source_of_truth_pr216.py \
  tests/test_paddle_integrity_pr223.py \
  -q -k "not test_race_day_exact_phase_and_structure"
# → 348 passed
cd frontend && npx craco test --watchAll=false --forceExit \
  src/__tests__/training-v2-page.test.jsx
# → 22 passed
```

Résultat : **0 échec imputable à ce round de corrections.** Suite complète
(`python3 -m pytest` sans filtre) : 300 échecs pré-existants, tous
confirmés indépendants de ce changement (comparaison différentielle avant/
après sur la liste des tests en échec) — connexions réseau externes
indisponibles dans le sandbox (`localhost:8001`, hostname
`charge-load.preview.emergentagent.com`), fixture Redis manquante
(`test_reliable_queue.py`), et un flake connu de rate-limiting
(`test_race_day_exact_phase_and_structure`, confirmé passant isolément).
Seul échec pré-existant et non lié : `test_g_server_uses_boundary`
(assertion sur une fonction renommée avant ce round, vérifié identique sur
l'état du dépôt avant modification).

Limites connues : le retrait des jours de repos de la diversion
"historique non disponible" repose sur `workout_type == "rest"` restant
la SEULE valeur utilisée pour désigner un jour de repos dans ce pipeline ;
si un futur type de séance neutre est introduit, ce garde devra être
étendu explicitement.

## C231-quater.1 — P0 : `/training/today` affiche TOUJOURS la served_prescription canonique

Bug corrigé : `adaptation_applied` était calculé à partir du recalcul
readiness **courant** (live), alors que le frontend s'en servait pour
choisir la séance affichée (`true` → `adapted_prescription`, `false` →
`planned_session`). Un snapshot déjà figé (ex. 12,6 km suite à une
alerte CAUTION passée) pouvait donc être écrasé à l'affichage par le
plan brut (18 km) dès qu'un appel ultérieur repassait en
FAVORABLE/KEEP — alors même que la prescription réellement servie
(`served_prescription`, issue de `get_or_create_served_prescription`)
restait 12,6 km en base.

Corrigé :
- `backend/server.py` (`/training/today`) expose désormais
  explicitement une clé canonique `served_prescription` (= la valeur
  FIGÉE, atomique, déjà utilisée pour construire `adapted_prescription`
  — celui-ci reste présent pour compatibilité et est garanti
  strictement identique à `served_prescription`).
- Le indicateur `adaptation_applied` reste calculé (recalcul live) mais
  redevient **purement informatif** — il n'est plus utilisé nulle part
  pour décider quelle séance est affichée. Le nouveau booléen
  `session_modified_from_planned` (comparaison RÉELLE entre la
  prescription servie et le plan brut) remplace `adaptation_applied`
  comme condition d'exposition du champ hérité `adaptive_session`.
- `frontend/src/pages/TrainingPlanV2.jsx` : la sélection de
  `todaySession` priorise désormais inconditionnellement
  `todayData.served_prescription`, avec repli sur
  `adapted_prescription` → `adaptive_session` → `planned_session` →
  `original_prescription`. L'ancien ternaire piloté par
  `adaptation_applied` a été supprimé.

Tests (`backend/tests/test_pr231_c231_corrections3.py`, end-to-end via
le vrai handler FastAPI + fausse base Mongo) :
- `test_today_endpoint_exposes_served_prescription_key_matching_frozen_snapshot`
- `test_today_endpoint_served_prescription_wins_even_when_adaptation_applied_is_false`
- `test_week_first_then_today_show_identical_served_prescription`
- `test_today_first_then_week_show_identical_served_prescription`

Tests (`frontend/src/__tests__/training-v2-page.test.jsx`) :
"C231 round 2 item 1: today always shows served_prescription, never the
stale planned_session even when adaptation_applied is false" — vérifie
que la carte "aujourd'hui" affiche 12,6 km et n'affiche JAMAIS 18 km,
même avec `adaptation_applied: false` dans la réponse mockée.

## C231-quater.2 — P0/P1 : `prescription_unavailable` reste au niveau du bridge, jamais dans les enums PR230

`MatchingStatus`/`AdherenceStatus` (PR230, `training_v2/performed_workout.py`)
avaient été pollués par un round précédent avec une valeur
`PRESCRIPTION_UNAVAILABLE` que `build_performed_workouts()` ne produit
jamais réellement (elle était fabriquée artificiellement dans le
bridge). Corrigé :
- `MatchingStatus` restauré à exactement `planned | matched | missed |
  ambiguous | unmatched_actual`.
- `AdherenceStatus` restauré à exactement `pending |
  completed_as_planned | completed_modified | completed_unverified |
  missed | ambiguous | unmatched_actual | not_applicable`.
- `backend/tests/test_performed_workout_pr230.py`
  (`test_engine_never_emits_a_completed_matching_status`) restauré pour
  vérifier exactement cet ensemble canonique (aucune modification
  sémantique du moteur PR230).
- `backend/training_v2/week_execution.py` réécrit : le fait "ce jour
  n'a jamais été réellement servi/figé" vit désormais UNIQUEMENT dans
  un champ dédié bridge/API,
  `SessionExecution.execution_status = EXECUTION_STATUS_PRESCRIPTION_UNAVAILABLE`
  (`row` devient `Optional[PerformedWorkout] = None` pour ce cas — plus
  aucune ligne PR230 fabriquée). PR230 n'est simplement jamais consulté
  pour ces prescriptions (`unavailable_prescription_ids`), au lieu de
  recevoir une fausse ligne.
- `backend/training_v2/training_week_response.py`
  (`WeekV2SessionResponse`) : nouveau champ `execution_status:
  Optional[str] = None` ; `workout_type`/`intensity_class` élargis en
  `Optional[str]` (aucune valeur fabriquée pour un jour non fiable).
- `backend/server.py` (`/training/v2/week`) : nouvelle fonction
  `_session_response()` qui construit une réponse "neutre" (tous les
  champs prévus à `None`, `execution_status` renseigné) quand
  `execution_status == EXECUTION_STATUS_PRESCRIPTION_UNAVAILABLE`,
  sinon la réponse normale issue de la ligne PR230.

Tests :
- `backend/tests/test_pr231_c231_corrections3.py` :
  `test_pr230_matching_status_enum_has_no_prescription_unavailable`,
  `test_pr230_adherence_status_enum_has_no_prescription_unavailable`,
  `test_week_session_response_has_dedicated_execution_status_field`.
- `backend/tests/test_pr231_c231_corrections2.py` : les 3 scénarios de
  jour jamais ouvert ont été réécrits pour vérifier `row is None` +
  `execution_status == EXECUTION_STATUS_PRESCRIPTION_UNAVAILABLE`
  (import direct depuis `training_v2.week_execution`) au lieu des
  anciennes assertions sur les enums PR230.

## C231-quater.3 — P0 : aucune prescription historique reconstruite affichée comme factuelle

Confirmé/étendu à l'échelle end-to-end (endpoint réel) : pour un jour
`planned_date < reference_date` sans snapshot existant, la réponse
`/training/v2/week` ne contient AUCUNE valeur recalculée aujourd'hui
présentée comme un fait historique — `workout_type`, `intensity_class`,
`distance_km`, `duration_minutes`, `matching_status`,
`adherence_status`, `actual` sont tous `None`, et
`execution_status = "prescription_unavailable"` signale explicitement
l'état. Une vraie activité Garmin survenue ce jour-là continue de
remonter dans `unmatched_actuals` (jamais perdue), sans jamais servir à
fabriquer un faux verdict "matched"/"missed" contre une prescription
non fiable.

Frontend (déjà en place, ré-audité ce round) :
`getSessionStatusKey()` retourne `"unavailable"` dès que
`execution_status === "prescription_unavailable"` (vérifié AVANT le
test "jour de repos") ; `WeekSessionRow` affiche alors le libellé
neutre `sessionStates.unavailable` ("Prescription non enregistrée" /
"Prescription not recorded" / "Prescripción no registrada" — FR/EN/ES
dans `frontend/src/lib/i18n.js`), sans badge Done/Missed/Modified et
sans distance/durée affichée.

Tests (`backend/tests/test_pr231_c231_corrections3.py`, end-to-end) :
- `test_week_endpoint_monday_never_served_reports_prescription_unavailable`
- `test_week_endpoint_real_garmin_activity_for_unserved_monday_still_surfaces_as_unmatched`

Tests (frontend) : "C231 round 2 item 3: a prescription_unavailable
session shows a neutral state, no Done/Missed/Modified badge, no
fabricated distance".

## C231-quater.4 — Validation

Commandes exécutées :
```
cd backend && python3 -m pytest \
  tests/test_pr232a_week_execution.py \
  tests/test_pr231_c231_corrections2.py \
  tests/test_pr231_c231_corrections3.py \
  tests/test_pr231_c231_final_corrections.py \
  tests/test_performed_workout_pr230.py \
  tests/test_pr232a_c231_week_endpoint.py \
  tests/test_pr231_served_prescription.py \
  -q -p no:cacheprovider
# → 142 passed

cd frontend && npx craco test --watchAll=false --forceExit \
  src/__tests__/training-v2-page.test.jsx
# → 24 passed
```

Suite complète backend (`python3 -m pytest` sans filtre) : ré-exécutée
pour dépister une régression éventuelle liée à l'élargissement de
`WeekV2SessionResponse.workout_type`/`intensity_class` en `Optional` et
au changement de forme de `SessionExecution` — les échecs observés
(mêmes ~300, réseau externe indisponible dans le sandbox, fixture Redis
manquante `test_reliable_queue.py`, tests `test_pr175_training_v2_cycle.py`
en 401 au lieu de 200/403) sont confirmés hors du périmètre des fichiers
modifiés par ce round (aucun ne référence `week_execution`,
`performed_workout`, `training_week_response`, `served_prescription`,
ni les routes `/training/today` / `/training/v2/week`).

Checklist de validation demandée :
- external_id réel Garmin toujours PASS (C231-ter.1, inchangé)
- served snapshot atomicité toujours PASS
  (`test_week_first_then_today_show_identical_served_prescription`,
  `test_today_first_then_week_show_identical_served_prescription`)
- index UNIQUE fail-fast toujours PASS (C231-bis.4/C231-ter.4, inchangé)
- no retroactive snapshot toujours PASS (C231-ter.3, inchangé — aucune
  régression : `unavailable_prescription_ids` ne déclenche jamais
  d'écriture de snapshot)
- no-lookahead : PASS (`build_performed_workouts` inchangé sémantiquement)
- multi-user isolation : PASS (isolation par `user_id` inchangée dans
  `build_week_execution`)
- None != 0 : PASS (`WeekV2SessionResponse` : tous les champs
  "prescription_unavailable" sont `None`, jamais `0`)
- zéro `/training/feedback` : PASS ("never calls the legacy
  /training/feedback endpoint" toujours vert)
- frontend n'invente jamais Done : PASS (tests dédiés item 3 + tests
  C231-ter.5 toujours verts)

Aucune modification du redesign visuel #232B. Aucun merge effectué.

## C231-quinquies.1 — P0 : Dashboard doit afficher la `served_prescription` canonique

Bug corrigé : `frontend/src/pages/Dashboard.jsx` choisissait encore la
séance affichée via `todaySession.adaptation_applied` (`true` →
`adaptive_session` + comparaison "originale grisée / adaptée en
surbrillance", `false` → `planned_session`) — alors que
`adaptation_applied` est purement informatif depuis C231-quater.1. Ce
choix pouvait afficher le plan brut (ex. 18 km) au lieu du snapshot
réellement servi (ex. 12,6 km), ou tenter d'afficher
`todaySession.adaptive_session` (potentiellement `null` quand la
séance servie ne diffère pas réellement du plan) dans le cas où
`adaptation_applied` restait vrai suite à un recalcul live (ex.
REDUCE) — un scénario auparavant susceptible de planter/afficher un
état vide.

Corrigé :
- La séance affichée est désormais calculée par une chaîne de
  priorité stricte, indépendante de `adaptation_applied` :
  `served_prescription` → `adapted_prescription` → `adaptive_session`
  → `planned_session` → `original_prescription`.
- `adaptation_applied` reste utilisé UNIQUEMENT pour afficher le
  bandeau d'information ("Adapté : …"), jamais pour choisir quelle
  séance est rendue.
- Suppression de l'ancienne vue comparative "séance originale grisée +
  séance adaptative en surbrillance" pilotée par `adaptation_applied` :
  un seul `SessionCard`, alimenté par la prescription canonique
  ci-dessus, est désormais rendu — élimine tout risque d'afficher une
  ancienne valeur (ex. 18 km) à côté de la valeur servie (ex. 12,6 km).
- `TrainingPlanV2.jsx` (C231-quater.1) et `Dashboard.jsx` partagent
  désormais exactement la même règle de priorité et affichent donc
  toujours la même séance "aujourd'hui".

Tests (`frontend/src/__tests__/dashboard-training-v2.test.jsx`, 3
nouveaux) :
- "C231-final: served_prescription (12.6) wins over stale
  planned_session (18) even when adaptation_applied=false" — plan brut
  18 km, snapshot servi 12,6 km, `adaptation_applied: false` ⇒ la
  carte affiche "12.6" et n'affiche jamais "18 km".
- "C231-final: authoritative served snapshot (18) stays displayed when
  adaptive_session is null, no crash" — snapshot servi 18 km,
  `adaptation_applied: true` (action REDUCE simulée),
  `adaptive_session: null` ⇒ la carte affiche toujours "18 km", sans
  plantage.
- "C231-final: source check — adaptation_applied is never used to
  select the displayed session" — vérifie statiquement l'absence de
  `todaySession.adaptation_applied ?` dans `Dashboard.jsx`.

## C231-quinquies.2 — P0 : aucune exception historique pour les jours de repos

Bug corrigé : `training_v2/week_execution.py` n'appliquait la
diversion `prescription_unavailable` que si le plan recalculé
aujourd'hui n'était PAS `rest` (`frozen is None and not is_rest and
planned_date < reference_date`). Cette exception était incorrecte :
sans snapshot historique, il est impossible de savoir si ce jour était
réellement un jour de repos au moment où il aurait dû être servi.

Corrigé : condition simplifiée à `frozen is None and planned_date <
reference_date` — indépendante de `workout_type`. Un jour passé sans
snapshot est TOUJOURS `execution_status="prescription_unavailable"`
(`workout_type=None`, `intensity_class=None`, `distance_km=None`,
`duration_minutes=None`, `matching_status=None`,
`adherence_status=None`, `actual=None`), y compris quand le plan
recalculé aujourd'hui dit `rest`. PR230 n'est jamais consulté pour ce
jour. Un jour AVEC un snapshot historique existant (repos inclus)
continue de passer par le matching PR230 normal (`planned` /
`not_applicable` reste un résultat légitime dans ce cas précis).
L'activité Garmin réelle éventuelle de ce jour reste visible via
`unmatched_actuals`.

Tests (`backend/tests/test_pr231_c231_corrections2.py`, réécrits) :
- A. `test_past_rest_day_never_opened_is_now_prescription_unavailable`
  — lundi passé, aucun snapshot, plan recalculé aujourd'hui = REST ⇒
  `execution_status == "prescription_unavailable"`, `row is None`
  (jamais `planned`/`not_applicable`).
- B. `test_past_rest_day_with_existing_frozen_snapshot_uses_pr230_normally`
  — lundi passé avec un snapshot historique réel REST déjà figé ⇒
  `execution_status is None`, `row.matching_status == PLANNED`,
  `row.adherence_status == NOT_APPLICABLE` (PR230 utilisé normalement).
- C. `test_real_garmin_activity_on_unavailable_rest_day_still_surfaces_as_unmatched`
  — activité Garmin réelle un lundi sans snapshot ⇒
  `execution_status == "prescription_unavailable"` côté session, mais
  l'activité reste présente dans `extra_rows`/`unmatched_actuals`.

`backend/tests/test_pr232a_week_execution.py::test_rest_day_is_not_applicable`
mis à jour pour fournir un snapshot historique REST déjà figé
(reproduisant le scénario B ci-dessus), au lieu de s'appuyer sur
l'ancienne exception désormais supprimée.

## C231-quinquies.3 — Validation

Commandes exécutées :
```
cd backend && python3 -m pytest \
  tests/test_pr232a_week_execution.py \
  tests/test_pr231_c231_corrections2.py \
  tests/test_pr231_c231_corrections3.py \
  tests/test_pr231_c231_final_corrections.py \
  tests/test_performed_workout_pr230.py \
  tests/test_pr232a_c231_week_endpoint.py \
  tests/test_pr231_served_prescription.py \
  -q -p no:cacheprovider
# → 144 passed

cd frontend && npx craco test --watchAll=false --forceExit \
  src/__tests__/dashboard-training-v2.test.jsx \
  src/__tests__/training-v2-page.test.jsx
# → 28 + 24 = 52 passed
```

Suite complète backend (`python3 -m pytest` sans filtre) : ré-exécutée,
mêmes ~300 échecs pré-existants (réseau externe/Redis indisponibles
dans le sandbox), confirmés indépendants des fichiers modifiés dans ce
round.

Checklist de non-régression demandée :
- PR230 enums inchangés/canoniques : PASS (`MatchingStatus`/
  `AdherenceStatus` non touchés dans ce round, tests dédiés toujours
  verts)
- served snapshot atomicité : PASS (`get_or_create_served_prescription`
  inchangé)
- external_id Garmin réel : PASS (C231-ter.1, inchangé)
- no-lookahead : PASS (`build_performed_workouts` inchangé
  sémantiquement)
- multi-user isolation : PASS (isolation par `user_id` inchangée)
- None != 0 : PASS (aucun champ `prescription_unavailable` n'est `0`)
- aucune reconstruction rétroactive : PASS — la correction du round
  RENFORCE cette garantie (plus aucune exception ne permet à un
  recalcul live de fabriquer un état historique, même `rest`)
- zéro `/training/feedback` : PASS
- TrainingPlanV2 et Dashboard affichent la même served prescription :
  PASS — les deux composants partagent désormais la même chaîne de
  priorité `served_prescription → adapted_prescription →
  adaptive_session → planned_session → original_prescription`
- tests backend + frontend ciblés : 0 fail (144 backend + 52 frontend)

Aucune modification du redesign visuel #232B. Aucun merge effectué.

# Addendum 3 — C231-sexies : micro-correction finale (même PR, NE PAS MERGER)

Dernier blocker UX/contrat : le bandeau "Adapté" du Dashboard était gated par
`adaptation_applied`, qui décrit le recalcul readiness LIVE de l'appel en
cours, jamais la prescription réellement servie/snapshottée. Résultat : un
faux positif possible — `served=18, planned=18, live action=REDUCE,
adaptation_applied=true, adaptive_session=null` affichait à tort "Adapté :
caution" alors que la séance affichée (18 km) est strictement identique au
plan brut.

## C231-sexies.1 — P1 : bandeau "Adapté" gated par `session_modified_from_planned`, jamais `adaptation_applied`

**Backend** (`backend/server.py`, endpoint `/training/today`) : le signal
`session_modified_from_planned` (déjà calculé en interne — comparaison
ground-truth `served_prescription_runtime != planned_session_runtime`,
utilisé pour dériver `adaptive_session`) est désormais explicitement exposé
dans la réponse JSON sous la clé `session_modified_from_planned`.

```python
"session_modified_from_planned": session_modified_from_planned,
```

**Frontend** (`frontend/src/pages/Dashboard.jsx`) : la condition du bandeau
d'adaptation est remplacée :

- avant : `todaySession.adaptation_applied && (...)` avec affichage de
  `todaySession.adaptation_reason` (texte potentiellement issu d'un recalcul
  live contradictoire, jamais persisté avec le snapshot servi)
- après : `todaySession.session_modified_from_planned === true && (...)`
  avec un libellé neutre fixe `"Séance adaptée"` (clé i18n
  `trainingPlanExtended.sessionAdapted`, ajoutée EN + FR) — **aucune**
  lecture de `adaptation_reason`, conformément à l'option "sûre" du besoin :
  ne pas afficher une raison potentiellement fausse tant qu'elle n'est pas
  persistée avec le snapshot.

Le choix de la séance affichée (`canonicalSession`, chaîne de priorité
`served_prescription → adapted_prescription → adaptive_session →
planned_session → original_prescription`) est totalement inchangé — seul le
bandeau informatif change de source de vérité.

## C231-sexies.2 — Tests obligatoires (scénarios A/B/C)

Ajoutés dans `frontend/src/__tests__/dashboard-training-v2.test.jsx` :

- **Scénario A** — `planned=18, served=18, adaptation_applied=true,
  live action=REDUCE, session_modified_from_planned=false` ⇒ aucun bandeau
  `[data-testid="adaptation-notice"]` rendu, aucune trace du texte
  `adaptation_reason` ("caution") dans le DOM.
- **Scénario B** — `planned=18, served=12.6,
  session_modified_from_planned=true` ⇒ bandeau `"Séance adaptée"` visible
  (texte neutre, sans `adaptation_reason`), carte affichant `12.6 km` (jamais
  `18 km`).
- **Scénario C** — vérification statique : le source de `Dashboard.jsx` ne
  contient plus aucune occurrence de `todaySession.adaptation_applied` et
  contient bien `session_modified_from_planned === true`.

Ajoutés dans `backend/tests/test_pr231_c231_corrections3.py` :

- `test_today_endpoint_exposes_session_modified_from_planned_true_when_snapshot_differs`
  — un snapshot gelé à 12.6 km (différent du plan live) ⇒
  `session_modified_from_planned is True`.
- `test_today_endpoint_session_modified_from_planned_false_when_served_equals_planned`
  — premier appel du jour (snapshot gelé = résultat de CE même appel) ⇒
  `session_modified_from_planned` est cohérent avec l'égalité
  `served_prescription == planned_session`.

## C231-sexies.3 — Validation

```
cd frontend && npx craco test --watchAll=false --forceExit \
  src/__tests__/dashboard-training-v2.test.jsx
# → 31 passed (3 nouveaux scénarios A/B/C + 28 pré-existants)

cd backend && python3 -m pytest \
  tests/test_pr231_c231_corrections3.py -q
# → 11 passed (2 nouveaux + 9 pré-existants)

cd backend && python3 -m pytest \
  tests/test_pr232a_week_execution.py \
  tests/test_pr231_c231_corrections2.py \
  tests/test_pr231_c231_corrections3.py \
  tests/test_pr231_c231_final_corrections.py \
  tests/test_performed_workout_pr230.py \
  tests/test_pr232a_c231_week_endpoint.py \
  tests/test_pr231_served_prescription.py \
  -q
# → 146 passed
```

Checklist de non-régression :
- `served_prescription` reste l'autorité Dashboard + TrainingPlanV2 : PASS
  (chaîne de priorité inchangée, seul le bandeau informatif change de
  source)
- historique rest sans snapshot = `prescription_unavailable` : PASS
  (C231-quinquies.2 inchangé dans ce round)
- PR230 enums inchangés : PASS
- no-lookahead : PASS
- multi-user : PASS (isolation par `user_id` inchangée)
- None != 0 : PASS
- zéro `/training/feedback` : PASS
- tests backend + frontend ciblés : 0 fail (11 + 146 backend, 31 frontend)

Aucune modification du redesign visuel #232B. Aucun merge effectué.

# Addendum 4 — C231-septies : `modified_from_planned` immuable (même PR, NE PAS MERGER)

Dernier blocker : `session_modified_from_planned` était recalculé À CHAQUE
appel de `/training/today` par comparaison `served_prescription_runtime !=
planned_session_runtime`. Or `served_prescription` est figée (snapshot) alors
que `planned_session` est recalculé live — le booléen pouvait donc changer
rétroactivement pour une séance déjà servie et qui n'avait, elle, jamais
changé (faux positif si le plan live dérive plus tard vers une autre valeur ;
faux négatif si le plan live rejoint fortuitement la valeur servie).

## C231-septies.1 — `PrescriptionSnapshot.modified_from_planned` (champ immuable)

`backend/training_v2/prescription_snapshot.py` : ajout du champ
`modified_from_planned: Optional[bool] = None` sur `PrescriptionSnapshot`.
Représente "la prescription réellement servie différait-elle du plan brut
AU MOMENT où le snapshot a été créé ?" — jamais recalculé après coup.
`snapshot_from_prescription()` accepte désormais un paramètre
`modified_from_planned: Optional[bool] = None` transmis tel quel (jamais
dérivé en interne).

Compatibilité anciens snapshots (scénario F) : un document Mongo persisté
avant l'existence de ce champ n'a pas la clé `modified_from_planned` ;
Pydantic le désérialise alors automatiquement en `None` (valeur par défaut)
— jamais reconstruit à partir du plan live.

## C231-septies.2 — Calcul UNE SEULE FOIS dans `get_or_create_served_prescription`

`backend/training_v2/served_prescription.py` :

- Nouveau paramètre `planned_prescription: Optional[WorkoutPrescription] = None`.
- À la création du snapshot (première fois seulement — `$setOnInsert`) :
  `modified_from_planned = _prescription_core_fields(served_candidate) !=
  _prescription_core_fields(planned_prescription)`, où
  `_prescription_core_fields` compare `(workout_type, intensity_class,
  distance_km, duration_minutes)` — exactement les champs persistés par le
  snapshot (exclut délibérément `reason_codes`, qui peut différer entre deux
  prescriptions structurellement identiques).
- Si un snapshot existe déjà, `planned_prescription`/`served_candidate` de
  CET appel sont entièrement ignorés (comme avant pour la prescription
  elle-même) — le booléen n'est JAMAIS recalculé après coup.
- Nouveau type de retour `ServedPrescriptionResult{prescription,
  modified_from_planned}` : les deux valeurs proviennent TOUJOURS du MÊME
  document Mongo gagnant (jamais une prescription d'un appel combinée à un
  booléen recalculé par un autre) — garantit la convergence Today/Week en
  cas de concurrence (scénario E).

## C231-septies.3 — `/training/today` et `/training/v2/week`

`backend/server.py` :

- `/training/today` : appelle `get_or_create_served_prescription(...,
  planned_prescription=planned_prescription)` et lit directement
  `session_modified_from_planned = served_result.modified_from_planned` —
  suppression totale de l'ancienne comparaison
  `served_prescription_runtime != planned_session_runtime`.
- `/training/v2/week` : même appel enrichi pour le slot "aujourd'hui"
  (`planned_prescription=sessions_for_execution[today_index]`, capturé
  AVANT écrasement par la valeur servie) ; le cache local
  `frozen_snapshots[...]` est reconstruit avec
  `modified_from_planned=served_result.modified_from_planned` (jamais
  recalculé) pour rester cohérent avec ce que `/training/today` lirait pour
  le même snapshot.
- `week_execution.py` : le chemin de repli (rarement emprunté, car
  `server.py` traite déjà "aujourd'hui" en amont) qui gèle un snapshot à
  partir de la session brute du `WeeklyPlan` passe désormais explicitement
  `modified_from_planned=False` (servi == planifié par construction, aucune
  adaptation n'a eu lieu sur ce chemin).

## C231-septies.4 — Frontend

Aucun changement : `Dashboard.jsx` utilisait déjà
`todaySession.session_modified_from_planned === true` (addendum 3) — `true`
⇒ bandeau, `false`/`null`/absent ⇒ aucun bandeau. Nouveau test ajouté pour
couvrir explicitement le cas `null` (scénario F, snapshot pré-migration).

## C231-septies.5 — Tests obligatoires (scénarios A-F)

`backend/tests/test_pr231_served_prescription.py` (niveau module, bas
niveau) :
- `test_scenario_A_creation_unmodified_when_served_equals_planned` — plan=18,
  served=18 ⇒ `modified_from_planned is False`.
- `test_scenario_B_creation_modified_when_served_differs_from_planned` —
  plan=18, served=12.6 ⇒ `modified_from_planned is True`.
- `test_scenario_C_live_plan_change_afterwards_does_not_flip_false_to_true` —
  snapshot créé `False` ; un appel ultérieur avec un `planned_prescription`
  différent (15) ne change rien : reste `False`.
- `test_scenario_D_live_plan_converges_afterwards_does_not_flip_true_to_false`
  — snapshot créé `True` ; un appel ultérieur dont le plan live "rejoint" la
  valeur servie (12.6) ne change rien : reste `True`.
- `test_scenario_E_concurrent_today_week_converge_on_same_winner_and_flag` —
  deux candidats concurrents (`asyncio.gather`) ⇒ un seul document Mongo,
  prescription ET `modified_from_planned` des deux appelants identiques et
  cohérents avec le document gagnant.
- `test_scenario_F_old_snapshot_without_field_returns_none_never_reconstructed`
  — document sans la clé ⇒ `modified_from_planned is None`, jamais recalculé.

`backend/tests/test_pr231_c231_corrections3.py` (niveau endpoint HTTP) :
- `test_today_endpoint_exposes_session_modified_from_planned_true_when_snapshot_differs`
  (snapshot seedé avec `modified_from_planned=True` explicite).
- `test_today_endpoint_session_modified_from_planned_false_when_served_equals_planned`.
- `test_snapshot_C_live_plan_changes_later_does_not_flip_unmodified_to_modified`.
- `test_snapshot_D_live_plan_converges_to_served_does_not_flip_modified_to_unmodified`.
- `test_scenario_F_pre_migration_snapshot_without_field_exposes_none_never_reconstructed`
  (vérifie aussi que `adaptive_session` reste `null`, jamais fabriqué depuis
  `None`).

`frontend/src/__tests__/dashboard-training-v2.test.jsx` :
- `C231-septies: scenario F — no banner when session_modified_from_planned is
  null (pre-migration snapshot)`.

## C231-septies.6 — Validation

```
cd backend && python3 -m pytest \
  tests/test_pr232a_week_execution.py \
  tests/test_pr231_c231_corrections2.py \
  tests/test_pr231_c231_corrections3.py \
  tests/test_pr231_c231_final_corrections.py \
  tests/test_performed_workout_pr230.py \
  tests/test_pr232a_c231_week_endpoint.py \
  tests/test_pr231_served_prescription.py \
  tests/test_pr232a_prescription_snapshot.py \
  tests/test_goal_truth_pr226.py \
  -q
# → 225 passed

cd frontend && npx craco test --watchAll=false --forceExit \
  src/__tests__/dashboard-training-v2.test.jsx \
  src/__tests__/training-v2-page.test.jsx
# → 32 + 24 = 56 passed (was 55; +1 nouveau scénario F)
```

Checklist de non-régression :
- `served_prescription` reste l'autorité Dashboard + TrainingPlanV2 : PASS
  (chaîne de priorité et snapshot get-or-create inchangés, seule la source
  du booléen d'adaptation change)
- historique passé sans snapshot = `prescription_unavailable` : PASS
  (inchangé)
- rest sans snapshot idem : PASS (inchangé)
- `external_id` Garmin réel : PASS (inchangé)
- PR230 enums inchangés : PASS
- no-lookahead : PASS
- multi-user : PASS (isolation par `user_id` inchangée, snapshots toujours
  clés par `(user_id, prescription_id)`)
- None != 0 : PASS (`modified_from_planned=None` n'est jamais traité comme
  `False` par le backend — seul le frontend le traite comme "pas de bandeau"
  au même titre que `False`, ce qui est le comportement demandé, pas une
  confusion `None==0`)
- zéro `/training/feedback` : PASS
- tests backend + frontend ciblés : 0 fail (225 backend, 56 frontend)

Aucune modification du redesign visuel #232B. Aucun merge effectué.
