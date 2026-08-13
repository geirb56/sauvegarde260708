# RunIndex R3 — Rapport de migration Readiness V2

## Statut : IMPLEMENTED IN PR / PENDING MERGE

R3 reste **PENDING MERGE** jusqu'à validation runtime réelle.
Ne jamais écrire MERGED avant merge réel.

---

## HEAD de départ

`b273464` — R3: wire Readiness V2 to /run-index via readiness_adapter, 17 deterministic tests, update roadmap

HEAD de la branche après corrections audit :

`1bbab43` — R3: fix duplicate import and remove synthetic fallback in exception path

---

## 1. Correction baseline RHR / HRV

### Problème audité

L'implémentation initiale de `_baseline_for` incluait la mesure récente dans le calcul
de sa propre baseline, ce qui amortissait artificiellement les déviations sur des journées
anormales. La fenêtre utilisait `reference_date − 13 .. reference_date` (inclusive), ce qui
incluait potentiellement des valeurs hors fenêtre R1.

### Correction apportée

Fichier : `backend/garmin/readiness_adapter.py`

**Ancienne logique :**
- `_latest_non_none(docs, field)` → valeur récente (pas de date connue)
- `_baseline_for(docs, field, reference_date)` : fenêtre `reference_date - 13 → reference_date` (inclusive du jour courant)
- `valid_measures` comptait les mesures dans la fenêtre indépendamment de la mesure récente

**Nouvelle logique :**
- `_latest_doc_with(docs, field)` → document complet avec date
- `recent_value` = valeur du doc le plus récent non-None
- `recent_date` = date de ce document
- `_baseline_for(docs, field, recent_date)` :
  - fenêtre exacte = `recent_date − 14 jours .. recent_date − 1 jour` (14 jours antérieurs)
  - la mesure à `recent_date` est explicitement exclue
  - `valid_measures` = nombre exact de documents non-None dans cette fenêtre
  - retourne `None` si aucun document antérieur ne contient de valeur valide

**Garanties :**
- `recent_value` n'est jamais incluse dans sa propre baseline
- une valeur très anormale aujourd'hui ne distord pas sa baseline de référence
- les valeurs au-delà de 14 jours sont exclues
- `valid_measures` est un décompte exact (ni sur-estimé, ni sous-estimé)
- aucun fallback inventé : si pas de baseline antérieure → `None`

---

## 2. Tests déterministes — état après correction

### Tests baseline (nouveaux — audit R3)

| # | Description | Critère |
|---|-------------|---------|
| B1 | `recent_value` exclue de baseline | baseline = 52.0 même si today = 100.0 |
| B2 | Valeur très anormale ne modifie pas sa propre baseline | baseline identique avec/sans spike today |
| B3 | Valeurs > 14 jours exclues | baseline ignores doc à J−15 |
| B4 | Aucune baseline antérieure → `None` | `signal.baseline is None` |
| B5 | `valid_measures` exact | 5 docs valides dans fenêtre → `valid_measures = 5` |

### Tests readiness_adapter (existants)

| # | Test | Résultat |
|---|------|----------|
| 1 | Données complètes → score float, SUFFICIENT | ✅ |
| 2 | HRV absente → score computable, missing_hrv | ✅ |
| 3 | RHR absente → score computable, missing_rhr | ✅ |
| 4 | Sommeil absent → DEGRADED, score not None | ✅ |
| 5 | Charge absente → INSUFFICIENT, score None | ✅ |
| 6 | load_change_percent=None → score si physio ok | ✅ |
| 7 | Physio absent + pas de charge → INSUFFICIENT | ✅ |
| 8 | Isolation user (stateless adapter) | ✅ |
| 9 | Backward-compatible run_readiness key | ✅ |
| 10 | Aucun fallback legacy (None reste None) | ✅ |

Total tests `test_run_index_r3_readiness_v2.py` : **22 tests** (17 originaux + 5 baseline)

---

## 3. Tests d'intégration compute_run_index (nouveaux)

Fichier : `backend/tests/test_run_index_compute_integration.py`

DB fake avec `_FakeCollection` qui filtre par `user_id` (isolation DB réelle).

| # | Test | Critère |
|---|------|---------|
| I1 | `metrics.run_readiness` = float quand SUFFICIENT | ✅ |
| I2 | `metrics.confidence` exposée | ✅ |
| I3 | `metrics.sufficiency_level` exposée | ✅ |
| I4 | `metrics.readiness_reasons` exposée (list) | ✅ |
| I5 | INSUFFICIENT → `run_readiness = None` | ✅ |
| I6 | INSUFFICIENT → `recommendation_color = gray` | ✅ |
| I7 | `legacy_run_readiness` présent mais non-autoritaire | ✅ |
| I8 | Backward-compatible : clé `run_readiness` toujours présente | ✅ |
| I9 | `run_readiness` ≠ 0 pour INSUFFICIENT (None, pas 0) | ✅ |
| I10 | **Multi-user** : userA ≠ userB dans même fake DB | ✅ |
| I11 | **Isolation user_id** : données userB ne contaminent pas userA | ✅ |

Total tests `test_run_index_compute_integration.py` : **11 tests**

---

## 4. Frontend — Comportement run_readiness null

Fichier : `frontend/src/pages/Dashboard.jsx`

**Avant :**
```js
const runReadinessScore = m.run_readiness ?? 100;
```
→ affichait `100` quand `run_readiness` était `null` (fallback vert implicite)

**Après :**
```js
const runReadinessScore = m.run_readiness ?? null;
const runReadinessUnavailable = runReadinessScore === null;
```

**Comportement null :**
- Score `null` → affiche le label `runReadinessUnavailable` (i18n)
- Couleur grise (`#6b7280`)
- Pas de `/ 100` affiché
- Pas de `0`, pas de `100` inventé
- Pas de `RUN HARD` affiché

**`gray` ajouté à `REC_STYLES` :**
- `accent: "#6b7280"` — gris neutre
- `bg: "linear-gradient(135deg, #111827 0%, #1f2937 100%)"` — fond sombre
- La résolution `REC_STYLES[recommendation_color]` trouve maintenant `gray` sans fallback sur `green`

**i18n ajouté :**
| Langue | Clé | Valeur |
|--------|-----|--------|
| `en` | `dashboard.runReadinessUnavailable` | `"Unavailable"` |
| `fr` | `dashboard.runReadinessUnavailable` | `"Indisponible"` |
| `es` | `dashboard.runReadinessUnavailable` | `"No disponible"` |

**Graphique historique :**
Le filtre existant (`h.run_readiness !== null`) continue d'exclure les valeurs null du
graphique — aucun changement requis.

**Tests frontend :**
Fichier : `frontend/src/__tests__/dashboard-run-readiness-null.test.jsx`

- `run_readiness = null` → score ne contient ni "0" ni "100"
- `run_readiness = null` → pas de suffix `/ 100`
- `run_readiness = 78.5` → affiche `78.5`

---

## 5. Résultat runtime réel

**Statut : À VALIDER — validation runtime non encore effectuée**

La validation runtime doit être faite AVANT le merge de #118.

Procédure :
1. Sync réelle compte Garmin test
2. `GET /api/run-index`
3. Relever : `run_readiness`, `confidence`, `sufficiency_level`, `readiness_reasons`, `legacy_run_readiness`
4. Confirmer provenance V2 (`metrics.run_readiness` ≠ `legacy_run_readiness` chemin)
5. Vérifier sync progress : score présent → `ready` ; score None → `unavailable`

*Ce rapport sera mis à jour avec les valeurs réelles après exécution.*

---

## 6. Invariants R3 confirmés

| Invariant | Statut |
|-----------|--------|
| R1/R1.6/R2A/R2B non modifiés | ✅ |
| Poids 40/30/30 inchangés | ✅ |
| Aucun nouveau fallback introduit | ✅ |
| `legacy_run_readiness` conservé (non supprimé) | ✅ |
| LT1/LT2 non codés | ✅ |
| R3 PENDING MERGE (non mergé) | ✅ |

---

## 7. Limites avant R4

- `legacy_run_readiness` reste dans la réponse API pour diagnostic — suppression en R4
- R4 ne peut s'ouvrir qu'après validation runtime R3 satisfaisante
- Le graphique historique `history[].run_readiness` utilise encore le calcul legacy par jour
  (non V2) — c'est attendu pour R3 ; la migration complète de l'historique est hors scope R3
