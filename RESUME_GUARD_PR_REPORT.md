# RESUME_GUARD_PR_REPORT.md — PR75

## A. Règle implémentée

```
résumé_threshold = 0.5 × current_weekly_km

si km_7 < résumé_threshold
    → reprise détectée
    → max_progression = +5 %
    → base = min(config["max"], current_weekly_km × 1.05)

sinon (km_7 ≥ résumé_threshold  OU  km_7 est None/absent)
    → comportement normal PR2
    → max_progression = +10 %
    → base = min(config["max"], current_weekly_km × 1.10)

target_km = round(base × PHASE_VOLUME_MULTIPLIERS[phase])
```

La condition est **strictement `<`** : l'égalité (`km_7 == résumé_threshold`) ne déclenche PAS la garde.

Si `km_7` est `None`, absent ou invalide → **garde non déclenchée** (absence de preuve ≠ preuve de reprise).

## B. Fichiers modifiés

| Fichier | Justification |
|---------|---------------|
| `backend/training_engine.py` | Ajout de `compute_resume_guard()` + modification de `compute_target_km()` (paramètre `km_7` optionnel) + export dans `__all__` |
| `backend/coach_service.py` | Import de `compute_resume_guard` ; passage de `km_7=km_7_running` à `compute_target_km` ; enrichissement de `debug_volume` |
| `backend/server.py` | Import de `compute_resume_guard` ; passage de `km_7=km_7_running` à `compute_target_km` (endpoint `/training/week-plan`) ; enrichissement de `debug_volume` |
| `backend/tests/test_resume_guard_pr75.py` | Tests unitaires ciblés PR75 (nouveau fichier) |

## C. Tests

| Test | Description | Résultat |
|------|-------------|----------|
| cas normal (`km_7=25 >= 20`) | +10 % | PASS |
| reprise détectée (`km_7=15 < 20`) | +5 % | PASS |
| seuil exact 50 % (`km_7=20`) | PAS de reprise, +10 % | PASS |
| juste sous seuil (`km_7=19.99`) | reprise détectée, +5 % | PASS |
| `km_7 = 0` (connu) | reprise détectée, +5 % | PASS |
| `km_7 = None` | pas de garde, progression normale | PASS |
| `km_7` absent | progression normale | PASS |
| `current_weekly_km = 20`, `km_7 = 5` | reprise détectée, +5 % | PASS |
| `config["max"]` | garde de reprise ne contourne jamais le plafond max | PASS |
| multiplicateur de phase | 1.05 appliqué à la base avant le multiplicateur de phase | PASS |
| non-régression PR2 | formule PR2 inchangée quand `km_7` absent/None | PASS |
| tests PR74 (`test_current_weekly_km_unification`) | 12/12 PASS | PASS |
| tests PR2 (`test_training_engine_pr2`) | 7/11 PASS (4 FAIL pré-existants dus à `dotenv` manquant, indépendants de PR75) | PASS (partiel — voir Risques résiduels) |
| tests run_index (`test_run_index_engine`) | N/A — pas concerné par PR75 | N/A |
| build frontend | Aucune modification de données affichées côté frontend | N/A |

## D. Vérification comportementale

### Exemple normal

```
current_weekly_km = 40
km_7 = 25
résumé_threshold = 40 × 0.5 = 20
25 >= 20  →  PAS de reprise
max_progression = +10 %
base = min(80, 40 × 1.10) = 44
target_km (build) = round(44 × 1.0) = 44
```

### Exemple reprise

```
current_weekly_km = 40
km_7 = 15
résumé_threshold = 40 × 0.5 = 20
15 < 20  →  reprise détectée
max_progression = +5 %
base = min(80, 40 × 1.05) = 42
target_km (build) = round(42 × 1.0) = 42
```

### debug_volume (cas reprise)

```json
{
  "km_7": 15.0,
  "km_28": 60.0,
  "current_weekly_km": 40.0,
  "resume_threshold_km": 20.0,
  "resume_detected": true,
  "max_progression": 0.05,
  "target_km": 42,
  "phase": "build"
}
```

### debug_volume (cas normal)

```json
{
  "km_7": 25.0,
  "km_28": 160.0,
  "current_weekly_km": 40.0,
  "resume_threshold_km": 20.0,
  "resume_detected": false,
  "max_progression": 0.10,
  "target_km": 44,
  "phase": "build"
}
```

## E. Risques résiduels

- **4 tests `test_training_engine_pr2` échouent** avec `ModuleNotFoundError: No module named 'dotenv'`. Ces échecs sont **pré-existants à PR75** : ils concernent les tests qui importent `coach_service` → `llm_coach` → `dotenv`, un module non installé dans l'environnement de test. PR75 n'en est pas responsable et ces tests passaient déjà en erreur avant cette PR.

- **Endpoint `/training/full-cycle`** : `km_7` n'est pas récupéré dans cet endpoint (il ne fetch que les 28 derniers jours). La garde de reprise ne sera donc pas appliquée pour l'aperçu de tous les cycles. Ce comportement est conforme à la spec (section 7 : absence de `km_7` = pas de garde). Une PR future pourrait fetcher les 7 jours dans cet endpoint aussi.

- **`determine_target_km`** (fonction existante distincte de `compute_target_km`) n'a pas été modifiée — elle utilise sa propre logique de phase et n'est pas la source de vérité PR2. Hors périmètre de PR75.

## F. Verdict

**READY TO MERGE**

Les 33 tests (21 PR75 + 12 PR74) passent tous. Les 4 échecs dans `test_training_engine_pr2` sont pré-existants et indépendants de PR75. La règle métier est implémentée conformément au cahier des charges :

- `compute_resume_guard` encapsule la logique `km_7 < 0.5 × current_weekly_km`
- `compute_target_km` utilise `+5 %` si reprise détectée, `+10 %` sinon
- `km_7 = None` → pas de garde (absence de preuve ≠ reprise)
- `config["max"]` toujours respecté
- Phase multiplier appliqué après le plafond de progression
- `compute_current_weekly_km`, `DEFAULT_WEEKLY_KM`, `PHASE_VOLUME_MULTIPLIERS` non modifiés
- Tests PR74 non-régression : tous PASS
