# RUNINDEX_PR142_REPORT.md
## PR #142 — Migration `/training/metrics` vers Training V2 + Correction frontière Mongo → DomainActivity

---

## 1. HEAD main de départ

```
9d11656 Merge pull request #138 from geirb56/copilot/audit-consumers-legacy
```

## 2. HEAD copilot/dev après réalignement

```
9d11656 Merge pull request #138 from geirb56/copilot/audit-consumers-legacy
```

Réalignement effectué via `git reset --hard refs/remotes/origin/main`.
La branche était 19 commits devant et 6 commits derrière main. Les commits divergents
(audits/validations sans valeur canonique) ont été abandonnés. PR #138 est bien présente.

## 3. Fichiers modifiés

| Fichier | Nature |
|---------|--------|
| `backend/server.py` | Correction endpoint `/training/metrics` |
| `backend/tests/test_training_metrics_pr142.py` | **Nouveau** — tests PR #142 (17 tests) |
| `docs/RUNINDEX_MASTER_ROADMAP_AND_DECISIONS.md` | Section 40 ajoutée |
| `RUNINDEX_PR142_REPORT.md` | **Ce fichier** |

Diffstat `backend/server.py` : 1 file changed, 33 insertions(+), 9 deletions(-)

## 4. Ancien chemin `/training/metrics`

```python
# Ancien code — Mongo docs passés DIRECTEMENT à TrainingLoad V2 (frontière incorrecte)
garmin_activities = await db.garmin_activities.find(...).to_list(200)
load_snapshot = build_training_load(garmin_activities, today_date)  # ← raw Mongo docs

# Détermination acwr_reliable via legacy
reprise_state = classify_training_state(activities_28)              # ← training_engine legacy
acwr_reliable = reprise_state not in ("deep_reprise", "partial_reprise")
```

Problèmes :
- Les documents Mongo bruts contournaient `mongo_garmin_activities_to_domain`.
- `classify_training_state` est une fonction de `training_engine.py` (legacy).
- Incohérence architecturale : une partie du pipeline utilisait V2, une autre le legacy.

## 5. Nouveau chemin

```python
# ── Mongo → DomainActivity boundary (PR142) ──────────────────────────
domain_activities = mongo_garmin_activities_to_domain(garmin_activities)

# ── Training V2 pipeline ──────────────────────────────────────────────
load_snapshot     = build_training_load(domain_activities, today_date)
training_history  = build_training_history(domain_activities, today_date)
runner_profile    = build_runner_profile(
    training_history=training_history,
    training_load=load_snapshot,
    reference_date=today_date,
)
training_state    = build_training_state(
    training_history=training_history,
    training_load=load_snapshot,
    runner_profile=runner_profile,
    reference_date=today_date,
)

# ── acwr_reliable depuis continuity_state (canonique) ─────────────────
acwr_reliable = training_state.continuity_state not in (
    "deep_reprise",
    "partial_reprise",
)
```

## 6. Preuve frontière Mongo → DomainActivity

- `mongo_garmin_activities_to_domain(garmin_activities)` est appelé **avant** toute couche V2.
- C'est le seul point de conversion pour cet endpoint — aucun deuxième adapter créé.
- `build_training_load`, `build_training_history`, `build_runner_profile`,
  `build_training_state` reçoivent tous des `DomainActivity` (ou objets compatibles
  via `_extract_fields` / `to_domain_activity`).
- Test A prouve : `mongo_garmin_activities_to_domain` retourne bien 28 `DomainActivity`
  avec `activity_type="running"` et `duration_s=1800.0` depuis des docs Mongo bruts.
- Test B prouve : `build_training_load` sur `domain_activities` donne le même ACWR
  qu'un appel direct.

## 7. Preuve disparition de `classify_training_state` legacy

- `classify_training_state` n'apparaît **plus** dans `server.py` (vérification AST : 0 usage).
- Import retiré de la liste `from training_engine import (...)`.
- Test C confirme : le patch de `training_engine.classify_training_state` pour
  lever une `AssertionError` ne bloque pas l'endpoint → la fonction n'est plus appelée.

**Audit imports `training_engine` restants dans `server.py` après PR #142 :**

```python
from training_engine import (
    DEFAULT_WEEKLY_KM,
    GOAL_CONFIG,
    compute_current_weekly_km,
    compute_cycle_dates,
    compute_target_km,
    apply_resume_guard,
    resolve_chronic_base,
    resolve_reprise_plan,
    REPRISE_STABLE_WEEKS,
    compute_week_number,
    determine_phase,
    get_phase_description,
    is_running,
    normalized_distance_km,
)
```

Ces imports alimentent encore d'autres endpoints (`/training/full-cycle`,
`/training/week-plan`, `/training/plan`, `/training/refresh`).

## 8. Comportement par `continuity_state`

| `continuity_state`  | `acwr_reliable` | Note |
|---------------------|-----------------|------|
| `deep_reprise`      | `False`         | Pas de run depuis ≥ 28j |
| `partial_reprise`   | `False`         | Volume récent < 50% baseline |
| `reprise_exit`      | `True`          | Comeback en cours, mais non deep/partial |
| `normal`            | `True`          | Continuité stable |
| `no_history`        | `True`          | Pas de reprise → pas d'inhibition ACWR |

`reason_codes` = diagnostic uniquement. Le routing passe par `continuity_state`.

## 9. Tests exécutés

### PR #142 — nouveaux tests

| Fichier | Tests |
|---------|-------|
| `test_training_metrics_pr142.py` | 17 tests |

### Régression

| Suite | Résultat |
|-------|----------|
| `test_training_history_pr05.py` | ✅ Pass |
| `test_training_v2_training_load.py` | ✅ Pass |
| `test_training_state_pr04.py` | ⚠️ voir §10 |
| `test_training_v2_domain_activity.py` | ✅ Pass |
| `test_daily_runtime_pr137.py` | ✅ Pass |
| `test_training_metrics_pr127.py` | ✅ Pass |
| `test_training_metrics_v2_alignment.py` | ✅ Pass |
| `test_training_metrics_endpoint.py` | ⚠️ `fastapi` absent (env) |

## 10. Résultats

**PR #142 tests : 17/17 PASS.**

**Régression globale : 279 passed, 3 failed (pre-existing), 1 error (env).**

Les 3 échecs dans `test_training_state_pr04.py` :
- `test_continuity_confidence_29_days` — attend `low`, obtient `medium`
- `test_continuity_confidence_89_days` — attend `medium`, obtient `high`
- `test_pr94_cas2_history_27d_last_run_27d` — attend `reprise_exit`, obtient `normal`

**Ces 3 échecs sont pré-existants sur `main` avant toute modification PR #142**
(confirmé par `git stash` + exécution sur main pur → mêmes 3 échecs).
Il s'agit d'une dette de calibration `training_state.py` hors scope de cette PR.

L'erreur `test_training_metrics_endpoint.py` est due à l'absence du module `fastapi`
dans l'environnement de test local. Hors scope.

## 11. Consumers `training_engine.py` runtime encore présents

Après PR #142, les consumers runtime directs restants de `training_engine.py` sont :

1. **`backend/server.py`** — endpoints :
   - `/training/full-cycle`
   - `/training/week-plan`
   - `/training/plan`
   - `/training/refresh`
   - (et autres callers des fonctions importées listées en §7)

2. **`backend/llm_coach.py`** — `generate_cycle_week()`

`/training/metrics` et `/training/today` ne consomment **plus** `training_engine.py`
en chemin runtime.

## 12. Éléments laissés à #143

- Migration `/training/full-cycle` vers Training V2
- Migration `/training/week-plan` vers Training V2
- Migration `llm_coach.generate_cycle_week()` vers Training V2
- Migration des autres callers `training_engine.py` confirmés dans `server.py`

Kill de `training_engine.py` réservé à **#144**, uniquement après preuve exhaustive
zéro consumer runtime.

## 13. Confirmations

| Item | Statut |
|------|--------|
| Aucun changement #141 repris | ✅ Confirmé |
| Aucun changement long-run | ✅ Confirmé |
| Aucun changement WeeklyTarget | ✅ Confirmé |
| Aucun changement Readiness | ✅ Confirmé |
| Aucun changement performance.py | ✅ Confirmé |
| `training_engine.py` conservé | ✅ Confirmé |
| Contrat HTTP `/training/metrics` inchangé | ✅ Confirmé (mêmes champs) |
| `/training/today` non modifié | ✅ Confirmé |
| Aucun import `performance.py` dans couches décisionnelles | ✅ Confirmé (tests L) |
