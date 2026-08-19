# Micro-validation runtime déterministe — LOW / CAUTION / VERY_LOW (DailyAdaptation V2 post-PR #144)

Date: 2026-08-19 · Mode: **LECTURE SEULE** · Aucun code modifié · Aucune PR · Aucune donnée Garmin/Mongo/plan/planning modifiée · Date système inchangée.
Compte réel: `da8505ef-…`. Les `ReadinessDecision` par bande sont construits **de manière déterministe en mémoire** (aucune falsification des scores Garmin persistés). Le TrainingLoad et le RecentTrainingResponse sont **réels et identiques** dans les 3 scénarios.

## 1) État
- **HEAD** = `857f583` (contient PR#143 `0b6b6a0` + PR#144 `09a256f`). #143 ✓ · #144 ✓ · BUG-137-01 résolu · #132 actif runtime.

## 2) Séance de référence (inchangée)
- reference_date=`2026-08-23` · workout_type=`long_easy` · distance_km=`13.3` · duration_minutes=`None` · intensity_class=`low`.

## 3) TrainingLoad réel (identique aux 3 scénarios)
- acute_load_7d=`44.02` min · chronic_weekly=`71.870` min · ACWR=`0.612` · status=`low` · confidence=`high`. (valeur calculée, aucun fallback)

## 4) RecentTrainingResponse réel (identique aux 3 scénarios)
- response_status=`sufficient` · available_running=`6` · selected_running=`6` · observed_runs=`6` · hr_coverage_count=`6` · average_hr_recent=`135.0`
- trends: volume=`increasing`, frequency=`increasing`, long_run=`increasing`, cardiac_efficiency=`stable`, intensity_exposure=`increasing`
- Vérif signal #132: `recent is None` = **False** · `response_status == "sufficient"` = **True** · `observed_runs > 0` = **True** · fourni à `build_daily_adaptation` dans les 3 scénarios.

## 5) Scénario FAVORABLE (référence)
- ReadinessDecision(band=FAVORABLE, score=100).
- action=`KEEP` · adapté = long_easy 13.3 km low (identique) · reasons=`[READINESS_FAVORABLE, PLAN_KEPT, INTENSITY_NOT_INCREASED]`.

## 6) Scénario CAUTION
- ReadinessDecision(band=CAUTION, score=65, confidence=NORMAL, sufficiency=SUFFICIENT, reason_codes=(READINESS_CAUTION)).
- action=`SHORTEN`
- original: long_easy · 13.3 km · None · low → adapté: long_easy · **9.3 km** · None · low
- reasons=`[READINESS_CAUTION, LONG_EASY_PROTECTED, WORKOUT_SHORTENED, INTENSITY_NOT_INCREASED]`
- Contrôle: action autorisée ✓ · distance ↓ (13.3→9.3) · durée inchangée (None) · intensité inchangée (low) · aucun MOVE/UPGRADE/CATCH_UP ✓.

## 7) Scénario LOW
- ReadinessDecision(band=LOW, score=47).
- action=`SHORTEN`
- adapté: long_easy · **9.3 km** · None · low
- reasons=`[READINESS_LOW, LONG_EASY_PROTECTED, WORKOUT_SHORTENED, INTENSITY_NOT_INCREASED]`
- **SHORTEN_FACTOR=0.70** : 13.3 × 0.70 = 9.31 → arrondi 1 décimale = **9.3 km** ✓.
- Séance distance-only (duration=None) : le contrat matérialise SHORTEN **via la distance** (13.3→9.3) ; la durée absente reste `None` (pas de durée inventée). Comportement réel documenté, aucune règle de distance inventée.

## 8) Scénario VERY_LOW
- ReadinessDecision(band=VERY_LOW, score=30).
- action=`REST`
- adapté: `rest` · distance=None · duration=None · intensity_class=`rest`
- reasons=`[READINESS_VERY_LOW, REST_RECOMMENDED]`
- Séance supprimée/remplacée par repos · **aucun rattrapage, aucun transfert, aucune compensation** ✓.

## 9) Comparaison croisée
| Band | action | type | distance | durée | intensité |
|---|---|---|---|---|---|
| FAVORABLE | KEEP | long_easy | 13.3 km | None | low |
| CAUTION | SHORTEN | long_easy | 9.3 km | None | low |
| LOW | SHORTEN | long_easy | 9.3 km | None | low |
| VERY_LOW | REST | rest | — | — | rest |

## 10) Monotonicité (exigence physiologique réelle, pas ordre lexical)
- FAVORABLE (13.3 km, low) ≥ CAUTION (9.3 km, low) = LOW (9.3 km, low) ≥ VERY_LOW (repos).
- **VERY_LOW ≤ LOW ≤ CAUTION ≤ FAVORABLE** respecté sur type/intensité/durée/distance/suppression.
- Aucune bande moins favorable ne produit une séance plus exigeante. Intensité jamais augmentée (low ou rest partout). ✓

## 11) Absence legacy
- `daily_adaptation.py` = pure V2 : imports uniquement `readiness_decision`, `training_load`, `training_response`, `workout_generator`. Aucun `adapt_session_to_readiness`, `training_engine`, `fatigue_ratio`, `fatigue_status`, `fatigue_physio`.
- Chemin exclusif : ReadinessDecision V2 → TrainingLoad V2 → RecentTrainingResponse V2 → DailyAdaptation V2.

## 12) None semantics
- Aucun `estimated_tss=0` fabriqué (TSS absent = None). Aucun `ACWR=1` inventé (ACWR réel 0.612). Aucune durée artificielle (None conservé quand absent). Aucune distance artificielle (SHORTEN = distance réelle × 0.70). Aucun score physiologique fallback (scores de scénario construits explicitement en mémoire, TrainingLoad réel). `None != 0` respecté.

---

## VERDICT : **PASS**

11/11 critères réunis :
1. CAUTION exécuté sans crash ✓
2. LOW exécuté sans crash ✓
3. VERY_LOW exécuté sans crash ✓
4. Toutes les actions autorisées (KEEP / SHORTEN / SHORTEN / REST) ✓
5. Aucune séance plus dure que l'originale ✓
6. Monotonicité globale respectée (VERY_LOW ≤ LOW ≤ CAUTION ≤ FAVORABLE) ✓
7. SHORTEN respecte 0.70 (13.3→9.3) ✓
8. REST ne déclenche aucune compensation ✓
9. RecentTrainingResponse reste actif (sufficient, observed=6) et consommé dans les 3 ✓
10. Aucun legacy ✓
11. Aucun fallback fictif (None≠0) ✓

Note: le signal #132 identique n'a pas modifié l'action entre scénarios (la bande de readiness pilote la décision) — conforme au critère « disponible et consommé, pas forcément action différente ». Aucun trend `decreasing` → pas de code `RECENT_RESPONSE_CAUTION`, ce qui est cohérent avec les trends réels (increasing/stable).
