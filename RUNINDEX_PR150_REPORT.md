# RUNINDEX PR150 REPORT — Nettoyage complet post-#149

## 1. HEAD copilot/dev départ
```
43ee9ec Merge pull request #149
```

## 2. Confirmation #148/#149
Both PRs merged and present in history.

## 3. Test portability avant/après

**Avant:** `test_fallback_code_path_exists_in_server` used hardcoded `/home/runner/work/sauvegarde260708/sauvegarde260708/backend/server.py`.

**Après:** `pathlib.Path(__file__).resolve().parents[1] / "server.py"` — portable across CI, Emergent, local.

## 4. Audit training_goals

| Endpoint/location | Operation | Purpose |
|---|---|---|
| `/training/week-plan` (was) | READ | Get goal for week-plan — **BUG: no writer exists** |
| `/training/goal` DELETE | DELETE | Cleanup |
| `config.training_goals` | IMPORT | GOAL_CONFIG dict (unrelated — config file, not Mongo) |

**Conclusion:** `db.training_goals` is a **dead/legacy** collection. No endpoint in current code writes to it.

## 5. Audit training_cycles

| Endpoint | Operation | Shape |
|---|---|---|
| `/training/set-goal` POST | UPSERT | `{user_id, goal, start_date, updated_at}` |
| `/training-plan/set-goal` POST | UPSERT | `{user_id, goal, updated_at}` |
| `/training/full-cycle` GET | READ | `{goal, start_date, adjusted_weeks, ...}` |
| `/training/goal` DELETE | DELETE | cleanup |

## 6. Writers/Readers

### training_cycles (CANONICAL)
- **Writers:** `/training/set-goal`, `/training-plan/set-goal`, `/training/full-cycle` (auto-create default)
- **Readers:** `/training/full-cycle`, `/training/week-plan` (after PR150)

### training_goals (DEAD)
- **Writers:** NONE
- **Readers:** was `/training/week-plan` (fixed in PR150), `/training/goal` DELETE

### user_goals
- **Writers:** `/user/goal` POST
- **Readers:** `/training/full-cycle` (event_date), `/training/week-plan` (event_date after PR150), dashboard, coach_service

## 7. Source canonique décidée + preuve

**`training_cycles`** is the canonical source for:
- `goal` (goal_type: 5K/10K/SEMI/MARATHON/ULTRA)
- `start_date` (cycle start)

**`user_goals`** is the canonical source for:
- `event_date` (race date)

**Proof:** `/training/set-goal` writes to `training_cycles`. No code path writes to `training_goals`.

## 8. Correction /training/week-plan

Changed from:
```python
goal = await db.training_goals.find_one({"user_id": user_id}, {"_id": 0})
```
To:
```python
cycle = await db.training_cycles.find_one({"user_id": user_id}, {"_id": 0})
user_goal = await db.user_goals.find_one({"user_id": user_id}, {"_id": 0})
goal = {"goal_type": cycle["goal"], "start_date": ..., "event_date": ...}
```

## 9. Audit TSS fallback complet

`_generate_fallback_week_plan` has two branches:
1. **Duration-based** (target_km_protected is None): Already fixed in PR149 — all `estimated_tss: None`, `total_tss: None`.
2. **Distance-based** (legacy templates): Had hardcoded values (0, 25, 30, 35, 45, 50, 55, 60).

## 10. TSS supprimés/remplacés par None

All 21 `estimated_tss` values in distance-based templates → `None`.
`total_tss = sum(...)` → `total_tss = None`.

## 11. Frontend null handling

Fixed 3 occurrences in:
- `Dashboard.jsx:180`
- `TrainingPlan.jsx:165`
- `TrainingPlan.jsx:763`

Before: `{session.estimated_tss || 0} TSS` (shows "0 TSS" when null)
After: `{session.estimated_tss != null ? \`${session.estimated_tss} TSS\` : '—'}`

## 12. Tests

| Test file | Tests | Status |
|---|---|---|
| `test_pr150_nettoyage.py` | 10 | PASS |
| `test_pr149_week_plan_v2.py` | 18 | PASS |

## 13. Diff

Files modified:
- `backend/server.py` — goal source fix + TSS None
- `backend/tests/test_pr149_week_plan_v2.py` — portable path
- `backend/tests/test_pr150_nettoyage.py` — NEW (10 tests)
- `frontend/src/pages/Dashboard.jsx` — null TSS display
- `frontend/src/pages/TrainingPlan.jsx` — null TSS display

## 14. Legacy restant

| Occurrence | Classification |
|---|---|
| `db.training_goals.delete_one` in `/training/goal` DELETE | LEGACY_KNOWN — safe cleanup op |
| `config.training_goals` import | VALID — this is GOAL_CONFIG, not Mongo |
| `db.training_cycles` default creation in full-cycle | VALID |

## 15. Audit zéro dette post-#150

- Hardcoded CI paths: **NONE** remaining
- `estimated_tss: 0` in server.py: **NONE** remaining
- `total_tss: 0` in server.py: **NONE** remaining
- `db.training_goals` reader in week-plan: **REMOVED**
- `db.training_goals` delete in `/training/goal`: LEGACY_KNOWN (cleanup is safe)

## 16. Runtime requis post-merge

Smoke endpoints:
- `/training/week-plan` — must return 200 if training_cycles has goal
- `/training/today`, `/training/plan`, `/training/full-cycle`, `/training/metrics`
- `/run-index`, `/dashboard`

## 17. Risque

- LOW: `training_cycles` might not have `start_date` for very old accounts (defaults to now)
- LOW: `user_goals` might not exist (race_date=None, acceptable for MAINTENANCE)

## 18. Recommandation #151

- Remove dead `db.training_goals` collection references entirely
- Add MAINTENANCE goal_type to `/training/set-goal` validation
- Consider unifying `user_goals.event_date` into `training_cycles`

---

## VERDICT

**READY FOR MERGE INTO copilot/dev**

- Test portable: YES
- Baseline: 0 failed (28/28 pass)
- Source goal: training_cycles (canonical, proven)
- /training/week-plan: reads training_cycles
- No destructive Mongo writes
- No fictitious TSS in fallbacks
- Frontend accepts None
- WeeklyTarget V2 remains prescriptive authority
- No invented physiological formulas
- Diff controlled (5 files)
- Mergeable
