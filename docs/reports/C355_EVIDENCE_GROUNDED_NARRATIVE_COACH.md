# C355 — Evidence-Grounded Narrative Coach

## 1. Architecture

Backend uniquement, lecture seule. V3 reste l'autorité des faits, des comparaisons,
des tendances et de la conformité à la prescription. Aucun nouvel audit Garmin,
aucun changement de calcul, de seuil, de zone ou de plan.

- **Narrative Context Builder** : sélectionne les affirmations permises par les
  sorties typées V3 et les lie à leurs références exactes. Le contexte envoyé au
  fournisseur ne contient ni document MongoDB, ni identifiant, ni nom, ni date,
  ni texte libre issu des données.
- **Narrative Generator** : compose des phrases FR/EN/ES, avec un mode
  déterministe disponible sans fournisseur. Le LLM optionnel est un éditeur
  contraint des formulations autorisées, pas une autorité scientifique.
- **Evidence Validator** : refuse toute affirmation extérieure au catalogue
  construit pour les preuves courantes. Une référence existante ne suffit pas
  pour autoriser un texte incompatible.

Le chargement réutilise l'analyse V2 déjà nécessaire à V3, sans nouvelle lecture.
La régularité des répétitions n'est pas un jugement exposé dans le contrat V3 :
les sorties existantes `phase_analysis.effort_regularity` et `coach_language`
de V2 sont donc transmises séparément au contexte, sans nouveau calcul. Une
disponibilité ou une confiance haute ne signifie jamais « répétitions régulières ».

## 2. Fichiers modifiés

- `backend/narrative_coach_v3.py` : contexte, composition, validation et cache.
- `backend/narrative_coach_v3_models.py` : contrat narratif et enveloppe additive.
- `backend/workout_intelligence_v3_service.py` : chargement partagé, transmission
  des jugements existants et isolation des erreurs narratives.
- `backend/server.py` : réponse additive sur la route V3 existante.
- `backend/tests/test_narrative_coach_v3.py` : cas métier et adversariaux.
- `backend/tests/test_workout_intelligence_v3.py` : contrat additif et isolation
  du narratif, conservation du chargement historique.
- Ce rapport.

Les modèles factuels V2/V3, le mapping Garmin, les données persistées et le
frontend ne sont pas modifiés.

## 3. Contrat API

La route authentifiée existante
`GET /api/coach/workout-intelligence/{workout_id}?language=fr`
conserve ses contrôles d'accès et ses erreurs 403/404/422. L'enveloppe conserve
`workout_id` et `workout_intelligence_v3` et ajoute `narrative_coach_v3` :

| Champ | Type |
| --- | --- |
| `headline`, `analysis`, `interpretation` | chaîne |
| `recommendation` | chaîne ou `null` |
| `limitations`, `evidence_refs` | tableaux de chaînes |
| `language` | `fr`, `en`, `es` |
| `generation_mode` | `llm_validated`, `deterministic_fallback`, `none` |

Les références V3 sont relatives à `workout_intelligence_v3`. Les références
`phase_analysis.*` et `coach_language.*` désignent les sorties V2 préexistantes,
pas de nouveaux champs inventés dans V3. L'endpoint V2 reste inchangé. Le
chargeur V3 historique conserve sa signature de retour à deux éléments.

Une erreur narrative ne transforme pas des faits V3 disponibles en erreur HTTP :
le service tente le fallback puis, en dernier recours, renvoie le mode `none`
avec des chaînes vides et aucune recommandation.

## 4. Validation réelle des affirmations

La validation n'est ni une recherche de mots interdits ni un second avis LLM.
Les conditions d'admission des affirmations sont évaluées côté serveur à partir
des sorties autoritatives. Le fournisseur ne peut choisir que des formulations
préalablement autorisées pour ces preuves. Toute prose libre, référence inventée
ou affirmation contradictoire provoque le fallback. Les textes libres du
diagnostic historique ne sont pas recopiés aveuglément.

Le contexte pertinent est sélectionné avant l'appel. La réponse attendue est
un objet `selections` contenant des identifiants autorisés et des indices de
formulation, ou leur forme compacte à deux indices. Le validateur reconstruit
le catalogue depuis les preuves courantes, exige chaque affirmation retenue
exactement une fois, conserve les limites et rejette les clés supplémentaires,
les doublons, les indices invalides et les références proposées par le modèle.
Le serveur restitue les phrases du catalogue, jamais une chaîne libre du LLM.

Les jugements de répétitions réutilisent uniquement les codes reconnus de
`coach_language`, les métadonnées de jugement connues et les preuves numériques
finies avec des comptes cohérents. Les jugements manquants, ambigus ou limités
à deux efforts ne deviennent pas une appréciation de toute la série.

Cela exclut également les hallucinations portant sur la météo, le terrain, la
fatigue, les objectifs, les allures cibles ou les zones cardiaques : aucune
formulation correspondante n'est ouverte au générateur.

## 5. Stratégie LLM et fallback

Le fournisseur n'est pas requis pour afficher une analyse utile. L'activation
LLM est volontaire via `C355_NARRATIVE_LLM_ENABLED=true` (désactivée par défaut).
Le transport isolé existant
`llm_coach._call_gpt` est réutilisé, sans historique de conversation ni contexte
personnel complet. Aucune nouvelle dépendance n'est ajoutée au dépôt.

Le fallback est construit avec les mêmes affirmations admises et les mêmes
références que le mode validé. Les pannes, délais dépassés, JSON invalides et
rejets de validation ne sont pas exposés sous forme de texte fournisseur.

## 6. Coûts et performances

Le mode déterministe et les résultats déjà validés en cache n'effectuent aucun
appel fournisseur et n'engendrent aucun coût LLM supplémentaire. Le cache est
local au processus, borné à 128 entrées, indexé par le contexte expurgé, la langue et la
version de génération. Il ne persiste rien dans MongoDB.

Sur un cache manquant avec LLM activé : au plus un appel par invocation, sans
nouvelle tentative automatique. Le délai externe est de 8 secondes ; il borne
le transport existant, dont le délai interne est de 15 secondes. Le modèle
configuré dans ce transport est `gpt-4.1-mini`. Les sélections JSON compactes
sont conçues pour rester compatibles avec sa limite historique de nettoyage
de 700 caractères. Les résultats rejetés et les fallbacks de panne ne sont
pas conservés dans le cache validé.

Les journaux C355 ne contiennent que l'issue opérationnelle (cache, résultat
validé, indisponibilité, rejet, timeout ou erreur), sans texte fournisseur ni
preuves personnelles. Le transport existant mesure la durée de ses appels ;
il ne fournit pas ici une facture ni un comptage de tokens fiable.

Estimation budgétaire **illustrative**, pas un tarif fournisseur vérifié :
avec 4 000 tokens d'entrée, 200 de sortie, 0,40 USD/million en entrée et
1,60 USD/million en sortie, une analyse non cachée coûterait environ
0,00192 USD. La formule à appliquer au tarif effectif est
`(tokens_entrée × tarif_entrée + tokens_sortie × tarif_sortie) / 1 000 000`.
Ces hypothèses ne constituent ni une consommation mesurée ni un plafond
technique de facturation. Désactivé ou servi depuis le cache : zéro appel
supplémentaire.

Les coûts réels fournisseur et les latences de production ne sont pas mesurés
par les tests synthétiques ; aucun chiffre de facturation ne doit être déduit
de ces tests.

## 7. Validation et références de livraison

Base cible : `copilot/dev`.

SHA base inspecté : `41100f12b48f384ff65d9cba9f8fe305af96fe73`.

HEAD d'implémentation testé : `652b4d3da17f83e4f3f75b294a5e9ae3997f0775`.
Les seules modifications de livraison suivantes complètent ce rapport ; le SHA
final incluant cette documentation est indiqué dans la PR et la réponse de livraison.

Version de génération : `c355-controlled-7`.

Résultat du dernier contrôle élargi : **1 246 tests réussis, 3 échecs
préexistants**, dont **145 tests narratifs réussis**. Les nouvelles vérifications
couvrent progression probable, stabilité, historique insuffisant, footing
relatif sans LT1, régularité disponible ou indisponible, absence de splits,
séance indéterminée et prescriptions absentes ou non autoritatives.

Les tests adversariaux couvrent fournisseur indisponible, timeout, JSON
invalide, réponse contradictoire munie de références existantes, référence
inventée, hallucinations de seuil et de progression. Ils couvrent également
FR/EN/ES, déterminisme, validation des limites obligatoires, cache/version/langue,
restitution des jugements canoniques, absence de lectures supplémentaires,
isolation des erreurs et maintien des contrôles d'accès et des faits V2/V3.

Commande de la dernière sélection (depuis le répertoire backend, avec
l'interpréteur de l'environnement de test temporaire restauré pour cette tâche) :

```bash
cd /home/runner/work/sauvegarde260708/sauvegarde260708/backend
python -m pytest \
  tests/test_narrative_coach_v3.py \
  tests/test_workout_intelligence_v3.py \
  tests/test_workout_analysis_v2.py \
  tests/test_workout_analysis_v2_phases.py \
  tests/test_workout_analysis_v2_facts.py \
  tests/test_workout_analysis_v2_unified.py \
  tests/test_coach_language.py \
  tests/test_coach_session_synthesis_c351.py \
  tests/test_coach_repetition_judgment.py -q --tb=short
```

`backend/pytest.ini` conserve ses deux workers xdist et `--dist loadscope`.
Les environnements temporaires ont été supprimés après exécution ; aucun
manifeste de dépendances n'a été changé. Le contrôle flake8 ciblé de
l'intégration (`E9,F63,F7,F82`) a réussi ; il ne constitue pas un lint complet
du module narratif.

Le contrôle élargi a également exposé trois assertions préexistantes FR/EN/ES
dans `test_workout_analysis_v2.py` : le test attend
`meaning.consistent_pacing`, tandis que le moteur renvoie
`meaning.hr_without_intensity_with_pacing`. Le moteur et ce fichier de tests
sont identiques à la base inspectée ; C355 ne modifie pas cette décision V2 et
ne supprime pas ces assertions. Ces échecs doivent rester visibles dans le
bilan, sans être présentés comme des tests réussis.

## 8. Exemples narratifs

Les trois exemples ci-dessous sont **synthétiques**. Ils ne constituent pas une
nouvelle consultation de données Garmin ni un audit des séances réelles.

Validation explicite des trois exemples : reconstruction de leurs entrées,
du contexte et des arguments de phases/jugement, puis appel de
`validate_narrative_selection` avec `{"selections": [[index, 0], ...]}` pour
toutes les affirmations admises. Résultats : **PASS / PASS / PASS**, avec
respectivement six, six et cinq sélections. Tous les champs validés sont
identiques au fallback affiché, à l'exception du mode :
`llm_validated` pour les sélections acceptées, `deterministic_fallback` pour
les exemples rendus sans fournisseur. Aucun appel LLM réel n'a été effectué.

### 8.1 Footing probable sans LT1

Preuves : `easy_run_probable`, confiance basse, décision relative à l'historique
personnel, 12 références ; FC moyenne 139 bpm, LT1 absent, pas de splits ;
tendance `stable` sur cinq observations, variation médiane de −3 s/km ;
conformité à la prescription indéterminée. La variation numérique ne devient
pas une progression lorsque le jugement V3 est stable.

```json
{
  "headline": "Probablement un footing facile",
  "analysis": "Par rapport à vos 12 séances personnelles de référence, cet effort paraît relativement facile.",
  "interpretation": "Votre historique montre une tendance stable sur 5 observations (variation d'allure médiane de -3 s/km) ; cela ne démontre pas une amélioration.",
  "recommendation": "Vous pouvez conserver un effort confortable, sans chercher systématiquement à accélérer.",
  "limitations": [
    "Sans splits ni LT1 fiable, les moyennes de séance ne permettent pas de confirmer une zone physiologique.",
    "La conformité à la prescription reste indéterminée."
  ],
  "evidence_refs": [
    "session_classification.type",
    "session_classification.confidence",
    "session_classification.decision_tier",
    "session_classification.relative_effort.status",
    "session_classification.relative_effort.reference_count",
    "performance_trend.status",
    "performance_trend.confidence",
    "performance_trend.observation_count",
    "performance_trend.median_change_sec_per_km",
    "intensity_assessment.lt1",
    "intensity_assessment.position",
    "session_classification.limitations",
    "intensity_assessment.hr_metric",
    "prescription_assessment.status",
    "session_classification.relative_effort.relative_position"
  ],
  "language": "fr",
  "generation_mode": "deterministic_fallback"
}
```

Validation : toutes les phrases proviennent du catalogue admis ; aucune zone
physiologique ni progression n'est affirmée. Le conseil reste qualitatif et lié
à l'effort relativement facile ; il ne fixe ni allure, ni FC, ni nouvelle séance.

### 8.2 Fractionné de structure comparable au 19 septembre

Preuves : échauffement de 300 s, six efforts de
`[72, 180, 180, 180, 247, 60]` s, cinq récupérations de 180 s ; allures,
distances et FC des efforts absentes. V3 identifie `intervals` ; V2 fournit
un groupe de trois efforts comparables en durée sur six, mais
`effort_regularity.available=false`. Aucun jugement catégoriel de régularité
n'est disponible. Prescription absente.

```json
{
  "headline": "Une séance fractionnée",
  "analysis": "Garmin a enregistré 6 phases d'effort et 5 phases de récupération.",
  "interpretation": "Pour comparer ce qui est comparable, 3 des 6 efforts ont été regroupés selon une durée similaire ; des efforts de tailles différentes ne doivent pas être traités comme des répétitions équivalentes. L'alternance effort-récupération identifie le fractionné, mais la comparaison fournie ne permet pas d'établir la régularité d'exécution des répétitions.",
  "recommendation": null,
  "limitations": [
    "La régularité des efforts est indisponible ; les répétitions ne peuvent pas être dites régulières.",
    "Aucune comparaison fiable avec la prescription n'est disponible pour juger la conformité."
  ],
  "evidence_refs": [
    "session_classification.type",
    "session_classification.confidence",
    "session_classification.decision_tier",
    "session_classification.evidence.effort_count",
    "session_classification.evidence.recovery_count",
    "phase_analysis.effort_regularity.comparable_effort_count",
    "phase_analysis.effort_regularity.effort_count",
    "phase_analysis.effort_regularity.comparability_basis",
    "phase_analysis.available",
    "phase_analysis.effort_regularity.available",
    "prescription_assessment.status"
  ],
  "language": "fr",
  "generation_mode": "deterministic_fallback"
}
```

Validation : composition déterministe à partir du catalogue admis ; aucune
affirmation de régularité ou d'irrégularité. La recommandation reste `null`,
faute de prescription ou de conseil spécifique suffisamment établi.

À l'inverse, pour quatre répétitions dont le moteur existant fournit un jugement,
les tests vérifient la restitution du jugement réel — homogène, variations
perceptibles ou importantes — et de son écart numérique, avec ses limites de
couverture. Le cas n'utilise pas l'explication d'indisponibilité ci-dessus.

### 8.3 Tendance historique suffisamment étayée

Preuves : FC moyenne actuelle 145 bpm ; seuils personnels de laboratoire admis,
LT1 150 et LT2 170, datés du 1er janvier 2026, confiance haute ; allure actuelle
5,6 min/km ; quatre références antérieures à FC 145 bpm aux allures
`[6,0 ; 5,95 ; 5,70 ; 5,65]` min/km. V3 donne
`probable_improvement`, confiance moyenne, cinq observations et variation
médiane de −19,5 s/km. Pas de splits ; conformité à la prescription indéterminée.
Ce sont des données synthétiques, pas des valeurs de seuil ajoutées au produit.

```json
{
  "headline": "Probablement un footing facile",
  "analysis": "Votre FC moyenne (145 bpm) se situe sous LT1, selon vos seuils personnels.",
  "interpretation": "Votre allure médiane est plus rapide de 19.5 s/km à FC comparable sur 5 observations sur 70 jours : un signe encourageant d'amélioration probable, pas une preuve de gain de forme.",
  "recommendation": null,
  "limitations": [
    "Sans splits, la FC moyenne ne décrit pas le temps passé dans chaque zone.",
    "La conformité à la prescription reste indéterminée."
  ],
  "evidence_refs": [
    "session_classification.type",
    "session_classification.confidence",
    "session_classification.decision_tier",
    "intensity_assessment.hr_used_bpm",
    "intensity_assessment.position",
    "intensity_assessment.lt1",
    "intensity_assessment.lt2",
    "performance_trend.status",
    "performance_trend.confidence",
    "performance_trend.observation_count",
    "performance_trend.median_change_sec_per_km",
    "performance_trend.span_days",
    "session_classification.limitations",
    "intensity_assessment.hr_metric",
    "prescription_assessment.status"
  ],
  "language": "fr",
  "generation_mode": "deterministic_fallback"
}
```

Validation : signe, amplitude, cinq observations et 70 jours correspondent
à la tendance fournie ; la conclusion reste une amélioration probable, pas une
preuve physiologique. Aucune modification de plan n'est proposée.

## 9. Limites

La validation fermée privilégie la sûreté factuelle à la liberté de paraphrase.
Elle ne prétend pas valider sémantiquement une prose arbitraire en trois langues.
Le LLM peut améliorer la présentation, mais ne peut ajouter une explication
scientifique absente du catalogue.

Le cache n'est ni distribué ni persistant ; les appels concurrents ne sont pas
fusionnés entre processus. La validation des tests utilise un transport simulé,
pas une requête facturée ni un essai de qualité auprès de coureurs.

Le mode LLM est donc livré désactivé : une évaluation explicite de son apport
conversationnel et de sa facturation réelle reste nécessaire avant activation.
Les exemples de septembre reproduisent une structure synthétique, pas le
document réel : la confiance canonique de la fixture est conservée telle quelle,
sans la remplacer par la confiance annoncée dans un rapport antérieur.

L'absence d'une mesure reste une absence, jamais zéro. Une observation isolée
n'est pas une tendance. Une intensité relative n'est pas une zone physiologique.
Une analyse sans seuils personnels peut rester utile sans recommander
systématiquement un test LT1/LT2.

## 10. Verdict

**GO conditionnel** pour revue de la PR backend en brouillon ; aucune autorisation
de merge, déploiement ou activation LLM n'est donnée.

- Les tests C355 passent ; les trois échecs V2 inchangés restent signalés.
- Scan de secrets : aucun secret détecté.
- CodeQL Python : **0 alerte**.
- La revue automatisée incluse dans `parallel_validation` est indisponible
  (modèle absent du registre), malgré son libellé de réussite ; elle ne doit
  pas être présentée comme une revue effectivement exécutée.
- Revue indépendante en lecture seule : aucun problème significatif identifié
  dans le diff contre la base ; ni modification ni nouvelle exécution des tests
  par le relecteur.
- L'activation fournisseur et l'évaluation conversationnelle réelle restent
  soumises à validation explicite.
