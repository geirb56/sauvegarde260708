# PR326 — Workout Analysis V2 : Unified Interpretation

## Audit avant modification

Base vérifiée : `copilot/dev`, `0bc806fc9a566c16918e044a852036413d6fe072`.
Branche de travail : `copilot/create-unified-interpretation-analysis`.

Causes racines confirmées dans le code :

- `build_workout_analysis_v2` construit summary, meaning et advice avant
  `_build_phase_analysis`, appelé seulement dans le constructeur de réponse.
- `_build_summary` exploite uniquement les totaux et la FC globale.
  `_build_meaning` et `_build_advice` sélectionnent leurs textes à partir
  des signaux, splits et analyses cardiaques générales, jamais des phases.
- `_build_limitations` utilise exclusivement `evidence.has_splits` pour
  déclarer indisponible toute analyse des fractions, même lorsque des phases
  structurées sont présentes.
- `signals.session_type` représente historiquement le volume/durée
  (short/standard/long), ou easy/hard si intensité disponible : il ne doit
  pas être réinterprété comme structure d'intervalles.
- `_has_trusted_zone_provenance` renvoie actuellement False. Une FC maximale
  observée ou un nom contenant Z5 ne fournit pas de référence physiologique.
- Les phases et leurs statistiques/régularité sont déjà provider-neutral
  (`ActivityPhase`). Le service effectue une lecture Garmin bornée au
  user_id pour fournir ces données normalisées ; le moteur ne doit pas
  reprendre cette dépendance.
- Les comparaisons existantes comportent des réserves de comparabilité.
  Les écarts descriptifs ne doivent pas devenir une conclusion de progression.

Avant : calculs généraux → conclusions générales ; phases → annexe indépendante.
Après prévu : calculs spécialisés existants → observations consolidées →
une orchestration des champs conclusifs → contrat V2 étendu additivement.

Compatibilité : conserver les champs historiques, les calculs spécialisés,
les defaults sans phases et les contrôles d'accès existants. Les consommateurs
lisent le contrat V2 canonique ; aucun changement frontend prévu.

## Architecture réalisée

Les calculs généraux, cardiaques, d'allure, historiques et de phases restent
inchangés. Les phases sont maintenant calculées avant les conclusions.
`_phase_observations` transforme les statistiques existantes en observations
factuelles partagées par summary, meaning et advice. Les limites de phases
alimentent également les limitations générales. Le chemin historique sans
phases conserve ses textes et ses codes.

La régularité relative utilise le critère descriptif existant de consistency
≥90, appliqué au cohort d'efforts comparables, uniquement si celui-ci est
complet pour les allures. Aucun seuil physiologique n'est ajouté.
Les évolutions de FC sont décrites comme des valeurs entre répétitions,
jamais converties en dérive cardiaque. Les comparaisons restent descriptives.

## Fichiers modifiés

- `backend/workout_analysis_v2.py` : orchestration, observations, structure,
  evidence additive et limitations localisées EN/FR/ES.
- `backend/tests/test_workout_analysis_v2_phases.py` : remplacer l'ancienne
  assertion d'indépendance totale des conclusions par la conservation des
  calculs spécialisés et signaux historiques.
- `backend/tests/test_workout_analysis_v2_unified.py` : fixtures synthétiques
  provider-neutral et tests de cohérence, incertitude et contrat Coach.
- `RUNINDEX_PR326_UNIFIED_WORKOUT_ANALYSIS_REPORT.md` : ce rapport.

## Contrat API et consommateurs

Extensions additives avec defaults permettant de relire les anciennes réponses :

- `signals.session_structure` : signal de structure (intervals, continuous,
  other), ou unavailable lorsque les observations ne permettent pas de conclure.
- `evidence.has_structured_phases`, `has_effort_regularity`,
  `has_phase_heart_rate` : booléens distincts, False par défaut.

`signals.session_type`, `evidence.has_splits` et `has_heart_rate` conservent
leur sémantique historique. Les nouveaux codes conclusifs avec phases sont
`summary.structured_phases`, `meaning.structured_phases`, `advice.structured_phases`.
Les intervalles nécessitent une récupération observée entre deux efforts :
le titre n'est jamais utilisé. Sans phases, continuous exige un champ explicite
`session_structure=continuous` ; une activité simplement nommée run ne prouve
pas l'absence de fractions. Une phase effort couvrant la durée entière permet
également d'identifier une séance continue.

Consommateurs audités : WorkoutDetail, DetailedAnalysis, SessionDetail, ainsi
que le contrat CoachWorkoutDetail/CoachContext V2. Ils consomment les textes
canoniques et tolèrent les extensions ; aucun changement frontend.
Les contrôles `coach_workout_analysis` FREE/TRIAL/PREMIUM dans server.py et
access_control.py, ainsi que le loader borné au user_id, sont inchangés.

## Tests

Environnement : `/tmp/test_env_pr326/bin/python`, Python 3.12.3 ;
`python -m pytest` avec la configuration existante `-n 2 --dist loadscope`.
Les dépendances existantes ont été installées ; le wheel litellm privé
était inaccessible (distribution publique utilisée) et emergentintegrations
indisponible. Les tests ciblés utilisent des doubles, sans Mongo de production.

Baseline avant code : **369 passed**, 14 warnings, aucune défaillance,
pour test_workout_analysis_v2.py, test_workout_analysis_v2_phases.py et
test_coach_context_v2.py.

Premier passage après orchestration : 365 passed, 4 failed. Ces quatre
assertions exigeaient que les phases ne changent aucun champ conclusif ;
elles ont été adaptées à l'objectif demandé sans retirer les validations
des calculs spécialisés, des zéros ou des données absentes.

Suite élargie ciblée : **545 passed**, 14 warnings de dépréciation FastAPI.
Commande depuis backend :

```text
/tmp/test_env_pr326/bin/python -m pytest
tests/test_workout_analysis_v2.py tests/test_workout_analysis_v2_phases.py
tests/test_workout_analysis_v2_unified.py tests/test_coach_context_v2.py
tests/test_coach_workout_access_pr325.py tests/test_coach_contract_unified.py
tests/test_llm_coach_voice.py tests/test_subscription_middleware_a63.py
tests/test_subscription_status_quota_contract.py tests/test_subscription_tiers_contract.py
tests/test_rag_endpoints.py tests/test_idor_integration.py -q --tb=short
```

Cette suite couvre les droits, refus avant loader/LLM, isolation utilisateur,
contrats HTTP, Coach, absence de zones fiables, phases sans splits, phases
partielles/incohérentes et absence de progression ou dérive inventées.
Résultat final après correction de revue : **551 passed**, 14 warnings,
`git diff --check` réussi. Les phases inconnues sans observations exploitables
conservent désormais les conclusions générales existantes (test ajouté).

Validation sécurité : scan de secrets sans résultat ; CodeQL Python **0 alerte**.
La revue automatisée de parallel_validation était indisponible (modèle absent),
malgré son statut de sortie « Success ». Une revue read-only indépendante
code-review a identifié le cas des phases inconnues ; il a été corrigé et
couvert par test. Revue technique C326 toujours requise.

## Exemple synthétique du 10 octobre 2026

Fixture représentative, sans lecture du compte réel. Distances des efforts :
832,07 / 851,11 / 885,81 / 825,41 m ; 240 s chacun. Ces mesures non arrondies
donnent 283,03 s/km de moyenne et 7,687 s/km de dispersion, affichés
4:43/km et 7,7 s/km. Les allures affichées sont 4:48, 4:42, 4:31, 4:51/km.

```json
{
  "version": "v2",
  "signals": {
    "session_type": {"available": true, "code": "standard"},
    "session_structure": {"available": true, "code": "intervals"},
    "intensity": {"available": false, "code": null}
  },
  "evidence": {
    "has_splits": false,
    "has_structured_phases": true,
    "has_effort_regularity": true,
    "has_phase_heart_rate": true
  },
  "physiology": {"hr_drift": null}
}
```

Extrait des observations communes : « Séance d'intervalles. 4 × 4 min
d'effort observées. 4 × 3 min de récupération observées. Efforts comparables :
allure moyenne 4:43/km, dispersion 7.7 s/km. Les répétitions comparables sont
relativement régulières. L'effort 3 est le plus rapide (4:31/km) ; l'effort 4
est le plus lent (4:51/km). FC moyenne : 151 → 157 → 159 → 159 bpm ;
description entre répétitions, pas une mesure de dérive cardiaque. FC maximale
observée : 175 bpm. »

La synthèse conserve aussi le volume de 14,26 km ; les trois champs conclusifs
préservent l'intensité physiologique indéterminée. Advice rappelle l'autorité
Training Today/Week. Les limitations distinguent splits kilométriques absents
et phases présentes, sans nier l'analyse des fractions.

## Risques résiduels et gouvernance

- La provenance de zones fiable n'est toujours pas établie par le moteur :
  intensité indisponible, volontairement conservatrice.
- Les récupérations observées peuvent établir une structure, pas une intensité.
  Les mesures partielles conservent leurs réserves et leur couverture.
- Textes plus longs avec phases ; aucune suite frontend exécutée (aucun
  changement frontend). Les trois consommateurs ont été inspectés.
- La récupération de phases par le service reste limitée à son cache Garmin
  actuel ; le moteur accepte toujours ActivityPhase de toute source.
- Les codes techniques de qualité des phases sont conservés dans les réserves,
  avec un préambule localisé.
- Aucun changement GCCLI, Redis, Mongo, abonnement, onboarding, Training,
  prescription, ni drift Emergent activity_day. Aucun LLM ajouté au moteur.
- Aucun accès au compte réel, aucune écriture de données réelles, aucun merge
  ou déploiement. Revue technique C326 requise avant intégration.

Base exacte : `0bc806fc9a566c16918e044a852036413d6fe072`.
HEAD d'implémentation initiale : `31dfcb933455b43fd02bb74f7ef49ef66f7c9f39`.
Le correctif de revue et les résultats finaux sont inclus dans le commit suivant.
Le HEAD final du rapport
sera indiqué dans la description de PR (un fichier ne peut contenir le SHA
du commit qui le contient sans référence circulaire).
