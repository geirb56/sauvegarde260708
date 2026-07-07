# Validation E2E — Adaptation séance du jour ↔ Run Readiness

Date : 2026-07-01 · Données réelles : VMA=12.4 km/h (confidence=medium), ACWR=1.57.
Endpoint : `GET /api/training/today` · Fonction pure : `training_engine.adapt_session_to_readiness`.

## Table de référence allures (dérivées de la VMA)
`vitesse = VMA × %` ; `allure = 60 / vitesse`
60% Z1 récup · 65% récup active · 70% très facile · 75% endurance fond. ·
80% endurance soutenue (haut Z2) · 85-90% seuil/tempo · 95-100% interv. longs · 100-105% interv. courts.

## Résultats (VMA 12.4, séances réelles du plan)

| # | Scénario | reco / rr | adaptation_applied | Résultat |
|---|----------|-----------|--------------------|----------|
| 1 | RUN HARD / Endurance | RUN HARD / 85 | **false** | Inchangé — 4.1 km • 6:01/km • Z2 (HR 135-150) |
| 2 | EASY / Threshold | EASY / 60 | **true** | → Endurance 12min • 1.7 km • **7:27-6:55/km** • Z2 (HR 130-145) 65-70% VMA |
| 3 | EASY / Endurance | EASY / 65 | **true** | Endurance 21min (−15%) • 2.9 km • **7:27-6:55/km** (vs 6:01) • Z2 |
| 4a | REST modéré | REST / 48 | **true** | → Recovery 25min • 3.2 km • **8:04-7:27/km** • Z1 (HR<130) 60-65% VMA |
| 4b | REST important | REST / 30 | **true** | → Repos complet • 0min • aucune allure |

## Validation visuelle frontend (Dashboard, scénario 2 live)
Mercredi forcé en Threshold (6 séances/sem) → reco réelle EASY (65) :
- Run Readiness **65 / 🟡 EASY RUN** + badge **EASY RUN** (haut de carte).
- Notice **"Adapted: Easy run recommandé - séance dure convertie en endurance facile"**.
- Séance originale grisée : **Threshold** 5:12/km HR 165-175 (22 TSS).
- Séance adaptée verte : **Endurance** • **7:27-6:55/km** • **HR 130-145** • **Zone 2 (65-70% VMA)** (16 TSS).
- Cohérence totale : recommandation ↔ type ↔ allure ↔ zone ↔ FC ↔ badge.

## Règles garanties
- Run Readiness = source de vérité. EASY/REST ne laissent JAMAIS une séance de course inchangée.
- Un jour de repos planifié reste repos (rien à assouplir).
- `adaptation_applied=true` dès qu'un champ change (type/durée/allure/zone/FC).
- Toutes les allures recalculées depuis la VMA.

## Limite connue
- Impossible de forcer la reco RUN HARD/REST en live (dépend de l'ACWR réel). S1 et S4 validés au niveau fonction pure avec données réelles ; S2 validé de bout en bout (endpoint + UI).
- VMA via méthode "average" (confidence=medium) — estimation à affiner ultérieurement.
