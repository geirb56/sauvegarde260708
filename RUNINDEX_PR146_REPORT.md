# RUNINDEX PR146 — Suppression de la copie orpheline GOAL_CONFIG

## 1. HEAD copilot/dev de départ

```
5c22ac4 Merge pull request #145
```

PR #145 merge confirmé dans HEAD.

## 2. Audit GOAL_CONFIG avant modification

| Fichier | Type | Détail |
|---------|------|--------|
| `backend/config/training_goals.py:7` | **Source canonique** | Définition unique post-PR145 |
| `backend/server.py:102` | Import runtime | `from config.training_goals import GOAL_CONFIG` |
| `backend/server.py:3486,3527,4411` | Usage runtime | Utilisation de GOAL_CONFIG importé |
| `backend/training_engine.py:22` | **COPIE LEGACY** | Définition orpheline — aucun consumer runtime |
| `backend/training_engine.py:928` | Export legacy | Dans `__all__` |
| `backend/tests/test_goal_config_pr145.py:14` | Test | Import parity test |
| `backend/tests/test_plan_duration_decoupled.py:29` | Test | Import pour cycle_weeks |

## 3. Preuve absence consumer runtime legacy

Aucun fichier runtime (server.py, llm_coach.py, coach_service.py) n'importe `GOAL_CONFIG` depuis `training_engine`. Seuls des tests y accédaient.

- `server.py` → importe depuis `config.training_goals` (PR145)
- `llm_coach.py` → importe uniquement `VOLUME_GOAL_CONFIG` depuis `training_engine`
- `coach_service.py` → n'importe pas `GOAL_CONFIG`

## 4. Modifications effectuées

### `backend/training_engine.py`
- Suppression de la définition `GOAL_CONFIG = { ... }` (lignes 22-53)
- Suppression de `"GOAL_CONFIG"` dans `__all__`

### `backend/tests/test_goal_config_pr145.py`
Réécriture complète pour PR146. Vérifie désormais :
1. `GOAL_CONFIG` existe dans `config.training_goals`
2. Les 5 goals attendus sont présents
3. Les champs contractuels sont présents
4. `server.py` importe depuis `config.training_goals`
5. `server.py` ne définit pas `GOAL_CONFIG` localement
6. `server.py` ne l'importe pas depuis `training_engine`
7. `training_engine.py` ne définit plus `GOAL_CONFIG` (vérification AST)

### `backend/tests/test_plan_duration_decoupled.py`
- Import mis à jour : `from config.training_goals import GOAL_CONFIG`

## 5. Fichiers modifiés

```
backend/training_engine.py
backend/tests/test_goal_config_pr145.py
backend/tests/test_plan_duration_decoupled.py
RUNINDEX_PR146_REPORT.md
```

## 6. Audit GOAL_CONFIG après modification

| Fichier | Type |
|---------|------|
| `backend/config/training_goals.py:7` | **UNIQUE définition** |
| `backend/server.py:102` | Import runtime |
| `backend/server.py:3486,3527,4411` | Usage runtime |
| `backend/tests/test_goal_config_pr145.py` | Tests (assertions, pas de définition) |
| `backend/tests/test_plan_duration_decoupled.py:29` | Test import depuis `config.training_goals` |

**Aucune autre définition de GOAL_CONFIG dans le repository.**

Note : `VOLUME_GOAL_CONFIG` reste dans `training_engine.py` — c'est une constante différente (volume bounds), hors scope PR146.

## 7. Preuve Single Source of Truth

`GOAL_CONFIG` est défini uniquement dans `backend/config/training_goals.py`. Toutes les autres occurrences sont des imports, usages ou assertions de test. Vérifié par grep exhaustif post-modification.

## 8. Tests

```
PR145 test suite:        8 passed, 0 failed
PR2 + decoupled suite: 65 passed, 2 failed (pre-existing)
```

Échecs pré-existants non liés à PR146 :
- `test_adjusted_weeks_is_base_weeks` — pattern source check obsolète
- `test_fallback_still_exists` — pattern `avg_speed / 0.70` absent (refactorisé dans PR antérieur)

`training_engine` reste importable après suppression.

## 9. Risques

**Risque : FAIBLE**

- La constante supprimée n'avait aucun consumer runtime
- `training_engine` reste importable
- Aucune logique métier modifiée

## 10. Consumers training_engine restants après PR146

### Runtime
| Fichier | Imports |
|---------|---------|
| `server.py` | `compute_current_weekly_km`, `determine_target_load`, `compute_target_km`, `compute_cycle_dates`, `determine_phase`, `resolve_chronic_base`, `resolve_reprise_plan`, `apply_resume_guard`, `build_reprise_week_structure`, etc. |
| `llm_coach.py` | `VOLUME_GOAL_CONFIG`, `compute_target_km`, `PHASE_VOLUME_MULTIPLIERS`, etc. |

### Tests
| Fichier | Usage |
|---------|-------|
| `test_training_engine_pr2.py` | `VOLUME_GOAL_CONFIG`, `PHASE_VOLUME_MULTIPLIERS`, etc. |
| `test_plan_duration_decoupled.py` | `GOAL_CONFIG` (via `config.training_goals`) |
| `test_current_weekly_km_unification.py` | `compute_current_weekly_km`, etc. |
| `test_resume_guard_pr76.py` | `apply_resume_guard`, `compute_target_km` |
| `test_cycle_dates.py` | `compute_cycle_dates` |
| `test_coach_load_context_pr128.py` | `build_training_context` |
| `test_training_metrics_pr127.py` | `determine_target_load` |

## 11. Recommandation #147

Prochaine migration candidate : `VOLUME_GOAL_CONFIG` vers `backend/config/`.
Les consumers runtime sont `training_engine.py` (interne) et `llm_coach.py`.
Risque moyen — nécessite vérification que les tests PR2 passent avec l'import redirigé.

Autre dette identifiée : `compute_current_weekly_km` a encore 2 consumers legacy (migration future vers `TrainingHistory V2`).

## Verdict

**READY FOR MERGE INTO copilot/dev**

- Aucun consumer runtime de `training_engine.GOAL_CONFIG` avant suppression ✓
- Copie legacy supprimée ✓
- `config.training_goals.GOAL_CONFIG` intacte ✓
- `server.py` continue d'utiliser `config.training_goals` ✓
- Aucune autre définition `GOAL_CONFIG` ✓
- `training_engine` reste importable ✓
- Tests verts (échecs pré-existants uniquement) ✓
- Aucun changement métier parasite ✓
- Diff minimal (3 fichiers + rapport) ✓
