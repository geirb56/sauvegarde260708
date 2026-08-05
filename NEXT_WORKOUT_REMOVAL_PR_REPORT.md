# NEXT_WORKOUT removal PR report

## A. Audit avant (producteurs / consommateurs)

- Producteurs backend identifiés :
  - `backend/garmin/insights.py`
  - `backend/server.py`
- Consommateurs frontend réels :
  - aucun consommateur `next_workout` / `nextWorkout` trouvé
- Tests qui imposaient encore `next_workout` :
  - `backend/tests/test_run_index_screen.py`
  - `backend/tests/test_cardio_coach_screen.py`

## B. Choix A ou B (suppression clé vs null) + justification

- Choix retenu : **A — suppression de la clé `next_workout`**
- Justification :
  - aucun consommateur frontend réel détecté
  - aligne le contrat avec le comportement produit réel
  - évite de continuer à exposer un champ mort ou ambigu

## C. Fichiers modifiés

- `backend/garmin/insights.py`
- `backend/server.py`
- `backend/tests/test_run_index_screen.py`
- `backend/tests/test_cardio_coach_screen.py`
- `NEXT_WORKOUT_REMOVAL_PR_REPORT.md`

## D. Tableau tests

| Vérif | Résultat |
|-------|----------|
| plus de template 6x800 / Easy Run / Rest Day dans next_workout | PASS |
| insights.py aligné | PASS |
| server.py fallback + no_data alignés | PASS |
| test_run_index_screen aligné | PASS |
| test_cardio_coach_screen aligné ou N/A | PASS |
| grep frontend sans next_workout | PASS |
| recommendation toujours présent | PASS |
| readiness / training/today / ReadinessChart non régressés | PASS |

## E. Grep post-modif

- `next_workout` : plus d'exigence de label non vide dans les tests ciblés
- `nextWorkout` : aucun consommateur frontend trouvé

## F. Risques résiduels

- Un consommateur externe hors repo pourrait dépendre historiquement de `next_workout`
- Les tests d'intégration HTTP dépendent toujours d'un backend lancé localement

## G. Verdict

**READY TO MERGE**
