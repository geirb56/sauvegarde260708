# CURRENT_WEEKLY_KM PR REPORT

## A. Audit initial

- Anciennes implémentations trouvées :
  - `coach_service.py`: `weekly_km = km_28 / 4 if km_28 > 0 else 20`
  - `server.py` full-cycle: `base_weekly_km = km_28 / 4 if km_28 > 0 else 25`
  - `server.py` week-plan context: `"weekly_km": km_28 / 4 if km_28 > 0 else 20`
  - `llm_coach.py`, `coach_service.py`, `server.py`, `training_engine.py`: `context.get(..., 30)` fallbacks
- Fichiers concernés :
  - `/home/runner/work/sauvegarde260708/sauvegarde260708/backend/training_engine.py`
  - `/home/runner/work/sauvegarde260708/sauvegarde260708/backend/coach_service.py`
  - `/home/runner/work/sauvegarde260708/sauvegarde260708/backend/server.py`
  - `/home/runner/work/sauvegarde260708/sauvegarde260708/backend/llm_coach.py`
  - `/home/runner/work/sauvegarde260708/sauvegarde260708/backend/tests/test_current_weekly_km_unification.py`
- Valeurs par défaut trouvées : 20, 25, 30 (avant modification).
- Appelants trouvés (plan generation) :
  - `coach_service.generate_dynamic_training_plan`
  - `server.get_full_training_cycle`
  - `server.get_week_plan`
  - `llm_coach.generate_cycle_week`
- Variantes de distance trouvées :
  - `distance_km` direct
  - `distance` avec conversion mètres (`>1000`) sur certains chemins
  - mix incohérent selon endpoint
- Activités détectées :
  - Avant: pas de filtre running sur les chemins volume hebdo
  - Running-only présent seulement sur d’autres bouts (ex: VMA), pas pour `current_weekly_km`
- Statut `compute_target_km` :
  - PR2 conservée (progression cap +10% puis multiplicateur de phase)
- Statut `determine_target_km` :
  - Existe toujours dans `training_engine.py`
  - Appelée uniquement par `generate_week_recommendation` (pas par les chemins de génération plan ciblés)

## B. Modifications

- Fonction créée :
  - `compute_current_weekly_km(workouts_28)` dans `training_engine.py`
- Constante créée :
  - `DEFAULT_WEEKLY_KM = 20` (source unique)
- Normalisation distance :
  - `normalized_distance_km(workout)` ajoutée
  - Règle appliquée: `distance_km` prioritaire; sinon `distance` (>1000 => /1000; sinon km)
- Filtre running :
  - `is_running(workout)` ajoutée
  - Types autorisés: `run`, `running`, `trail_running`, `treadmill_running`
- Appelants migrés :
  - `coach_service.generate_dynamic_training_plan` utilise `compute_current_weekly_km(workouts_28)`
  - `server.get_full_training_cycle` utilise `compute_current_weekly_km(workouts_28)`
  - `server.get_week_plan` utilise `compute_current_weekly_km(workouts_28)`
  - Defaults context `weekly_km` alignés sur `DEFAULT_WEEKLY_KM` (coach/llm/server/training_engine)
- `debug_volume` ajouté/adapté :
  - `coach_service.generate_dynamic_training_plan` (retour)
  - `server.get_full_training_cycle` (retour)
  - `server.get_week_plan` (retour)
  - Champs exposés selon chemin: `km_7`, `km_28`, `current_weekly_km`, `target_km`, `phase`

## C. Tests

| Test | Résultat |
|---|---|
| `compute_current_weekly_km` | PASS |
| distance normalization | PASS |
| running filter | PASS |
| fallback | PASS |
| coach_service | PASS |
| server/full-cycle | PASS |
| week-plan | PASS |
| `compute_target_km` | PASS |
| non-régression | PASS |
| frontend build | N/A |

Tests exécutés réellement :
- `python -m pytest tests/test_current_weekly_km_unification.py tests/test_training_engine_pr2.py tests/test_plan_duration_decoupled.py -v`
- Résultat: **72 passed**

## D. Recherche post-modification

- Une seule fonction `compute_current_weekly_km` : **OUI**
- Une seule valeur `DEFAULT_WEEKLY_KM` : **OUI**
- Aucun fallback concurrent 25/30 (chemins ciblés) : **OUI**
- Aucun calcul concurrent de `km_28 / 4` pour `current_weekly_km` : **OUI**  
  (des `km_28/4` restent pour ACWR/CTL, hors source de vérité `current_weekly_km`)
- Running uniquement : **OUI**
- Distance normalisée : **OUI**
- `compute_target_km` PR2 préservé : **OUI**
- `determine_target_km` documentée si encore appelée : **OUI**
- Règle `km_7` non implémentée : **OUI**
- `debug_volume` disponible : **OUI**

## E. Risques résiduels

- `determine_target_km` reste présente (appel interne `generate_week_recommendation`) ; non refactorée volontairement.
- Des calculs `km_28/4` persistent pour métriques charge/fatigue (ACWR/CTL/TSB), hors périmètre de cette PR.
- Le chemin chat/coaching général (`/coach/analyze`) conserve ses propres calculs de distance/contexte ; hors périmètre de cette PR centrée génération de plan.

## F. Verdict obligatoire

READY TO MERGE
