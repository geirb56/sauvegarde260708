# RUNINDEX_PR225_REPORT — Readiness Runtime Data Truth

**PR #225 — Base: `copilot/dev`**  
**Date: 2026-08-30**

---

## Objectif

Supprimer toutes les fausses/stales données Garmin utilisées par Readiness.

---

## Audit des consumers

### 1. `garmin/readiness_adapter.py`

**Problème identifié :**  
`_latest_doc_with(docs, field)` et `_build_sleep_record(docs)` parcouraient les documents
sans vérifier leur date — un document RHR/HRV/sommeil vieux de plusieurs semaines pouvait
être présenté comme la mesure actuelle.

**Correction :**  
- Ajout de la constante `_MAX_PHYSIO_STALENESS_DAYS = 7`.
- `_latest_doc_with` accepte désormais un paramètre `reference_date` et rejette tout document
  dont la date est absente, non parseable, ou antérieure à `reference_date − 7 jours`.
- `_build_sleep_record` idem : staleness gate obligatoire.
- `_build_physio_signal` passe `reference_date` à `_latest_doc_with`.
- `build_readiness_v2_from_garmin_data` passe `reference_date` à `_build_sleep_record`.

### 2. `garmin/insights.py`

**Problèmes identifiés :**

| Ligne (avant) | Code fautif | Effet |
|---|---|---|
| `_latest_with(docs, key)` | pas de vérification de date | donnée stale présentée comme actuelle |
| `sleep_efficiency = 0.85` | fallback inventé | efficacité synthétique quand score absent |
| `sleep_hours_val = sleep_hours if sleep_hours is not None else 7.0` | fallback inventé | 7h de sommeil synthétique |
| `sleep_penalty = max(0, 8-val) + (1-eff)*2` | utilise les deux valeurs synthétiques | pénalité basée sur des données inventées |
| `"sleep_hours": round(sleep_hours_val, 1)` | expose la valeur synthétique | UI affiche 7h comme vraie donnée |
| `"sleep_efficiency": round(sleep_efficiency, 2)` | idem | 0.85 inventé affiché |

**Corrections :**
- `_latest_with` : staleness gate identique à l'adapter (importe `_MAX_PHYSIO_STALENESS_DAYS`),
  appelée avec `today` comme référence.
- `sleep_efficiency` : `None` quand `sleep_score_raw is None` — aucun défaut synthétique.
- `sleep_hours_val` : reste le `sleep_hours` brut (`Optional[float]`), jamais remplacé par `7.0`.
- `sleep_penalty` : calculé uniquement si `sleep_hours_val is not None`; terme efficacité ajouté
  seulement si `sleep_efficiency is not None`; `None` sinon.
- `sleep_status` : `"gray"` quand `sleep_penalty is None`.
- Raison sommeil : affiche `"Données sommeil absentes"` quand absent au lieu de crasher.
- Output dict : `sleep_hours` et `sleep_efficiency` exposés comme `None` quand absents.

### 3. `engine/readiness_engine.py`

**Problèmes identifiés :**
- `sleep_score: float = 70.0` — défaut synthétique en signature de fonction.
- `primary_score = 70.0` — fallback quand aucun signal physio disponible.

**Corrections :**
- `sleep_score: Optional[float] = None` — la pondération sleep est omise du calcul quand `None`.
- Retour `None` quand aucun signal physio (ni HRV, ni RHR/baseline) — jamais une valeur inventée.
- Pondération normalisée dynamiquement sur les composantes disponibles.

**Note :** ce module est du code legacy non utilisé dans le path V2 ; la formule Readiness V2
reste dans `training_v2/` (non modifiée).

### 4. Sync Garmin daily metrics (`garmin/service.py`)

Audité — aucune fabrication de données détectée. Le sync persiste les vraies valeurs du device
ou `None` ; pas de valeur synthétique injectée.

### 5. Dashboard (`garmin/insights.py`)

Corrigé ci-dessus — consumer principal du run-index.

### 6. Progress/Health

Audité — pas d'accès direct à RHR/HRV/sommeil identifié en dehors des paths déjà couverts.

---

## Tests créés — `tests/test_readiness_data_truth_pr225.py`

| # | Nom du test | Résultat |
|---|---|---|
| 1 | `test_today_metric_used_over_older_one` | ✅ PASS |
| 2 | `test_stale_metric_not_presented_as_current` | ✅ PASS |
| 3 | `test_absent_physio_stays_none` | ✅ PASS |
| 3b | `test_absent_rhr_hrv_produces_none_signals` | ✅ PASS |
| 4 | `test_no_sleep_7h_fallback_in_insights` | ✅ PASS |
| 5 | `test_today_sync_refreshes_metrics_used_by_readiness` | ✅ PASS |
| 6a | `test_readiness_v2_complete_data_produces_float_score` | ✅ PASS |
| 6b | `test_readiness_v2_no_activities_score_is_none` | ✅ PASS |
| 6c | `test_readiness_v2_formula_not_mutated` | ✅ PASS |

**Total : 9/9 PASS**

---

## Régressions Readiness V2

Commande :
```
python -m pytest tests/test_run_index_r3_readiness_v2.py \
  tests/test_training_v2_readiness.py \
  tests/test_training_v2_readiness_signals.py \
  tests/test_training_v2_readiness_subscores.py \
  tests/test_training_v2_readiness_sufficiency.py \
  tests/test_training_v2_readiness_decision.py -v
```

Résultat : **203 passed** — aucune régression.

---

## Doctrine respectée

- `None ≠ 0` — aucune donnée physiologique inventée.
- Aucun fallback `sleep=7h`, `sleep_efficiency=0.85`, `primary_score=70`.
- Donnée absente ou trop ancienne (`> 7 jours`) → `None`, jamais valeur synthétique.
- Fraîcheur exposée via staleness gate : seule une donnée dans la fenêtre `[reference_date−7, reference_date]` est utilisée comme mesure courante.
- Formule Readiness V2 (`training_v2/`) : **non modifiée**.

---

## Runtime Garmin réel

DEFERRED TO FINAL RUNTIME GATE (non disponible en sandbox CI).
