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

## C326 — Correctif de revue

### Audit et périmètre

HEAD relu avant correction : `db9f0fd55f9afe804571e225dbac96a8ac4ecd58`.
L'audit confirme que `_phase_observations` renvoyait une liste unique injectée
intégralement dans summary, meaning et advice. Les tests exigeaient cette triple
répétition. `_build_limitations` affichait directement les identifiants de qualité
et les noms anglais des données manquantes.

Fichiers modifiés par C326 uniquement :

- `backend/workout_analysis_v2.py` : observations réparties légèrement par rôle
  (faits essentiels, exécution, Coach, incertitudes), textes et localisation.
- `backend/tests/test_workout_analysis_v2_unified.py` : assertions de
  complémentarité, concision, couverture partielle et limitations FR/EN/ES.
- `RUNINDEX_PR326_UNIFIED_WORKOUT_ANALYSIS_REPORT.md` : cette section.

Le fichier test_workout_analysis_v2_phases.py a été relu et reste inchangé
dans ce correctif. Aucun nouveau moteur/service, aucune modification des
calculs #322/#323, modèles API, signaux, evidence, droits ou frontend.

### Régularité et complémentarité

Le score ≥90 provenait de la logique historique des splits kilométriques,
réappliquée aux efforts par la première implémentation #326. C326 retire
cette qualification : la dispersion mesurée suffit, sans seuil de réussite,
sans jugement physiologique et sans recalcul du score de cohérence.

Le résumé donne structure, durées/counts observés, allure moyenne des efforts
comparables et distance totale, sans série cardiaque ou limitations.
Meaning présente dispersion, extrêmes et évolution descriptive de FC,
avec couverture partielle si nécessaire. Advice retient un seul fait court :
écart d'allure entre les deux derniers efforts comparables mesurés si la
couverture est complète, sinon dispersion sur le sous-ensemble avec réserve.
L'absence de référence physiologique reste explicite dans meaning/advice
et les limitations, sans prescrire la suite de l'entraînement.

### Exemple avant/après : fixture 4 × 4 min (FR)

**Avant**, chaque champ reprenait notamment :
« Séance d'intervalles. 4 × 4 min d'effort observées. 4 × 3 min de récupération
observées. Allure moyenne 4:43/km, dispersion 7.7 s/km. Répétitions relativement
régulières. Effort 3 plus rapide (4:31/km), effort 4 plus lent (4:51/km).
FC 151 → 157 → 159 → 159 bpm, pas une mesure de dérive cardiaque.
Maximum 175 bpm. Intensité indéterminée. »
Summary ajoutait les totaux, meaning l'historique, advice l'autorité Training.

**Après**, exemple produit par le moteur :

- **summary** : « Séance d'intervalles. 4 × 4 min d'effort observées.
  4 × 3 min de récupération observées. Allure moyenne des efforts comparables :
  4:43/km. Distance totale : 14,26 km. »
- **meaning** : « Les 4 efforts comparables mesurés présentent une dispersion
  de 7,7 s/km. L'effort 3 est le plus rapide (4:31/km) ; l'effort 4 est le plus
  lent (4:51/km). La FC moyenne évolue de 151 à 159 bpm entre les efforts
  mesurés 1 et 4. Cette évolution ne constitue pas une mesure de dérive
  cardiaque. FC maximale observée dans les phases : 175 bpm. L'intensité
  physiologique ne peut pas être déterminée de manière fiable. »
- **advice** : « Le dernier effort comparable mesuré est plus lent de 19,8 s/km
  que le précédent. L'intensité physiologique ne peut pas être déterminée
  de manière fiable. »

Les codes `limitations.phases.*` restent identiques ; par exemple,
`effort_paces_incomplete` devient :

- FR : « Certaines allures d'effort sont manquantes ; l'analyse de régularité
  est partielle. »
- EN : « Some effort paces are missing; the regularity analysis is partial. »
- ES : « Faltan algunos ritmos de esfuerzo; el análisis de regularidad es parcial. »

Les données manquantes sont également nommées dans la langue demandée.
Splits absents, phases présentes, couverture cardiaque et intensité indéterminée
restent distingués.

### Tests et risques résiduels

Environnement de cette session : `/tmp/c326-venv/bin/python`, Python 3.12.3.
Commande identique aux 12 suites listées ci-dessus, avec cet interpréteur et
la configuration existante `-n 2 --dist loadscope`.
Les dépendances nécessaires aux tests ont été restaurées, pas de modification
des requirements ; les intégrations privées inutilisées par ces doubles
n'ont pas été nécessaires. Aucune prétention de baseline C326 : l'environnement
était prêt après le début des modifications.

Passage ciblé unified/phases : **109 exécutés, 109 réussis, 0 échoué,
0 ignoré**. Passage des 12 suites : **570 exécutés, 570 réussis,
0 échoué, 0 ignoré**, 12 avertissements de dépréciation existante.
Dernier passage après ajustement de ponctuation/historique : **570 exécutés,
570 réussis, 0 échoué, 0 ignoré**, 12 avertissements, 3,37 s.
`git diff --check` réussi. Aucun échec de suite constaté dans ce correctif.

Revue read-only indépendante : deux observations corrigées et testées :
la moyenne partielle du résumé affiche désormais sa couverture compacte
(ex. 3/4), et les références similaires sur 180 jours restent visibles même
en l'absence de baseline sur 14 jours. La limitation d'historique absent
reste dans limitations, pas dans l'interprétation d'exécution.
Passage final après ces corrections : **571 exécutés, 571 réussis,
0 échoué, 0 ignoré**, 12 avertissements, 3,35 s.

Risques résiduels : textes légèrement différents, aucune suite frontend
exécutée car aucun changement frontend ; qualité des mesures inchangée,
incertitudes conservées. Les champs sans observations suffisantes conservent
leur fallback historique. Les codes de diagnostic bruts restent disponibles
dans phase_analysis pour les outils techniques, pas dans les limitations
utilisateur. Aucun merge, déploiement ou accès en écriture aux données réelles.
Nouvelle revue C326 requise avant merge.

Validation du correctif : scan de secrets sans résultat ; CodeQL Python :
**0 alerte**. La revue automatisée standard reste indisponible (modèle absent),
la revue indépendante et ses deux corrections sont documentées ci-dessus.

Nouveau HEAD du correctif : `171ae0f1db8e819f0777cf9ada90c34976358168`.
Le commit suivant ne modifie que la traçabilité de ce rapport. Le SHA final contenant
ce rapport sera publié sur la PR #326 et dans le compte rendu final.
