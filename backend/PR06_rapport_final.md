# PR06 — Rapport final : Charge d'entraînement déterministe (Training Load V2)

> **Correctifs PR90** — convention inclusive, tests ACWR exacts, suppression du fallback distance, documentation de la séparation TrainingHistory / TrainingLoadSnapshot.

## 1. SHA de départ

```
87d2aee feat(PR06): add training load V2 deterministic engine + 48 tests + report
```

## 2. Branche utilisée

Branche de travail courante (preview) issue de la fusion PR01→PR05.

## 3. Fichiers créés

| Fichier | Rôle |
|---|---|
| `backend/training_v2/training_load.py` | Module métier principal — calcul déterministe de la charge V2 |
| `backend/tests/test_training_v2_training_load.py` | Suite de tests PR06 (50 tests) |
| `backend/PR06_rapport_final.md` | Ce rapport |

## 4. Fichiers modifiés

| Fichier | Modification |
|---|---|
| `backend/training_v2/__init__.py` | Export de `TrainingLoadSnapshot` et `build_training_load` |

Aucun autre fichier modifié. Aucune route, recommandation, plan, frontend, `.env` ou fichier protégé touché.

## 5. Séparation explicite des deux modules

Deux modules coexistent dans `training_v2/` avec des objectifs distincts :

| Module | Fenêtres | Objectif |
|---|---|---|
| `TrainingHistory` (PR05) | 7 jours, **30 jours**, 90 jours | Vision métier / historique : agrégation de volume (distance, durée) pour l'affichage et les tendances |
| `TrainingLoadSnapshot` (PR06) | aiguë = 7 jours, chronique = **28 jours** (= 4 semaines exactes) | Vision technique ACWR : ratio Acute:Chronic Workload Ratio basé sur la durée |

La différence entre 30 jours (TrainingHistory) et 28 jours (TrainingLoadSnapshot) est **intentionnelle** : 28 jours représente exactement 4 semaines calendaires, ce qui est la définition standard de la charge chronique pour l'ACWR.

## 6. Définition de la charge (durée uniquement)

La charge d'une activité est un **proxy de volume basé uniquement sur la durée** :

```
charge (min) = durée valide (secondes) / 60
```

**Comportement strict :**

| Cas | Résultat |
|---|---|
| Durée valide (> 0) | charge = durée / 60 min |
| Durée absente / nulle / négative | aucune charge (0) |
| Distance seule, sans durée | **aucune charge** — pas de fallback artificiel |

La distance peut être utilisée par `TrainingHistory` pour les métriques de volume, mais **ne génère pas de durée synthétique** dans ce module.

**Explicitement exclu du calcul de charge :**

- TRIMP (Training Impulse)
- TSS (Training Stress Score)
- Garmin Training Load
- Fréquence cardiaque / zones FC
- Facteur d'intensité
- Dénivelé / gradient
- RPE (Rate of Perceived Exertion)
- Estimation distance × allure (`ESTIMATED_MINUTES_PER_KM` supprimée)

Types de course acceptés : `running`, `trail_running`, `treadmill_running`.

## 7. Conventions des fenêtres temporelles

Pour une `reference_date` donnée (fenêtres inclusives) :

| Fenêtre | Borne gauche | Borne droite |
|---|---|---|
| Aiguë 7 jours | `reference_date - 6 jours` (J-6) | `reference_date` |
| Chronique 28 jours | `reference_date - 27 jours` (J-27) | `reference_date` |
| Précédente 7 jours | `reference_date - 13 jours` (J-13) | `reference_date - 7 jours` (J-7) |

La fenêtre chronique est **28 jours** (non 30 jours). Un test de cohérence explicite le vérifie.

## 7. Formule ACWR

```
chronic_weekly_load = load_28d / 4
acwr = acute_load_7d / chronic_weekly_load
     = 4 × acute_load_7d / load_28d
```

La charge aiguë (J-6 à J) est incluse dans `load_28d`. Ainsi :

```
Soit B = charge des jours J-27 à J-7 (hors fenêtre aiguë)
Soit A = charge aiguë J-6 à J
load_28d = B + A
chronic_weekly_load = (B + A) / 4
acwr = A / ((B + A) / 4) = 4A / (B + A)
```

Si `chronic_weekly_load == 0` → `acwr = None`.  
Le calcul utilise la précision flottante complète ; l'arrondi (3 décimales) s'applique uniquement au champ final.

## 8. Convention inclusive de profondeur d'historique (correctif PR90)

**Formule corrigée :**

```python
available_history_days = (reference_date - first_date).days + 1
```

Le `+ 1` applique la convention inclusive : J-27 à J = 28 jours calendaires (les deux bornes comptées).

**Résultats attendus et vérifiés :**

| Première activité | available_history_days | has_sufficient_history | confidence |
|---|---|---|---|
| J (days_ago=0) | 1 | False | low |
| J-6 (days_ago=6) | 7 | False | low |
| J-12 (days_ago=12) | 13 | False | **low** |
| J-13 (days_ago=13) | 14 | False | **medium** |
| J-26 (days_ago=26) | 27 | False | **medium** |
| J-27 (days_ago=27) | **28** | **True** | **high** |
| J-28 (days_ago=28) | 29 | True | high |

`has_sufficient_history = available_history_days >= 28`

## 9. Gestion du cas sans historique

Aucun `acwr = 1.0` artificiel en l'absence d'historique.

```
si load_28d == 0 :
    chronic_weekly_load = 0.0
    acwr = None
    status = "unavailable"
    is_available = False
```

## 10. Statuts et seuils ACWR

Les seuils sont centralisés comme constantes dans le module :

| Statut | Condition |
|---|---|
| `"unavailable"` | `acwr is None` |
| `"very_low"` | `acwr < 0.50` |
| `"low"` | `0.50 ≤ acwr < 0.80` |
| `"balanced"` | `0.80 ≤ acwr ≤ 1.30` |
| `"elevated"` | `1.30 < acwr ≤ 1.50` |
| `"high"` | `acwr > 1.50` |

Le terme `"overtraining_risk"` n'est pas utilisé — l'ACWR seul ne permet pas d'établir un diagnostic de surentraînement.

## 11. Tests des seuils ACWR (correctif PR90)

### Helper de test

```python
def _acwr_acute_minutes(target_acwr: float, B_min: float = 60.0) -> float:
    """A = target_acwr × B / (4 - target_acwr)"""
    return target_acwr * B_min / (4.0 - target_acwr)
```

Ce helper inverse la formule `ACWR = 4A/(B+A)` pour calculer la charge aiguë exacte correspondant à un ACWR cible.

### Seuils testés (B = 60 min, 4 × 900 s dans jours 8-11)

| ACWR cible | A (min) | ACWR calculé | Statut attendu |
|---|---|---|---|
| 0.30 (< 0.50) | 18/3.7 ≈ 4.865 | 0.30 | `very_low` |
| **0.50** (borne low) | 60/7 ≈ 8.571 | **0.50** | `low` |
| 0.60 (< 0.80) | 180/17 ≈ 10.588 | 0.60 | `low` |
| **0.80** (borne balanced) | 15.0 | **0.80** | `balanced` |
| 1.00 (intérieur balanced) | 20.0 | 1.00 | `balanced` |
| **1.30** (borne haute balanced) | 260/9 ≈ 28.889 | **1.30** | `balanced` |
| 1.40 (intérieur elevated) | 420/13 ≈ 32.308 | 1.40 | `elevated` |
| **1.50** (borne elevated) | 36.0 | **1.50** | `elevated` |
| 1.60 (> 1.50) | 40.0 | 1.60 | `high` |

Chaque test vérifie `s.acwr ≈ target (abs=0.001)` avant de vérifier `s.status`.

## 12. Confiance et disponibilité

### Disponibilité

`is_available = True` ssi `acwr is not None` (i.e. `chronic_weekly_load > 0`).

`has_sufficient_history = available_history_days >= 28`

`available_history_days` est calculé à partir des dates réelles de toutes les activités de course valides ≤ `reference_date`, avec convention inclusive (`+1`).

### Niveaux de confiance

| Niveau | Condition |
|---|---|
| `"none"` | Aucune charge exploitable (total_any_load == 0) |
| `"low"` | Charge présente, `available_history_days < 14` |
| `"medium"` | `14 ≤ available_history_days < 28` |
| `"high"` | `available_history_days ≥ 28` |

La confiance est basée sur l'ensemble de l'historique disponible, pas uniquement sur la fenêtre 28j.

## 13. Tests ajoutés

50 tests déterministes couvrant :

| # | Cas de test |
|---|---|
| 1 | Aucune activité |
| 2 | Uniquement des activités non-running |
| 3 | Une activité valide dans les 7 derniers jours |
| 4 | Calcul exact depuis la durée |
| 5 | Distance seule sans durée → **aucune charge** (pas de fallback) |
| 6 | Durée seule source de charge (distance ignorée) |
| 7 | Durée nulle → aucune charge (pas de fallback distance) |
| 8 | Durée négative → aucune charge (pas de fallback distance) |
| 9 | Ni durée ni distance → exclu |
| 10 | Activité future exclue |
| 11 | J-6 inclus dans la fenêtre aiguë |
| 12 | J-7 exclu de la fenêtre aiguë |
| 13 | J-27 inclus dans la fenêtre 28j |
| 14 | `chronic_weekly_load = load_28d / 4` |
| 15 | Calcul exact ACWR |
| 16 | `acwr=None` si charge 28j nulle |
| 17 | Statut `"unavailable"` sans dénominateur |
| 18 | ACWR = 0.30 → `very_low` (+ assertion s.acwr) |
| 19 | ACWR = 0.50 → `low` (borne exacte + assertion s.acwr) |
| 20 | ACWR = 0.60 → `low` (intérieur + assertion s.acwr) |
| 21 | ACWR = 0.80 → `balanced` (borne exacte + assertion s.acwr) |
| 22 | ACWR = 1.00 → `balanced` (intérieur + assertion s.acwr) |
| 23 | ACWR = 1.30 → `balanced` (borne haute exacte + assertion s.acwr) |
| 24 | ACWR = 1.40 → `elevated` (intérieur + assertion s.acwr) |
| 25 | ACWR = 1.50 → `elevated` (borne exacte + assertion s.acwr) |
| 26 | ACWR = 1.60 → `high` (+ assertion s.acwr) |
| 27 | Fenêtre précédente J-13 à J-7 |
| 28 | Calcul `load_change_percent` |
| 29 | Variation `None` si charge précédente = 0 |
| 30 | Historique insuffisant |
| 31 | Historique exactement suffisant — J-27 → True (convention inclusive) |
| 32 | confidence `"none"` |
| 33 | confidence `"low"` (intérieur) |
| 34 | confidence `"medium"` (intérieur) |
| 35 | confidence `"high"` (intérieur) |
| 36 | confidence `"low"` à la borne haute (13 jours) |
| 37 | confidence `"medium"` à la borne basse (14 jours) |
| 38 | confidence `"medium"` à la borne haute (27 jours) |
| 39 | confidence `"high"` à la borne basse (28 jours = J-27) |
| 40 | Sub-document `garmin_activity` (PR02) |
| 41 | Objets Pydantic |
| 42 | Immutabilité du modèle |
| 43 | Déterminisme |
| 44 | Indépendance au temps système |
| 45 | Activité avec seulement durée valide |
| 46-47 | Cohérence 28j ≠ 30j (fenêtre [J-27 ; J]) |
| 48 | `trail_running` accepté |
| 49 | `treadmill_running` accepté |
| 50 | Arrondi ACWR à 3 décimales |

## 14. Commandes exécutées

```bash
# Suite PR06 uniquement
cd backend
PYTHONPATH=/app/backend python -m pytest tests/test_training_v2_training_load.py -q
```

## 15. Résultats exacts des tests

### Suite PR06

```
50 passed in 0.66s
```

### Suite PR01→PR06

```
186 passed in 1.34s
```

0 failed, 0 errors.

## 16. Résultat du backend health

Non testé en isolation dans cet environnement (pas de serveur démarré localement). Aucune route, aucun serveur, aucun middleware n'a été modifié par PR06 ni par ce correctif. `GET /api/health` reste intact.

## 17. Confirmation : aucune route, recommandation ou plan modifié

- Aucun fichier dans `backend/engine/` modifié
- `training_engine.py` non modifié
- `coach_service.py` non modifié
- `server.py` non modifié
- Aucun router modifié
- Aucune logique de recommandation modifiée
- Aucun plan de génération modifié
- `backend/engine/training_load_engine.py` non modifié, non supprimé

## 18. Confirmation : aucun fichier protégé touché

- `.env` : non touché
- Fichiers de configuration : non touchés
- Redis / Garmin sync : non touchés
- Frontend : non touché
- Abonnements / Paddle / authentification : non touchés

## 19. Fichiers modifiés (PR90 — corrections d'architecture)

| Fichier | Modification |
|---|---|
| `backend/training_v2/training_load.py` | Suppression `ESTIMATED_MINUTES_PER_KM` et fallback distance×6 ; docstring enrichi (séparation TrainingHistory/TrainingLoadSnapshot, exclusions explicites) |
| `backend/tests/test_training_v2_training_load.py` | Remplacement tests fallback par tests "distance seule → 0 charge" ; suppression `test_only_valid_distance` et `test_estimated_minutes_per_km_constant` |
| `backend/PR06_rapport_final.md` | Ce rapport mis à jour |

Aucun autre fichier touché.

## 20. SHA final du commit

Disponible après le push (généré par `engine-tools-report_progress`).

