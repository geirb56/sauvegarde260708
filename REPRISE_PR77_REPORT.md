# PR77 — Reprise après arrêt (comeback logic)

Date : 2026-06 · Périmètre : logique de reprise uniquement (Modes A/B) + consolidation
de la sortie longue + tests + rapport. **Aucun déploiement.** Moteur normal inchangé.

## Objectif
Corriger la logique de reprise après une période d'arrêt, en particulier :
- 4 semaines sans courir, 0 km réel sur 28 jours ;
- ancien coureur entraîné mais actuellement désentraîné ;
- éviter les plans incohérents (ex. sortie longue de 16 km dans une semaine de 12 km,
  ou effondrement du plan en semaine 2).

## Fichiers modifiés
| Fichier | Rôle |
|---|---|
| `backend/training_engine.py` | **Source unique** : `resolve_chronic_base`, `classify_training_state`, `resolve_reprise_plan`, `build_reprise_week_structure`, `cap_long_run_for_low_volume`, constantes `REPRISE_BASE_KM`, `REPRISE_STABLE_WEEKS`, `REPRISE_DEEP_SESSION_MINUTES` ; `compute_long_run_km` plafonne la sortie longue en faible volume. |
| `backend/llm_coach.py` | `generate_cycle_week` (générateur déterministe principal) : structure facile-only en reprise ; séances **par durée** (run/walk) en reprise profonde. |
| `backend/coach_service.py` | `generate_dynamic_training_plan` utilise `resolve_reprise_plan` et propage `context["training_state"]` ; `_deterministic_plan` route la sortie longue via `compute_long_run_km`. |
| `backend/server.py` | `/training/full-cycle` et `/training/week-plan` utilisent `resolve_reprise_plan` ; la semaine courante en reprise affiche des `session_types` faciles-only. |
| `backend/tests/test_reprise_pr77.py` | 7 scénarios obligatoires. |
| `backend/tests/test_real_cache_bypass_pr76.py` | tolérance d'arrondi ajustée. |

## Logique retenue
### 1. Base d'entraînement (séparée de la chronique physiologique)
`compute_current_weekly_km` (÷4, utilisée par ACWR/readiness) est **inchangée**. La base
du *target* est calculée par `resolve_chronic_base(workouts_28)` = moyenne sur les
**semaines actives** (celles contenant réellement des courses) → pas de dilution par ÷4
pour un athlète avec peu de semaines de données. 0 semaine active → `REPRISE_BASE_KM = 12`.

### 2. Classification adaptative (pas de durée fixe)
`classify_training_state` renvoie :
- `deep_reprise` : 0 km / 28 j → 1re semaine **par durée** (facile, run/walk), sans km imposé.
- `partial_reprise` : données récentes mais comeback précoce (< `REPRISE_STABLE_WEEKS`=3
  semaines actives tolérées) **ou** chute > 50 % du volume (resume guard) → facile-only,
  le volume progresse, l'intensité reste gelée.
- `reprise_exit` : assez de semaines tolérées → réintroduction de l'intensité **en tenant
  le volume** (jamais volume + intensité simultanément).
- `normal` : moteur standard.

La sortie de reprise dépend du **nombre de semaines actives réellement complétées**
(donnée), pas d'un calendrier fixe. Hook `recovery_red_flag` présent (par défaut `False`),
prêt pour la PR ultérieure sur les signaux d'alerte (Q3 reportée).

### 3. Progression
Base × +10 % (via `compute_target_km`), plafonnée par le resume guard (+5 % du chronique
quand chute > 50 %). En reprise, **seul le volume** progresse ; l'intensité reste facile.

### 4. Sortie longue (source unique)
`compute_long_run_km` est désormais la seule source ; elle intègre
`cap_long_run_for_low_volume` (≤ 40 % du target sous le plancher de l'objectif).
`_deterministic_plan` y est routé. Plus de plancher `long_min` imposé en faible volume.

### 5. Normalisation de l'arrondi (chemin réel corrigé)
`generate_cycle_week` arrondissait chaque distance de séance à 0,1 km indépendamment,
donc la somme dérivait du `target_km` (ex. 16,06 + 9,88 + 16,06 → **42,1** au lieu de 42,0).
Correctif : après construction des séances, le résidu (`target_km − somme`) est appliqué à
la **plus grande séance de course**, garantissant `weekly_km == target_km` exactement.
Le test (tolérance qui masquait le symptôme) a été remis en assertion **stricte** (`≤ 42`).
Nouveau test verrou : `test_weekly_total_matches_target_no_rounding_drift`.

## Scénarios testés (`test_reprise_pr77.py`) et résultats
| # | Scénario | Résultat |
|---|---|---|
| 1 | 0 km / 28 j (arrêt 4 sem) | `deep_reprise`, 3 séances endurance par durée (20/25/30 min), run/walk, aucune séance dure, ~10,5 km |
| 2 | S1→S2→S3 | 12,6 → 14,1 → 14,9 km, **aucun effondrement** |
| 3 | Sortie longue | jamais > 50 % du volume hebdo (reprise ~40 %) |
| 4 | Reprise partielle (chronique 40, dernière sem 15) | `partial_reprise`, facile-only, guard actif |
| 5 | Surcharge brutale (S1 12,6 puis 40) | amortie par la moyenne semaines actives (≤ 32) |
| 6 | Athlète normal (SEMI50/M80/10K40) | **aucune régression** : 55 / 88 / 44 km, intensité conservée |
| 7 | Volume + intensité non simultanés | reprise = facile (volume↑) ; exit = intensité réintroduite + volume tenu |

**Tests globaux liés : 150 passed** (`test_reprise_pr77`, `test_real_cache_bypass_pr76`,
`test_resume_guard_pr76`, `test_current_weekly_km_unification`, `test_cycle_dates`,
`test_training_engine_pr2`, `test_plan_duration_decoupled`).

**Smoke e2e HTTP** (nouvel utilisateur, 0 donnée) : `GET /api/training/plan` →
`state=deep_reprise`, `weekly_km=10.5`, séances 20/25/30 min, conseil run/walk. Backend sain.

## Non-régression confirmée
- resume guard PR76 : OK.
- protection contre la régression semaine 2 : OK.
- moyenne sur semaines actives : OK.
- plafonnement de la sortie longue en faible volume : OK.
- athlètes normalement entraînés : identique (55 / 88 / 44 km, sorties longues 31–34 %).

## Limites connues
- **Signaux d'alerte subjectifs (douleur/gonflement)** : reportés à une PR ultérieure
  (aucune donnée subjective dans le modèle). Hook `recovery_red_flag` prêt, non branché.
- **Récupération objective (HRV/readiness)** : non branchée dans cette PR (sortie de reprise
  basée sur la progression uniquement, conformément au choix « pas de dépendance santé »).
- **Générateurs de secours** (`_deterministic_plan`, `_generate_fallback_week_plan`) : la
  logique reprise vit dans le générateur déterministe principal `generate_cycle_week` (qui
  ne tombe jamais en échec en fonctionnement normal) ; les fallbacks respectent le
  target/sortie longue mais ne forcent pas la structure facile-only.
- gccli non officiel : dépend de la synchronisation Garmin réelle.

## Déploiement
Aucun. Correctifs à publier via **Save to Github** dans une PR dédiée à la reprise.
