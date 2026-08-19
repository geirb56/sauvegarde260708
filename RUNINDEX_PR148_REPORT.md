# RUNINDEX PR148 REPORT — test_fallback_still_exists

## 1. HEAD copilot/dev de départ
`e1a222c` — Merge pull request #147

## 2. Confirmation #147 présente
Oui — commit `4a74027` (PR147: replace fragile adjusted_weeks string test with AST-based proof) visible dans copilot/dev.

## 3. Failure reproduite
```
FAILED tests/test_training_engine_pr2.py::TestVMAFallbackConfidence::test_fallback_still_exists
AssertionError: PR2 should preserve the /0.70 fallback (no refactor) — pattern missing.
assert 'avg_speed / 0.70' in '<coach_service source>'
```

## 4. Assertion originale
```python
assert "avg_speed / 0.70" in src
```
Recherche textuelle d'un pattern exact qui n'existe plus sous cette forme.

## 5. Invariant historique recherché
Le test protège le fallback VMA : quand aucun best effort n'est disponible, la VMA est estimée en divisant la vitesse moyenne par 0.70, et cette estimation est marquée `vma_method = "average"` (low confidence).

## 6. Code actuel
```python
# coach_service.py ligne 462
estimated_vma = (60.0 / avg_pace) / 0.70
vma_method = "average"
```
`60.0 / avg_pace` = conversion pace → speed. La sémantique est identique à `avg_speed / 0.70`.

## 7. Classification
**TEST_STATUS = FRAGILE**

## 8. Justification
Le comportement (division par 0.70, méthode "average") est intact. Seule la variable a changé de `avg_speed` à `(60.0 / avg_pace)` — refactor syntaxique, pas sémantique. Le test cherchait un string littéral qui ne correspond plus.

## 9. Stratégie de correction

### V1 (commit initial — insuffisant)
Remplacement de la recherche textuelle par une preuve AST en deux parties indépendantes :
1. Vérifier qu'une division par 0.70 existe *quelque part* dans coach_service
2. Vérifier que l'assignation `vma_method = "average"` existe *quelque part*

**Problème** : ces deux vérifications n'étaient pas liées. Le test resterait vert si le vrai fallback était cassé mais qu'un autre `/0.70` existait ailleurs dans le fichier.

### V2 (commit final — ciblé)
Le test vérifie désormais que dans **le même bloc AST** (siblings) :
- `estimated_vma` reçoit une expression `(X / avg_pace) / 0.70` (division par 0.70 avec `avg_pace` dans le numérateur)
- `vma_method = "average"` est assigné

Le test échouera si :
- le diviseur 0.70 est changé (ex: 0.80)
- `avg_pace` est retiré du calcul
- `estimated_vma` reçoit une constante (ex: 12.0)
- `vma_method = "average"` est déplacé hors de cette branche

Le test reste flexible sur le formatting (accepte 0.7 ou 0.70, 60 ou 60.0).

## 10. Diff
```
backend/tests/test_training_engine_pr2.py  (test_fallback_still_exists rewritten)
RUNINDEX_PR148_REPORT.md                   (ce rapport)
```

## 11. Preuve zéro code métier modifié
Aucun fichier modifié en dehors de `backend/tests/test_training_engine_pr2.py` et ce rapport. Pas de changement à training_engine.py, coach_service.py, llm_coach.py, server.py, training_v2/, config/, frontend.

## 12. Tests
```
test_training_engine_pr2.py:  18 passed, 0 failed
test_plan_duration_decoupled.py: 41 passed, 0 failed
Total regression suite: 59 passed, 0 failed, 0 skipped
```

## 13. Smoke
```python
import training_engine  # OK
import coach_service    # OK
```

## 14. Risque
Minimal. PR test-only, aucune logique métier modifiée. Le nouveau test est strictement plus robuste que l'ancien (résiste aux refactors de variable tout en détectant une vraie suppression du fallback).

## 15. État baseline après #148
0 FAILED sur les tests unitaires exécutables (hors tests nécessitant env vars/DB non disponibles dans ce contexte).

## 16. Recommandation #149
Baseline propre atteinte. #149 devrait reprendre la migration Training Engine V2 (probablement /training/week-plan → WeeklyTarget V2) après audit du HEAD réel.
