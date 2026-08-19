# RUNINDEX PR #154 — Report

## HEAD départ

`041de63` (Merge PR #153)

## Occurrences `db.training_goals` — AVANT

| File | Line | Type |
|------|------|------|
| backend/server.py | 3458 | RUNTIME_WRITE (`delete_one`) — DELETE /training/goal |
| backend/server.py | 4576 | RUNTIME_READ (`find_one`) — GET /training/week-plan |

## Classification

- `backend/config/training_goals.py` — CONFIG_MODULE (GOAL_CONFIG source, untouched)
- `db.training_goals.delete_one` in DELETE /training/goal — RUNTIME_WRITE → **removed**
- `db.training_goals.find_one` in GET /training/week-plan — RUNTIME_READ → **replaced with `db.training_cycles`**

## Audit: collection legacy confirmée morte

- **Writer runtime vers db.training_goals ?** — NON. `set_training_goal` writes to `db.training_cycles`.
- **Reader runtime ?** — Seul `/training/week-plan` lisait `db.training_goals` (now fixed).
- **Delete legacy ?** — `DELETE /training/goal` avait un `db.training_goals.delete_one` (now removed).
- **Collections actives pour le goal utilisateur :** `db.training_cycles`, `db.training_context`.

## Modification effectuée

### backend/server.py

1. **DELETE /training/goal** — Removed `db.training_goals.delete_one(...)`. Now only deletes from `db.training_context` and `db.training_cycles` (the active collections).
2. **GET /training/week-plan** — Replaced `db.training_goals.find_one(...)` with `db.training_cycles.find_one(...)`.

## Occurrences `db.training_goals` runtime — APRÈS

**ZERO**

## Collections supprimées par DELETE /training/goal (final)

- `db.training_context` — delete_one
- `db.training_cycles` — delete_one

## Fichiers modifiés

- `backend/server.py`
- `backend/tests/test_pr154_delete_training_goal.py` (new)
- `RUNINDEX_PR154_REPORT.md` (new)

## Tests

```
tests/test_pr154_delete_training_goal.py — 4 passed, 0 failed, 0 skipped
```

Tests vérifient :
1. DELETE fonctionne (200 + success=true)
2. Collections actives nettoyées (training_context, training_cycles)
3. Aucun accès à db.training_goals
4. Cas "no data" retourne success=false

## Mergeability

Compatible — changement minimal, pas de conflit attendu.

## Dettes hors scope découvertes

- `/training/week-plan` utilise le document `training_cycles` mais attend un champ `goal` — le schéma est compatible (set-goal écrit `goal` dans `training_cycles`). Pas d'action requise.

## Verdict

**READY FOR MERGE INTO copilot/dev**
