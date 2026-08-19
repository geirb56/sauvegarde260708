# RUNINDEX PR #154 — Report

## HEAD départ

`041de63` (Merge PR #153)

## Occurrences `db.training_goals` — AVANT

| File | Line | Type |
|------|------|------|
| backend/server.py | ~3458 | RUNTIME_WRITE (`delete_one`) — DELETE /training/goal |
| backend/server.py | 4576 | RUNTIME_READ (`find_one`) — GET /training/week-plan |

## Classification

- `backend/config/training_goals.py` — CONFIG_MODULE (GOAL_CONFIG source, untouched)
- `db.training_goals.delete_one` in DELETE /training/goal — RUNTIME_WRITE → **removed in #154**
- `db.training_goals.find_one` in GET /training/week-plan — RUNTIME_READ → **kept intentionally, to be addressed in #155**

## Audit: collection legacy confirmée morte (no writer)

- **Writer runtime vers db.training_goals ?** — NON. `set_training_goal` writes to `db.training_cycles`.
- **Reader runtime ?** — `/training/week-plan` lit encore `db.training_goals` (volontairement conservé, scope #155).
- **Delete legacy ?** — `DELETE /training/goal` avait un `db.training_goals.delete_one` → **supprimé**.
- **Collections actives pour le goal utilisateur :** `db.training_cycles`, `db.training_context`.

## Modification effectuée

### backend/server.py

1. **DELETE /training/goal** — Removed `db.training_goals.delete_one(...)`. Now only deletes from `db.training_context` and `db.training_cycles` (the active collections).

## Occurrences `db.training_goals` runtime — APRÈS

| Type | Count | Detail |
|------|-------|--------|
| RUNTIME_WRITE | 0 | — |
| RUNTIME_READ | 1 | GET /training/week-plan (intentionally kept, #155) |

## Collections supprimées par DELETE /training/goal (final)

- `db.training_context` — delete_one
- `db.training_cycles` — delete_one

## Fichiers modifiés

- `backend/server.py` — removed `db.training_goals.delete_one` from DELETE route
- `backend/tests/test_pr154_delete_training_goal.py` (new)
- `RUNINDEX_PR154_REPORT.md` (new)

## Tests

```
tests/test_pr154_delete_training_goal.py — 4 passed, 0 failed, 0 skipped
```

Tests vérifient :
1. DELETE fonctionne (200 + success=true)
2. Collections actives nettoyées (training_context, training_cycles)
3. Aucun accès à db.training_goals lors du DELETE
4. Cas "no data" retourne success=false

## Mergeability

Compatible — changement minimal, pas de conflit attendu.

## Dettes hors scope découvertes

- **#155** : `/training/week-plan` conserve un reader `db.training_goals.find_one(...)`. À migrer vers `db.training_cycles` dans une PR dédiée.

## Verdict

**READY FOR MERGE INTO copilot/dev**
