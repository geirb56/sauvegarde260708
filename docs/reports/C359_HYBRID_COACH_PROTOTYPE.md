# Itération C360 antérieure — Narrative Planning & Controlled Rendering

## Portée et décision

Cette section documente l'itération C360 précédente ; le compte-rendu courant
« C360 — Evidence-Grounded LLM Coach » se trouve à la fin du fichier. Les
constats antérieurs restent des instantanés historiques. HEAD du code évalué
pour cette ancienne itération :
`7942e4bc2b14febe10bd0eadb8cb5296eb1563ec`.

### Architecture avant / après

| | Avant C360 | Après C360 |
| --- | --- | --- |
| Entrée fournisseur | Evidence Pack V3 structuré | Même Evidence Pack filtré par droits, sans assertion en prose ni source-path |
| Contrat | Synthèse libre accompagnée de déclarations de preuves, puis comparaison littérale du texte | Plan JSON sans prose : ID principal, IDs secondaires ordonnés, conclusions autorisées, limites essentielles et niveau de détail |
| Contrôle | Comparer chaque phrase générée à une assertion exacte ; rejet des paraphrases | Reconstruire les faits/droits, vérifier tous les IDs, conclusions et limites, refuser doublons/incompatibilités et niveau incohérent |
| Rédaction | Repli déterministe si le texte libre ne pouvait pas être prouvé | Rendu local contrôlé depuis les assertions V3 et des clauses de limite localisées ; le fournisseur ne fournit aucun texte affiché |
| Science / produit | HOLD | Autorités et permissions inchangées ; le plan est techniquement vérifiable, mais une vraie génération rédactionnelle et un gain produit ne sont pas démontrés : **HOLD** |

### Contrat du plan narratif

Un unique appel fournisseur demande exclusivement un objet de ce type :

```json
{
  "main_fact_id": "interval.count",
  "supporting_fact_ids": [],
  "conclusion_ids": {
    "interval.count": "recorded_intervals_without_regularity"
  },
  "required_limit_ids": {
    "interval.count": [
      "no_repetition_durations",
      "regularity_verdict_unavailable"
    ]
  },
  "detail_level": "concise"
}
```

Le serveur reconstruit les faits admissibles à partir de V3 et des permissions.
Le plan doit sélectionner entre un et trois faits distincts ; le nombre doit
respecter `concise` (1), `balanced` (jusqu'à 2) ou `detailed` (jusqu'à 3). Le
premier est l'observation principale ; l'ordre des IDs secondaires est conservé.
Chaque conclusion doit être exactement celle du fait. Toutes les limites
essentielles doivent être présentes ; des limites supplémentaires ne sont
acceptées que si elles appartiennent au fait. Le fait inconnu, une référence
historique non autorisée, un ID de conclusion absent/incorrect, une limite
essentielle omise, un doublon, une combinaison redondante ou une clé de prose
libre invalide le plan.

Étape A sélectionne et hiérarchise ; Étape B est un rendu local à partir de
phrases factuelles canonisées et de clauses de sécurité contrôlées. Il n'y a pas
de seconde génération libre ni de juge LLM. Cette frontière permet de vérifier
le contrat sans interpréter du texte, mais **ne permet pas au LLM d'écrire une
prose originale**. La flexibilité observée vient du plan (focus, ordre, faits
secondaires, détail), et non d'une validation sémantique d'un texte libre.

### Exemple complet — séance fractionnée

Faits admissibles (les champs privés, sources et textes arbitraires ne sont pas
transmis) :

- `interval.count`: efforts `4`, récupérations `3`; conclusion
  `recorded_intervals_without_regularity`; limites requises
  `no_repetition_durations`, `regularity_verdict_unavailable`.
- `intensity.position`: FC moyenne `160 bpm`, seuils personnels `LT1=150`,
  `LT2=170`, position `between_LT1_LT2`; conclusion
  `average_hr_threshold_position`; limites requises
  `average_not_whole_effort`, `no_time_in_zones`, `no_physiological_cause`.

Plan sélectionné : celui de l'exemple JSON ci-dessus. Il choisit le nombre
d'efforts/récupérations comme observation principale, n'ajoute pas la moyenne
cardiaque hors sujet et demande une réponse concise.

Texte C360 effectivement accepté :

> Garmin a enregistré une séance fractionnée avec 4 phases d'effort et 3 phases de récupération. La durée de chaque répétition n'est pas disponible, donc sa régularité ne peut pas être jugée.

Narrative V3 de référence, sur la même fixture :

> Une séance fractionnée. Garmin a enregistré 4 phases d'effort et 3 phases de récupération. La comparaison disponible ne permet pas d'établir la régularité des répétitions ; cela ne signifie pas qu'elles étaient irrégulières. La conformité à la prescription reste indéterminée.

Le rendu C360 nomme la séance et lie explicitement l'absence de durée au
non-jugement de la régularité ; il ne transforme pas l'absence de preuve en
irrégularité. V3 est plus fluide sur la réserve, tandis que C360 est plus
spécifique sur la limite des durées. Aucun texte d'un vrai LLM n'a été évalué.

### Sept comparaisons V3 / C360

Les faits ci-dessous sont **tous** ceux du paquet autorisé pour le cas. `valeurs
→ conclusion [limites essentielles]` les résume sans chemins de source. Les
plans et textes proviennent du transport planificateur **simulé**, puis du
rendu local effectivement accepté ; ils ne sont pas des sorties d'un fournisseur.
Les références V3 sont les rendus déterministes `deterministic_fallback` avec
les mêmes autorisations histoire/prescription. Les fixtures et sorties sont
synthétiques.

#### 1. Footing facile (`easy`)

- Faits : `session.kind` `{classification: easy_run_probable}` →
  `probable_session_type` [`probable_not_certain`]; `intensity.position`
  `{average_hr: 140, lt1: 150, lt2: 170, position: below_LT1}` →
  `average_hr_threshold_position` [`average_not_whole_effort`,
  `no_time_in_zones`, `no_physiological_cause`].
- Plan : principal `session.kind`; secondaire `intensity.position`;
  conclusions correspondantes; limites requises ci-dessus; `balanced`.
- C360 accepté : « Tu as probablement fait un footing facile. En complément,
  ta FC moyenne est de 140 bpm, sous LT1 ; elle ne décrit pas tout l'effort.
  Elle ne renseigne ni le temps passé dans les zones ni la raison de cette
  moyenne. »
- Narrative V3 : « Probablement un footing facile. Ta fréquence cardiaque
  moyenne (140 bpm) se situe sous LT1, selon tes seuils personnels. Ton
  historique comparable ne permet pas encore de savoir avec confiance si tu
  progresses ou si tes performances baissent. Sans splits, la FC moyenne ne
  décrit pas le temps passé dans chaque zone. La conformité à la prescription
  reste indéterminée. »
- Comparaison : même fait principal et personnalisation cardiaque ; C360 est
  beaucoup plus court et omet les réserves d'historique/prescription sans objet.
  Sa phrase de limite reste un ajout explicatif local, pas une rédaction LLM.

#### 2. Sortie longue (`long`)

- Faits : `session.long` `{duration: 100 min, usual_duration: 50 min}` →
  `probable_long_duration_comparison` [`probable_not_certain`,
  `duration_not_effort`]; `intensity.position` `{average_hr: 140, lt1: 150,
  lt2: 170, position: below_LT1}` → `average_hr_threshold_position`
  [`average_not_whole_effort`, `no_time_in_zones`, `no_physiological_cause`].
- Plan : principal `session.long`; secondaire `intensity.position`;
  conclusions et limites requises correspondantes; `balanced`.
- C360 accepté : « Ta sortie est probablement longue : 100 min, contre 50 min
  habituellement. La durée ne permet pas à elle seule d'estimer l'intensité.
  En complément, ta FC moyenne est de 140 bpm, sous LT1 ; elle ne décrit pas
  tout l'effort. Elle ne renseigne ni le temps passé dans les zones ni la raison
  de cette moyenne. »
- Narrative V3 : « Probablement une sortie longue. Ta fréquence cardiaque
  moyenne (140 bpm) se situe sous LT1, selon tes seuils personnels. Ton
  historique comparable ne permet pas encore de savoir avec confiance si tu
  progresses ou si tes performances baissent. Sans splits, la FC moyenne ne
  décrit pas le temps passé dans chaque zone. La conformité à la prescription
  reste indéterminée. »
- Comparaison : C360 expose la particularité 100/50 déjà calculée par V3 et
  rappelle que durée n'est pas intensité ; V3 ne montre pas la comparaison
  habituelle. La seconde réserve cardiaque rend toutefois C360 moins concise
  qu'elle pourrait l'être.

#### 3. Fractionné (`intervals_4x4`)

- Faits : `interval.count` `{efforts: 4, recoveries: 3}` →
  `recorded_intervals_without_regularity` [`no_repetition_durations`,
  `regularity_verdict_unavailable`]; `intensity.position` `{average_hr: 160,
  lt1: 150, lt2: 170, position: between_LT1_LT2}` →
  `average_hr_threshold_position` [`average_not_whole_effort`, `no_time_in_zones`,
  `no_physiological_cause`].
- Plan : principal `interval.count`; aucun secondaire; conclusion et deux
  limites requises correspondantes; `concise`.
- C360 accepté : « Garmin a enregistré une séance fractionnée avec 4 phases
  d'effort et 3 phases de récupération. La durée de chaque répétition n'est pas
  disponible, donc sa régularité ne peut pas être jugée. »
- Narrative V3 : « Une séance fractionnée. Garmin a enregistré 4 phases
  d'effort et 3 phases de récupération. La comparaison disponible ne permet
  pas d'établir la régularité des répétitions ; cela ne signifie pas qu'elles
  étaient irrégulières. La conformité à la prescription reste indéterminée. »
- Comparaison : C360 lie concrètement les deux limites et évite tout jugement
  d'irrégularité ; V3 formule plus explicitement que l'absence de preuve ne
  signifie pas des répétitions irrégulières. Aucune durée « 4 minutes » n'est
  inventée à partir du nom de la fixture.

#### 4. Données peu documentées (`sparse`)

- Faits : `session.unknown` `{classification: unknown,
  average_hr_available: 0}` → `session_type_unproven`
  [`unknown_not_easy`].
- Plan : principal `session.unknown`; aucun secondaire; limite requise;
  `concise`.
- C360 accepté : « Le type de ta séance reste incertain ; aucune FC moyenne
  n'est disponible. Un type inconnu ne signifie pas que la séance était facile. »
- Narrative V3 : « Type de séance incertain. Les données disponibles ne
  permettent pas d'identifier le type de séance de façon fiable. Ton historique
  comparable ne permet pas encore de savoir avec confiance si tu progresses ou
  si tes performances baissent. Sans splits ni LT1 fiable, les moyennes de
  séance ne permettent pas de confirmer une zone physiologique. La conformité à
  la prescription reste indéterminée. »
- Comparaison : C360 évite les réserves génériques et ne transforme pas les
  données absentes en séance facile. V3 fournit une explication plus complète
  du manque d'information ; le gain d'utilité n'est donc pas univoque.

#### 5. Tapis roulant (`treadmill`)

- Faits : `session.kind` `{classification: easy_run_probable}` →
  `probable_session_type` [`probable_not_certain`]; `intensity.position`
  `{average_hr: 140, lt1: 150, lt2: 170, position: below_LT1}` →
  `average_hr_threshold_position` [`average_not_whole_effort`,
  `no_time_in_zones`, `no_physiological_cause`].
- Plan : principal `session.kind`; secondaire `intensity.position`;
  conclusions et limites requises correspondantes; `balanced`.
- C360 accepté : « Tu as probablement fait un footing facile. En complément,
  ta FC moyenne est de 140 bpm, sous LT1 ; elle ne décrit pas tout l'effort.
  Elle ne renseigne ni le temps passé dans les zones ni la raison de cette
  moyenne. »
- Narrative V3 : identique au texte de la fixture `easy`.
- Comparaison : C360 ne produit aucune particularité tapis ; le seul fait tapis
  disponible n'autorise pas une comparaison historique ici. Cette fixture ne
  démontre donc pas de personnalisation spécifique au tapis.

#### 6. Historique comparable (`comparable_history`)

- Faits : `session.kind` `{classification: easy_run_probable}` →
  `probable_session_type` [`probable_not_certain`]; `intensity.position`
  `{average_hr: 140, lt1: 150, lt2: 170, position: below_LT1}` →
  `average_hr_threshold_position` [`average_not_whole_effort`, `no_time_in_zones`,
  `no_physiological_cause`]; `trend.probable_improvement`
  `{observations: 6, median_change: -24 s/km, span: 92 days}` →
  `qualified_historical_trend` [`not_proof_of_fitness`, `no_cause`,
  `terrain_weather_not_controlled`].
- Plan : principal `trend.probable_improvement`; secondaires, dans l'ordre,
  `session.kind`, `intensity.position`; conclusions et limites requises
  correspondantes; `detailed`.
- C360 accepté : « Ton historique suggère une amélioration probable : 6
  observations sur 92 jours, variation d'allure médiane de −24 s/km (récente
  moins ancienne) ; ce n'est pas une preuve de changement de forme. La cause
  n'est pas établie et les effets du terrain ou de la météo ne sont pas isolés.
  En complément, tu as probablement fait un footing facile. Autre repère utile :
  ta FC moyenne est de 140 bpm, sous LT1 ; elle ne décrit pas tout l'effort.
  Elle ne renseigne ni le temps passé dans les zones ni la raison de cette
  moyenne. »
- Narrative V3 : « Probablement un footing facile. Ta fréquence cardiaque
  moyenne (140 bpm) se situe sous LT1, selon tes seuils personnels. Ton allure
  médiane est plus rapide de 24 s/km à fréquence cardiaque comparable sur 6
  observations sur 92 jours : un signe encourageant d'amélioration probable,
  pas une preuve de gain de forme. Sans splits, la FC moyenne ne décrit pas le
  temps passé dans chaque zone. La conformité à la prescription reste
  indéterminée. »
- Comparaison : le plan place la tendance en tête et conserve sa qualification,
  puis ajoute type et FC. La formulation C360 devient toutefois longue et
  accumule des réserves ; V3 est plus fluide et personnalise aussi l'allure
  comparable. C360 n'établit pas qu'il soit plus agréable ou utile.

#### 7. Physiologie insuffisante (`no_physiology`)

- Faits : `intensity.hr` `{average_hr: 140}` →
  `descriptive_average_hr_only` [`no_physiological_zone`,
  `average_not_whole_effort`]; `session.unknown` `{classification: unknown,
  average_hr_available: 1, average_hr: 140}` → `session_type_unproven`
  [`unknown_not_easy`].
- Plan : principal `session.unknown`; aucun secondaire; limite requise;
  `concise`.
- C360 accepté : « Ta FC moyenne est de 140 bpm ; le type de ta séance reste
  incertain. Un type inconnu ne signifie pas que la séance était facile. »
- Narrative V3 : « Type de séance incertain. Les données disponibles ne
  permettent pas d'identifier le type de séance de façon fiable. Ton historique
  comparable ne permet pas encore de savoir avec confiance si tu progresses ou
  si tes performances baissent. Sans splits ni LT1 fiable, les moyennes de
  séance ne permettent pas de confirmer une zone physiologique. La conformité à
  la prescription reste indéterminée. »
- Comparaison : C360 conserve la moyenne disponible et refuse d'en faire une
  zone ou une intensité. Il est plus court, mais V3 explicite mieux pourquoi
  la physiologie n'est pas interprétable.

### Évaluation transversale

| Critère | Observation sur les sorties acceptées |
| --- | --- |
| Pertinence du fait principal | Le plan simulé met en tête durée ou tendance quand elles existent ; il garde le décompte comme fait central du fractionné. |
| Personnalisation | Le 100/50 min et le −24 s/km sont exposés. Le cas tapis reste identique au footing facile ; aucune spécialisation supplémentaire n'est démontrée. |
| Clarté / naturel | Les sorties courtes sont lisibles. La sortie historique ressemble encore à un assemblage de phrases canoniques, et certaines explications sont plus sèches que V3. |
| Répétitions | L'historique générique et la conformité indisponible sont omis. En contrepartie, plusieurs limites d'intensité peuvent s'accumuler dans la sortie détaillée. |
| Utilité | Le plan peut sélectionner et ordonner des informations utiles sans recopier systématiquement tous les faits. Les résultats synthétiques ne démontrent pas une utilité supérieure dans tous les cas. |
| Fidélité scientifique | Seuls les faits, conclusions et limites reconstruits localement sont rendus. Pas de zone depuis la FC moyenne seule, de régularité depuis des comptes, de durée depuis le nom de fixture, de causalité ou de prescription nouvelle. |

Le planificateur des comparaisons est un **mock déterministe** écrit pour les
fixtures, et le rendu est local ; ces résultats évaluent le contrat et ses textes
de sortie, **pas la qualité d'un véritable LLM**. Le plan peut être édité par un
fournisseur réel lorsqu'il est explicitement activé, mais aucun appel fournisseur
réel n'a eu lieu. Comme le texte affiché est construit localement, C360 ne
démontre pas une rédaction naturelle par LLM.

### Tests, sécurité et verdict

Tests ciblés existants et adaptés : `164 passed` pour
`backend/tests/test_hybrid_coach_c359.py`, incluant plans valides et invalides,
ID/conclusion inconnus, fait non autorisé, limite essentielle omise, ordre,
doublon/répétition, prose libre rejetée, timeout, JSON invalide, repli, accès,
flag, transport/latence et FR/EN/ES. La même suite couvre les sept fixtures
synthétiques ; aucune séance réelle n'a été utilisée. `py_compile`,
`git diff --check` et Flake8 ciblé (`E9,F63,F7,F82`) réussissent.

Limites : les faits V3 restent la seule autorité et ne sont pas recalculés ;
la validation du plan ne prouve pas que les entrées V3 sont vraies, ne garantit
pas la qualité éditoriale et ne vérifie aucun texte fournisseur puisque celui-ci
est refusé. Les clauses localisées constituent du rendu contrôlé, non un
vérificateur sémantique universel. Aucune écriture MongoDB, opération Garmin /
GCCLI, route, branchement production, déploiement ou merge n'a été effectué.
Le feature flag `C359_HYBRID_COACH_ENABLED` reste **OFF par défaut**.

- **GO technique :** contrat ID-only fail-closed et rendu local implémentés ;
  tests ciblés verts.
- **GO produit : non.** Aucun fournisseur réel, panel de qualité ou avantage
  constant sur Narrative V3 n'a été démontré.
- **Verdict global : HOLD.** Cette architecture contrôlée débloque une sélection
  narrative structurée, mais pas une rédaction libre sûre et une qualité
  supérieure vérifiée. Attendre l'audit C360 ; ne pas activer ni intégrer.

Base : `copilot/dev` (`720fb5cd31faca5f9f6435bb0be4c7cbf0f3fcf6`). HEAD final du
code C360 testé : `7942e4bc2b14febe10bd0eadb8cb5296eb1563ec`. Suite ciblée :
`/tmp/c360-validation-venv/bin/python -m pytest tests/test_hybrid_coach_c359.py -q --tb=short`
depuis `backend/` — **164 passed**.

# C359 — Coach hybride V1/V3, prototype contrôlé

## Revalidation de livraison — 22 octobre 2026 — HOLD maintenu

Cette section décrit la dernière itération ; les sections suivantes conservent
les résultats et l'audit historique des livraisons précédentes.

### Périmètre et architecture réellement présents

- PR **#359 existante**, toujours draft ; aucune nouvelle PR, activation,
  connexion UI/route, opération Garmin/GCCLI, écriture MongoDB, séance réelle,
  mise en production ou fusion.
- Base exacte `copilot/dev` :
  `720fb5cd31faca5f9f6435bb0be4c7cbf0f3fcf6`.
- HEAD reçu et relu avant cette itération :
  `ed41c4dddec4aba98ba44167af7af38c5a047ed7`.
- HEAD du code validé de cette itération :
  `bba6a47b5cbf407a34290a3b3fd7d8d2bb7bc82e`.
  La modification suivante est uniquement ce rapport ; le SHA final de
  livraison est consigné dans le commentaire de la PR pour éviter une référence
  autoréférentielle.

La branche reçue contenait **déjà** la correction de l'ancienne paraphrase :
faits structurés V3, prompt de synthèse libre, affirmations/provenances déclarées,
contrôle indépendant strict et repli sélectionné, avec verdict HOLD explicite.
Il serait inexact d'attribuer à cette dernière itération le remplacement initial
des substitutions. Le tableau avant/après et la méthode détaillée ci-dessous
décrivent cette architecture, conservée ici. Aucun moteur scientifique V2/V3 ni
transport de production n'a été modifié.

### Changements exacts de cette itération

Dans `backend/hybrid_coach_c359.py`, génération
`c359-selected-facts-hold-3`, une tendance n'est plus admise sur son seul
statut/confiance/delta : les champs **déjà évalués par V3** doivent se corroborer.
Une amélioration ou baisse exige `variation_confirmed=True`, un statut stable
exige `False`. La grille de sensibilité doit être présente et ses statuts
cohérents avec le verdict ; les limites `status_sensitive_to_criteria` et
`reference_structure_unknown` entraînent l'abstention, même en présence d'une
confiance contradictoire. La période doit être renseignée et positive.

Il s'agit d'un contrôle d'admission conservateur, **pas** d'une nouvelle analyse
historique : aucun seuil, cohorte, médiane ou calcul physiologique n'est
recalculé. Confirmation, limites et statuts de sensibilité sont rattachés aux
chemins de provenance locaux. La limite de contexte terrain/météo non contrôlé
figure dans le paquet de faits ; elle n'impose pas une réserve répétitive dans
chaque phrase, mais interdit d'en déduire une cause.

Dans `backend/tests/test_hybrid_coach_c359.py`, **51 cas supplémentaires** :
contradictions statut/confirmation/sensibilité/limites/période, refus d'une
assertion auparavant valide après modification de la preuve, repli sans tendance
rejetée, admissions positives des trois statuts cohérents et comparaison des
sept fixtures dans chacune des langues FR/EN/ES. Les fixtures et les tests
existants sont conservés ; les tests vérifient aussi l'absence de mutation de V3.
Les cas de statut construits pour tester le contrôleur ne sont pas présentés
comme de nouvelles séances évaluées scientifiquement.

### Comparaisons et limites du contrôle

Les **sept paires de textes complets**, reproduites dans la table « Comparaison
qualitative des sept fixtures conservées » ci-dessous, ont été régénérées et
vérifiées : leurs textes restent identiques après ce durcissement. L'évaluation
par cas et par critère reste donc applicable, avec les mêmes limites.
Les 21 comparaisons FR/EN/ES sont toutes en repli et HOLD. Les assertions servies
sont rattachées aux preuves locales ; les propositions libres simulées restent
rejetées. Le mock de proposition libre est rédigé en français : il exerce un
refus, **pas** une génération libre EN/ES réussie. Les admissions positives
FR/EN/ES portent sur les assertions locales, pas sur un LLM multilingue évalué.

**Aucun gain de qualité d'analyse LLM n'est démontré.** La sélection déterministe
améliore la pertinence de certains replis, mais ne satisfait pas à elle seule
l'objectif de synthèse intelligente. Le contrôle exact des assertions locales
n'est ni une validation sémantique générale, ni un contrôle de chiffres seul :
tout caractère servi est couvert par une assertion locale reconstruite depuis
les preuves et les droits. Des formulations libres pourtant correctes sont
refusées. Les nouvelles corroborations de tendance ne changent pas cette
frontière, ne garantissent pas la vérité des entrées et ne vérifient pas une
relation causale libre.

Deux blocages supplémentaires restent inchangés : V3 ne porte pas de verdict
autonome de régularité des répétitions ; le nettoyage partagé du transport coupe
à 700 caractères, potentiellement au milieu du JSON. Ni les comptes, ni une
disponibilité de régularité, ni les références déclarées par le fournisseur ne
comblent ces manques. Le registre de connaissances scientifiques reste vide.

### Vérifications exécutées sur ce code

Environnement Python isolé, outils de tests existants restaurés sans changer
les dépendances du dépôt ; `backend/pytest.ini` conserve
`-n 2 --dist loadscope`. Les erreurs initiales de dépendances absentes ont été
résolues dans cet environnement uniquement, sans modifier de test.

| Vérification | Résultat constaté |
| --- | --- |
| Hybride C359 + Narrative V3 + Workout Intelligence V3 | **498 réussis**, 7 avertissements |
| Les mêmes suites + V2, CoachLanguage, droits et synthèse de séance | **1452 réussis, 3 échecs**, 14 avertissements |
| Trois tests V2 concernés sur la base exacte extraite par `git archive` | **Les mêmes 3 échecs reproduits** |
| Sept comparaisons dans chacune des langues FR/EN/ES | **21 replis vérifiés, 21 HOLD**, aucun appel LLM |
| Flake8 ciblé existant `E9,F63,F7,F82` ; `git diff --check` | Réussis |
| Scan de secrets des deux fichiers Python avant commit | Aucune détection |
| CodeQL Python après commit | **0 alerte** |
| Revue du diff par agent en lecture seule | Aucun problème significatif signalé |
| Revue groupée de `parallel_validation` | **Indisponible** : modèle demandé absent du registre, malgré l'enveloppe « Success » |

Les trois échecs sont
`test_comparable_history_stays_separate_and_metrics_are_unchanged[en/fr/es]`,
dans `test_workout_analysis_v2.py:1838` : attendu
`meaning.consistent_pacing`, reçu `meaning.hr_without_intensity_with_pacing`.
Ils sont reproduits cette fois sur la base exacte, pas seulement repris d'un
rapport antérieur ; aucun de ces tests ni leur moteur n'a été modifié.

Commandes exécutées depuis le répertoire `backend/` de ce dépôt :

```sh
/tmp/c359-validation-venv/bin/python -m pytest \
  tests/test_hybrid_coach_c359.py tests/test_narrative_coach_v3.py \
  tests/test_workout_intelligence_v3.py -q --tb=line

/tmp/c359-validation-venv/bin/python -m pytest \
  tests/test_hybrid_coach_c359.py tests/test_narrative_coach_v3.py \
  tests/test_workout_intelligence_v3.py tests/test_workout_analysis_v2.py \
  tests/test_workout_analysis_v2_unified.py tests/test_workout_analysis_v2_facts.py \
  tests/test_workout_analysis_v2_phases.py tests/test_coach_language.py \
  tests/test_coach_workout_access_pr325.py tests/test_coach_session_synthesis_c351.py \
  -q --tb=line
```

Les booléens de prérequis fournisseur ont été vérifiés à nouveau : clé configurée
absente, SDK fournisseur absent. **Aucun appel LLM réel** n'a été effectué.
Coût et latence fournisseur restent **non disponibles**, jamais remplacés par
zéro ou par la durée d'un mock.

**Verdict : HOLD.** La sûreté du repli et les refus sont testés, mais la liberté
narrative nécessaire n'est toujours pas vérifiable de manière assez fiable.
Ni un juge LLM, ni une heuristique, ni un catalogue élargi de substitutions ne
sont présentés comme solution. Ne pas activer : garder #359 en draft et attendre
l'audit demandé.

## Correction après audit HOLD — PR #359 uniquement

La première version ci-dessous est conservée comme **instantané historique**,
pas comme description de la correction. Son gain de substitution lexicale ne
répondait pas à l'objectif de synthèse intelligente. Il ne suffit pas de
remplacer un catalogue de synonymes par un catalogue plus grand.

### Audit préalable de la correction, en lecture seule

Point de départ : `4466e3e0e79e5e86e41a4ce8124f045c6c4b0315`, sur la même
branche de la PR draft #359. Base d'intégration inchangée :
`copilot/dev`, `720fb5cd31faca5f9f6435bb0be4c7cbf0f3fcf6`.

Fichiers relus avant modification : prototype hybride, Narrative V3,
Workout Intelligence V3 et ses modèles, transport LLM, présent audit historique
et tests hybrides/V3. Aucune modification des autorités scientifiques n'est
nécessaire ni autorisée.

| Source à ce point de départ | Fait fiable disponible / frontière |
| --- | --- |
| `backend/workout_intelligence_v3.py:621–744` | Type de séance, confiance, règles et preuves. Une sortie longue porte déjà durée, durée habituelle, ratio et taille d'historique ; ne pas recalculer le seuil de classification. |
| `backend/workout_intelligence_v3_models.py:183–199` | FC moyenne, position **de cette moyenne** par rapport aux seuils personnels acceptés ; ni temps dans les zones, ni position de chaque répétition. |
| `backend/workout_intelligence_v3_models.py:202–231` | Référence d'effort relative à l'historique, explicitement non physiologique ; accès historique requis. |
| `backend/workout_intelligence_v3.py:919–974` | Tendance évaluée par le moteur, avec confiance/sensibilité. Une différence isolée ne crée pas une tendance. |
| `backend/workout_intelligence_v3_models.py:310–320` | Statut canonique de conformité, pas une autorisation de créer/modifier un entraînement. |
| `backend/workout_intelligence_v3.py:626–634` | Décompte des efforts/récupérations et **disponibilité** de régularité seulement. La confiance haute ne constitue pas un verdict « régulier ». |
| `backend/narrative_coach_v3.py:73–108,195–299` | Le verdict catégoriel de régularité utilisé par la narration actuelle vient des conclusions versionnées V2/CoachLanguage du même passage, pas du seul booléen V3. Pas de nouvelle déduction à partir de la dispersion. |
| `backend/llm_coach.py:209–299` | Transport existant, mais nettoyage générique à 700 caractères : risque de troncature du JSON structuré. Aucun changement du transport de production pour masquer ce blocage. |

Informations manquantes : objectif autorisé dans la sortie V3, durées
individuelles des répétitions, verdict de régularité V3 autonome, métadonnée
narrative spécifique tapis, preuve d'une cause de fatigue, service indépendant
de vérification sémantique générale. Le libellé de fixture « 4 × 4 min » n'est
pas une preuve permettant au narrateur d'énoncer les durées.

**Décision d'architecture avant la correction :** laisser le LLM proposer une
synthèse véritablement libre et structurée, mais ne jamais confondre cette
proposition avec du texte vérifié. Des références déclarées, des chiffres
corrects et des assertions structurées cohérentes ne prouvent pas l'équivalence
de leur formulation libre. Toute partie invérifiable doit être rejetée, pas
« validée » par une heuristique ou un second LLM. Sans solution fiable à cette
frontière, le verdict reste HOLD, même si la sélection déterministe des faits
devient plus utile.

### Protocole d'évaluation de la correction

Réutiliser les sept fixtures **sans changer leurs données** pour rendre un
résultat plus flatteur. La fixture fractionnée d'origine ne contient pas de
verdict de régularité. D'éventuels cas réguliers/irréguliers supplémentaires
doivent être identifiés séparément.

Pour chaque cas, distinguer :

1. Narrative V3 actuel à partir de la même preuve.
2. Proposition libre simulée (non assimilable à une réponse réelle du LLM).
3. Texte effectivement servi après contrôle ou repli.

Évaluer séparément exactitude, personnalisation, pertinence, naturel, concision,
conseil et fiabilité. Une meilleure sélection ou un meilleur repli déterministe
n'établissent pas un gain de qualité du LLM. Une phrase libre correcte refusée
doit compter comme une limite du prototype, pas être cachée du bilan.

Vérification des prérequis fournisseur dans le processus de cette correction :
clé de transport absente et SDK existant non installé dans le Python système.
Seuls ces booléens ont été vérifiés, sans lecture ni exposition de secrets.
Aucun appel LLM réel, aucun test de séance réelle ou accès aux données privées
n'a été effectué. Aucun coût ou temps fournisseur ne sera extrapolé à partir
des simulations. Le budget timeout est une limite, pas une latence mesurée.

### Architecture avant / après

| Couche | Première livraison, rejetée par l'audit | Correction |
| --- | --- | --- |
| Science | Moteurs V2/V3 existants | **Inchangés** ; aucun seuil, régularité, progrès ou prescription recalculé par le narrateur |
| Faits | Sous-ensemble du texte déjà présélectionné par Narrative V3 | `AdmissibleFact` construit depuis des champs structurés V3 : identifiant stable, valeurs/unités, conclusion autorisée, confiance, conditions, limites importantes, priorité et chemins de source locaux |
| Génération | Une phrase, substitutions prédéfinies | Demande de synthèse originale, choix/hiérarchie/relations des faits admissibles ; sortie structurée avec texte complet, affirmations et identifiants de preuves/conclusions |
| Contrôle | Grammaire de substitutions littérales | Reconstruction indépendante des assertions autorisées depuis V3 ; **aucun vérificateur d'entailment libre disponible** |
| Texte servi | Tout le catalogue rendu, une phrase éventuellement reformulée | Proposition invérifiable écartée ; sélection déterministe de faits utiles comme repli. Sous-ensemble littéral vérifiable distingué explicitement d'une synthèse libre validée |
| Verdict | Prototype prudent mais gain conversationnel non démontré | **HOLD explicite dans chaque résultat** ; pas de succès sémantique déclaré par défaut |

Les listes de synonymes et les fonctions `_equivalent` et
`validate_hybrid_lead` sont retirées, pas agrandies. Le paquet fourni au LLM
ne contient pas de phrase à recopier : `provider_fact()` exclut l'assertion
locale et les chemins de source. Les identifiants de preuve sont du vocabulaire
fixe (`interval.count`, `session.long`…), jamais les identifiants de séances
ou d'utilisateurs. Les textes libres des champs coach, limites et sources
arbitraires ne sont pas transmis.

Les autorisations sont contrôlées **avant** la construction privilégiée et
l'appel fournisseur. FREE est refusé ; TRIAL/PREMIUM passent par `UserAccess`.
L'historique et la prescription nécessitent toujours le booléen explicite
`True` côté serveur. Une conformité dérivée d'un type dépendant de l'historique
ne contourne pas cette restriction. Le résultat d'une erreur n'est jamais un
V3 complet non filtré.

Le prompt demande une réponse naturelle dans la langue du paquet FR/EN/ES,
non limitée à une phrase ni à trois paragraphes, sans inventer de conclusion
ou de prescription. Le transport RunIndex existant reste inchangé. Il n'est
appelé qu'en opt-in avec le flag expérimental ; aucun appel réel n'a été
effectué pour cette correction.

### Méthode de contrôle factuel et frontière non résolue

La sortie demandée au fournisseur a la forme :

- `text` : synthèse complète.
- `claims` : affirmations factuelles, chacune avec son `text`, ses
  `evidence_ids` et ses `conclusion_ids`.

Ces déclarations **ne sont pas une preuve**. Le contrôle ne compare pas
seulement les nombres, ni les assertions structurées entre elles : il
reconstruit le catalogue autorisé depuis les valeurs V3 et les droits.
Pour l'unique cas démontrable aujourd'hui, le texte d'une affirmation doit
être exactement une assertion locale, ses identifiants doivent correspondre
à cette assertion, et le texte complet doit être exactement l'assemblage de
ces affirmations, sans connecteur ni phrase non couverte. Identifiant inconnu,
doublon, changement d'unité, de négation, de confiance ou omission d'une réserve
matérielle échouent à ce contrôle.

Ce sous-cas est nommé `literal_subset_verified`, avec
`verification_scope=literal_assertions_only`. Ce n'est **pas** un générateur
libre certifié ; le verdict reste HOLD. La sélection, l'omission et l'ordre de
faits littéraux peuvent être acceptés, mais une reformulation libre même
plausible, une relation causale ou une interprétation nouvelle sont refusées.
Le texte non vérifié n'est ni renvoyé dans le résultat ni journalisé.

Une réponse bien formée mais non démontrable produit
`reason=semantic_verification_unavailable` et le repli autorisé. Les réponses
invalides/tronquées, les erreurs et les timeouts ont aussi un repli ; une
annulation du demandeur se propage. Il n'existe ni juge LLM présenté comme
garantie, ni score heuristique baptisé « équivalence sémantique ».

**Limites résiduelles :**

- Le sous-cas littéral est trop restrictif pour démontrer l'objectif V1 :
  des formulations correctes sont rejetées. C'est un blocage documenté,
  pas une nouvelle solution par substitutions.
- Des champs structurés identiques ne prouvent pas le sens d'un texte libre ;
  les relations entre faits (cause, concession, évolution, conseil) restent
  particulièrement difficiles à vérifier indépendamment.
- Les assertions locales et leur pertinence sont du code de présentation
  auditable, pas une preuve universelle de complétude ou de qualité humaine.
- La confiance dans les données d'entrée suppose une sortie canonique V3
  déjà limitée au propriétaire ; cet appel interne n'est pas une API acceptant
  des preuves ou droits fournis par le navigateur.
- Le nettoyage partagé de 700 caractères peut couper le JSON, dont le texte
  est répété dans les affirmations. Une réponse rejetée pour cette raison
  n'évalue pas la qualité du modèle.
- Le verdict de régularité autonome manque dans V3. Ni le décompte, ni la
  confiance, ni la disponibilité ne peuvent combler ce manque.

### Connaissances scientifiques futures

L'audit historique de la première livraison est conservé plus bas : aucun des
190 conseils non sourcés n'est réintroduit. L'interface immuable
`ValidatedKnowledgeProvenance` réserve une URI source, une empreinte et une
révision relue. Le registre `VALIDATED_KNOWLEDGE` est vide ; il n'y a ni loader,
ni recherche, ni entrée de texte scientifique activable par un appelant.
Le nom du type et une provenance déclarée ne valent pas validation scientifique.
L'admission future nécessitera une politique séparée de revue et de pertinence.

### Comparaison qualitative des sept fixtures conservées

Référence : **texte complet** du rendu déterministe Narrative V3 actuel, pas
uniquement son champ `analysis`. Même sortie scientifique, droits historiques
et prescription explicitement autorisés pour les deux textes. Les propositions
libres du transport simulé ont été refusées ; la colonne hybride ci-dessous
est donc le **repli réellement servi**, pas une synthèse LLM prétendument validée.
Les phrases et valeurs sont issues exclusivement des fixtures synthétiques.

| Séance | Narrative V3 actuel — texte complet | Hybride corrigé — repli déterministe |
| --- | --- | --- |
| Footing facile | Probablement un footing facile. Ta fréquence cardiaque moyenne (140 bpm) se situe sous LT1, selon tes seuils personnels. Ton historique comparable ne permet pas encore de savoir avec confiance si tu progresses ou si tes performances baissent. Sans splits, la FC moyenne ne décrit pas le temps passé dans chaque zone. La conformité à la prescription reste indéterminée. | Type probable de ta séance : footing facile. Ta FC moyenne est de 140 bpm, sous LT1 ; elle ne décrit pas tout l'effort. |
| Sortie longue | Probablement une sortie longue. Ta fréquence cardiaque moyenne (140 bpm) se situe sous LT1, selon tes seuils personnels. Ton historique comparable ne permet pas encore de savoir avec confiance si tu progresses ou si tes performances baissent. Sans splits, la FC moyenne ne décrit pas le temps passé dans chaque zone. La conformité à la prescription reste indéterminée. | Sortie longue probable : 100 min, contre tes 50 min habituelles. Ta FC moyenne est de 140 bpm, sous LT1 ; elle ne décrit pas tout l'effort. |
| Fractionné 4 × 4 min | Une séance fractionnée. Garmin a enregistré 4 phases d'effort et 3 phases de récupération. La comparaison disponible ne permet pas d'établir la régularité des répétitions ; cela ne signifie pas qu'elles étaient irrégulières. La conformité à la prescription reste indéterminée. | Garmin a enregistré 4 phases d'effort et 3 phases de récupération. |
| Séance peu documentée | Type de séance incertain. Les données disponibles ne permettent pas d'identifier le type de séance de façon fiable. Ton historique comparable ne permet pas encore de savoir avec confiance si tu progresses ou si tes performances baissent. Sans splits ni LT1 fiable, les moyennes de séance ne permettent pas de confirmer une zone physiologique. La conformité à la prescription reste indéterminée. | Le type de ta séance reste incertain ; aucune FC moyenne n'est disponible. |
| Tapis roulant | Probablement un footing facile. Ta fréquence cardiaque moyenne (140 bpm) se situe sous LT1, selon tes seuils personnels. Ton historique comparable ne permet pas encore de savoir avec confiance si tu progresses ou si tes performances baissent. Sans splits, la FC moyenne ne décrit pas le temps passé dans chaque zone. La conformité à la prescription reste indéterminée. | Type probable de ta séance : footing facile. Ta FC moyenne est de 140 bpm, sous LT1 ; elle ne décrit pas tout l'effort. |
| Historique comparable | Probablement un footing facile. Ta fréquence cardiaque moyenne (140 bpm) se situe sous LT1, selon tes seuils personnels. Ton allure médiane est plus rapide de 24 s/km à fréquence cardiaque comparable sur 6 observations sur 92 jours : un signe encourageant d'amélioration probable, pas une preuve de gain de forme. Sans splits, la FC moyenne ne décrit pas le temps passé dans chaque zone. La conformité à la prescription reste indéterminée. | Ton historique suggère une amélioration probable : 6 observations sur 92 jours, variation d'allure médiane de −24 s/km (récente moins ancienne) ; ce n'est pas une preuve de changement de forme. Ta FC moyenne est de 140 bpm, sous LT1 ; elle ne décrit pas tout l'effort. |
| Physiologie insuffisante | Type de séance incertain. Les données disponibles ne permettent pas d'identifier le type de séance de façon fiable. Ton historique comparable ne permet pas encore de savoir avec confiance si tu progresses ou si tes performances baissent. Sans splits ni LT1 fiable, les moyennes de séance ne permettent pas de confirmer une zone physiologique. La conformité à la prescription reste indéterminée. | Ta FC moyenne est de 140 bpm ; le type de ta séance reste incertain. |

Les réserves absentes du repli ne sont pas des assertions contraires : ne pas
parler de progrès quand aucune tendance n'est disponible n'exige pas une phrase
générique sur l'absence de progrès démontré. De même, ne pas qualifier la
régularité des quatre efforts évite d'affirmer aussi bien « réguliers » que
« irréguliers ». Les limites restent dans le paquet structuré pour empêcher le
générateur de dépasser ces droits d'interprétation.

Appréciation par cas, limitée aux **replis servis**, sans note chiffrée ni
attribution au LLM :

| Cas | Exactitude | Personnalisation | Pertinence | Naturel | Concision | Conseil | Fiabilité |
| --- | --- | --- | --- | --- | --- | --- | --- |
| Facile | FC/type autorisés | Type et moyenne propres au cas | Pas de réserve historique sans objet | Plus direct, début encore catégoriel | Deux faits | Aucun conseil nouveau | Réserve sur la moyenne maintenue |
| Longue | Durées déjà présentes dans V3 | 100 contre 50 min habituelles | Particularité de durée mise en tête | Comparaison compréhensible | Deux faits | Enseignement descriptif, pas de cible | Historique explicitement autorisé |
| Fractionné | Seulement 4 efforts/3 récupérations | Décompte spécifique | Pas de moyenne FC hors sujet | Simple mais peu explicatif | Un fait | Aucun gain de conseil | Ni régularité ni durées individuelles inventées |
| Peu documentée | Absence de moyenne, pas de toute FC | Limite propre au cas | Incertitude centrale seulement | Direct | Un fait | Abstention justifiée | Aucun type ou seuil inventé |
| Tapis | Identique au cas facile | Pas de particularité tapis exploitable | Aucun enseignement tapis démontré | Identique au cas facile | Deux faits | Aucun conseil nouveau | Aucune correction de tapis improvisée |
| Historique | −24 s/km, 6 observations, 92 jours | Tendance propre au cas | Tendance avant métrique secondaire | Plus dense, technique | Deux faits | Signal descriptif, pas de prescription | « Probable » et absence de preuve de forme maintenus |
| Sans physiologie suffisante | FC moyenne seule, type incertain | Valeur disponible utilisée | Pas de seuil fictif | Direct | Un fait | Abstention | Aucune zone ou intensité physiologique conclue |

| Critère | Observation sur ces textes servis | Limite / verdict partiel |
| --- | --- | --- |
| Exactitude | Valeurs et conclusions rattachées aux assertions locales ; pas de nouvelle mesure ou cause | Certification du sous-cas littéral uniquement, pas de validation sémantique libre |
| Personnalisation | La sortie longue expose maintenant 100 min contre 50 min habituelles ; FC disponible utilisée sans inventer de seuil absent | Aucun objectif, verdict de régularité ou contexte tapis ajouté ; pas de personnalisation supplémentaire démontrée pour tapis |
| Pertinence | La durée distinctive ou la tendance passe avant les métriques secondaires ; la moyenne de séance n'est plus utilisée pour commenter les répétitions | Règles de sélection de présentation, pas intelligence LLM démontrée |
| Naturel | Tutoiement et formulations moins administratives ; pas de rappel de conformité indisponible dans chaque séance | Appréciation de lecture, sans panel aveugle ; des formulations de type « Type probable » restent peu conversationnelles |
| Concision | Une ou deux assertions dans ces cas ; disparition des réserves répétitives sans rapport avec le fait retenu | Ne démontre pas à elle seule une meilleure analyse ni la complétude de la réponse |
| Conseil | Aucun entraînement/allure/zone conseillé sans autorité ; la comparaison de durée peut constituer un enseignement descriptif | Aucun gain de conseil personnalisé démontré ; ne pas inventer de recommandation pour remplir une structure |
| Fiabilité | Droits et dépendances indirectes fermés par défaut ; propositions libres refusées, erreurs et annulation testées | Fonction de synthèse libre toujours **HOLD** |

**Ce qui est réellement amélioré :** choix déterministe de l'information
distinctive (notamment la durée relative déjà calculée par V3), hiérarchie et
concision. **Ce qui n'est pas démontré :** un gain de qualité d'analyse provenant
du LLM, ni la capacité à servir une explication originale avec fiabilité.

Exemple de faux négatif assumé : dans la fixture longue, le transport simulé
propose « Avec 100 minutes face aux 50 habituelles, cette sortie se distingue
probablement par sa longueur, sans indication de difficulté. » Cette phrase
peut paraître cohérente avec les valeurs, mais le contrôle ne sait pas en
démontrer automatiquement le sens complet : elle est rejetée, pas présentée
comme validée. Les références déclarées ne changent pas ce résultat.

### Tests, mesures et verdict de la correction

Validation exécutée par l'agent d'implémentation, avec les outils existants
restaurés dans `.git/c359-venv`, sans modification des dépendances du dépôt :

| Exécution | Résultat |
| --- | --- |
| Dernière exécution des suites hybride, Narrative V3 et Workout Intelligence V3 | **447 réussis**, 7 avertissements |
| Régression élargie V2, CoachLanguage, droits et synthèse de séance, avant les dernières régressions de présentation | **954 réussis, 3 échecs** préexistants |
| Flake8 ciblé `E9,F63,F7,F82` et vérification des espaces du diff | Réussis |

Commande ciblée, depuis `backend/` :

```sh
TMPDIR="$PWD/../.git/c359-venv" ../.git/c359-venv/bin/python -m pytest \
  tests/test_hybrid_coach_c359.py tests/test_narrative_coach_v3.py \
  tests/test_workout_intelligence_v3.py \
  --basetemp=../.git/c359-venv/pytest-target-final \
  --junitxml=../.git/c359-venv/results-target-final.xml \
  -o junit_family=xunit1 -q --tb=line
```

La régression élargie couvre `test_workout_analysis_v2.py`,
`test_workout_analysis_v2_unified.py`, `test_workout_analysis_v2_facts.py`,
`test_workout_analysis_v2_phases.py`, `test_coach_language.py`,
`test_coach_workout_access_pr325.py` et
`test_coach_session_synthesis_c351.py`. Les trois échecs concernent
`test_comparable_history_stays_separate_and_metrics_are_unchanged[en/fr/es]` :
attendu `meaning.consistent_pacing`, reçu
`meaning.hr_without_intensity_with_pacing`. Leur reproduction sur la base
intacte est établie dans la première livraison conservée ci-dessous ; elle
n'a pas été refaite pour cette correction. Ces tests et moteurs restent
inchangés ; aucune suppression pour obtenir du vert.

Les tests couvrent les assertions exactes acceptées **et** les refus :
invention/modification de chiffres ou unités, contradictions texte/preuve,
FC moyenne confondue avec intensité des répétitions, FC maximale présente
sans moyenne, LT1/LT2 absents, progression non démontrée, régularité non
autorisée, cause de fatigue, prescription inventée, historique interdit et
dépendances indirectes, texte caché, identifiants/doublons/JSON invalides,
troncature fournisseur, erreur, timeout, annulation, FREE/TRIAL/PREMIUM et
français/anglais/espagnol. Les sept fixtures initiales sont conservées.

**Mesures fournisseur : non disponibles.** Les sept comparaisons ont
`cost=None` et `provider_duration_sec=None`. Aucun coût nul ou temps LLM
n'est inféré d'un mock. Le timeout de 8 secondes n'est pas une latence mesurée.

**Traçabilité de validation :**

- Base exacte `copilot/dev` :
  `720fb5cd31faca5f9f6435bb0be4c7cbf0f3fcf6`.
- HEAD de la correction de code :
  `c6b9a2bc6ae89c6121f5b0a2b9fb00c9dd3b4fbe`.
  Les dernières sources testées et le code analysé sont ceux de ce commit ;
  la mise à jour ultérieure du présent rapport est documentaire uniquement.
  Le SHA de livraison documentaire final est consigné dans le commentaire de
  livraison de la PR #359 pour éviter un SHA autoréférentiel dans ce fichier.
- Contrôle de secrets des trois fichiers modifiés : aucune détection.
- Validation parallèle après commit : **CodeQL Python, zéro alerte**.
- Revue automatisée groupée **indisponible**, malgré l'enveloppe « Success » :
  modèle `claude-sonnet-4.6` absent du registre. Ce résultat ne constitue pas
  une revue réussie. Une revue indépendante en lecture seule n'a identifié
  aucun problème significatif dans la correction.

**Verdict : HOLD.** Le prototype démontre une meilleure sélection déterministe
de certains faits, pas une synthèse intelligente libre suffisamment fiable.
Trois blocages techniques sont explicites : vérification sémantique libre
indisponible, réponse structurée exposée à la troncature de l'adaptateur partagé,
et absence d'autorité de régularité autonome dans l'entrée V3. À cela s'ajoute
l'absence d'évaluation d'un vrai fournisseur. Ne pas activer sur la seule base
de la fluidité des phrases simulées.

Livraison sur la même PR #359, toujours draft. Flag désactivé par défaut ;
aucune route/UI branchée, aucun moteur scientifique modifié, aucun accès
Garmin/GCCLI, aucune écriture MongoDB, aucun test de séance réelle,
déploiement ou merge. **Attendre l'audit C359 avant toute suite.**

---

## Instantané de la première livraison — non applicable à la correction

<details>
<summary>Audit historique conservé et résultats de la première livraison (avant correction)</summary>

## Périmètre et références

- Base : `copilot/dev`, `720fb5cd31faca5f9f6435bb0be4c7cbf0f3fcf6`.
- Branche de travail : `copilot/c359-prototype-controle`.
- Head de code testé : `d2947d539e50999ed92b0aad4ff1370fc023c2a7`.
  Les commits suivants ne complètent que ce rapport ; le SHA final de livraison
  est également indiqué dans la description de la PR.
- Tests : 390 réussis sur le périmètre hybride/Narrative V3/Intelligence V3 ;
  régression élargie : 919 réussis, 3 échecs V2 préexistants reproduits sur la base.
- Aucun branchement aux routes, aucune modification UI/science, aucun accès
  MongoDB/Garmin, aucune synchronisation, activation, livraison ou fusion.
- Ce rapport est un instantané C359, pas une nouvelle autorité scientifique.

## 1. Audit historique — consigné avant le premier changement de code

Le clone initial était superficiel. `git fetch --unshallow origin` a permis de
consulter les vraies versions historiques. Ne pas confondre le Coach
conversationnel historique avec `CoachLanguageV1`, couche déterministe récente
de conclusions V2.

L'introduction historique est retrouvée à
`fb0f68a253bcbf015e6dcccbab35d5fe82c40c3c`. À ce commit,
`backend/llm_coach.py:38–71` promettait un historique « COMPLETE », VO2max,
prédictions, ACWR et TSB, sans les bornes d'autorisation et d'incertitude
actuelles. Le prompt séance est à `:86–96`. Les imports historiques
`:20` et `backend/coach_service.py:28–37` dépendaient aussi de `training_engine`
(cibles de volume, semaine, phase, charge), dépendance à ne pas restaurer.
Ces observations portent sur cette version historique, **pas** sur le prompt
de chat actuel, qui a depuis reçu des garde-fous explicites.

### Chaîne historique retrouvée

| Version vérifiée | Mécanisme |
| --- | --- |
| `8f18c214d0907db92ab2090e25d4e30d83d326da:backend/rag_engine.py` | Dernière version avant suppression du RAG dans `794d77cbfa4af66963456ef10a3a0b20b8db244c`. `load_knowledge_base` (16), `retrieve_similar_workouts` (437), `retrieve_relevant_tips` (478), `generate_workout_analysis_rag` (942). |
| `15b6f0474f22dcc7af96db862971b39cb0539786:backend/coach_service.py` | Dernière version avant retrait de l'analyse legacy dans `968a604be519c39c2160ec2652818bbdbb9a9854`. `analyze_workout` (110) prépare résumé, splits, comparaison, forces/faiblesses ; enrichissement LLM (148), cache (158), repli déterministe. |
| Même commit, `backend/llm_coach.py` | `SYSTEM_PROMPT_SEANCE` (69–78) : réaction positive, analyse simple, point marquant, conseil pour la prochaine sortie, 4–5 phrases. `enrich_workout_analysis` (137–148) envoie le contexte au fournisseur existant. |
| Base C359, `backend/narrative_coach_v3.py` | Catalogue de faits typés (111–534), rendu déterministe (537), validation par indices/variantes exacts (564), appel optionnel (644). Ce n'est pas une rédaction libre : aucune nouvelle phrase n'est autorisée. |

Le RAG historique n'est pas un index vectoriel sourcé : récupération Python
de séances et sélection de conseils/templates avec `random.choice/sample`.
Le qualificatif « deterministic » de son en-tête n'est donc pas une garantie.
Ses dépendances directes sont la bibliothèque standard, les données d'activité
et `knowledge_base.json`. L'enrichissement ajoute `python-dotenv`,
`emergentintegrations.llm.chat`, la clé d'environnement existante et le modèle
configuré. Aucun de ces composants n'est réinstallé dans l'architecture produit.

### Base de connaissances et exclusions

À la base C359, `backend/knowledge_base.json` contient 19 catégories de conseils
en chaînes simples (190 conseils), sans auteur, publication, date de validation ni citation
scientifique par conseil. La provenance Git prouve l'existence d'un texte, pas
sa validité scientifique. **Aucun contenu de cette base n'est admis dans C359.**
Le fichier initial et celui de la base C359 ont le même SHA-256 :
`893cb8689955aa0dcce7772d521433c51c6bea7b481c3c72c98d65bb7c74dc1d`.

Exclusions concrètes dans le RAG historique :

- `rag_engine.py:492` : cadence manquante remplacée par 180.
- `:640`, `:1019`, `:1058` : cible universelle 170–180 pas/min.
- `:713` : tendance d'allure choisie aléatoirement.
- `:1025–1037`, `:1083–1084` : différence d'allure assimilée à une progression.
- `:1129` : « regular progression » comme texte prérempli.
- `:1167–1173` : conseil template pouvant devenir une prescription concurrente.
- Base de connaissances : « évacuer les toxines », ratio charge/récupération
  universel, règle des 10 %, cadence « optimale » : non réimportés.

### Fonctions encore utilisées à la base C359

- `coach_service.chat_response` → `llm_coach.enrich_chat_response` reste la
  chaîne de chat (`backend/coach_service.py:66–80`, `backend/server.py`).
- `llm_coach._call_gpt` reste le transport du chat et de Narrative V3 ;
  `_clean_response` tronque à 700 caractères (`backend/llm_coach.py:209–299`).
- `load_scoped_workout_intelligence_v3_with_narrative` est appelé par la route
  actuelle (`backend/server.py:2168`) et appelle **uniquement** Narrative V3.
- Le nom `retrieve_similar_workouts` existe dans V2, mais c'est une
  réimplémentation bornée actuelle, pas la remise en service de `rag_engine` :
  `backend/workout_analysis_v2.py:875,938,1067` et
  `backend/workout_analysis_v2_service.py:377`.
- `CoachLanguageV1` reste un contrat de conclusions typées consommé par V2
  et par la lecture versionnée de régularité de Narrative V3 ; ce n'est pas
  le LLM V1.
- `rag_engine.py`, `coach_service.analyze_workout`,
  `llm_coach.enrich_workout_analysis` et le prompt séance ont été supprimés.
  `chat_engine.py` et la base JSON subsistent, mais aucune importation runtime
  de `chat_engine` n'apparaît dans les modules backend non-tests à cette base.

### Comparaison et décision avant implémentation

V1 apporte un ton direct et une sélection de l'information, mais ses conseils,
ses comparaisons et ses déductions ne constituent pas des preuves. V3 lie au
contraire les phrases aux faits, incertitudes et limites des moteurs, au prix
d'une liberté rédactionnelle très faible.

Réutiliser **le style** (point utile d'abord, phrases courtes, pas de récitation),
le transport existant et les preuves typées V3. Ne restaurer ni le moteur RAG,
ni ses valeurs par défaut, ni ses prescriptions, ni ses conclusions
physiologiques. Une paraphrase libre ne peut pas être déclarée fiable par une
simple vérification des nombres ou une seconde opinion LLM. Le prototype
choisira donc une liberté **bornée et vérifiable**, avec repli pour toute
paraphrase dont l'équivalence ne peut être démontrée localement.

## 2. Architecture expérimentale

Un seul nouveau module produit : `backend/hybrid_coach_c359.py`. Il n'est
importé par aucune route, aucun loader ni aucune page. Aucun fichier produit
préexistant n'est modifié.

### Contrat

1. `generate_hybrid_coach` reçoit un `WorkoutIntelligenceV3` déjà calculé et
   limité au propriétaire, ainsi qu'un `UserAccess` résolu côté serveur.
   Ce n'est pas un endpoint et ce contrat ne doit jamais devenir un corps de
   requête autorisant lui-même l'accès.
2. FREE est refusé avant construction du contexte/appel fournisseur.
   TRIAL/PREMIUM passent par `UserAccess.can("coach_workout_analysis")`.
   `llm_access` est également requis avant tout appel LLM.
3. `C359_HYBRID_COACH_ENABLED` absent ou faux → résultat `disabled`, sans texte
   personnalisé ni appel fournisseur. Les tests ne changent cette variable
   que dans leur processus.
4. `HybridPermissions.history` et `.prescription` sont des restrictions
   supplémentaires **désactivées par défaut**, pas de nouvelles offres
   commerciales. Seul le booléen explicite `True` les ouvre dans l'appel
   interne de confiance. Pas de permission implicite par nom de séance,
   formule commerciale fournie par le navigateur ou message conversationnel.
5. Le catalogue vient du builder Narrative V3 actuel, puis d'une allowlist
   fermée. Toute nouvelle catégorie inconnue est exclue par défaut. Les
   dépendances indirectes sont filtrées : une sortie longue utilise
   l'historique même si son `decision_tier` est `personal_thresholds`. Son
   titre et son jugement de conformité sont donc masqués sans autorisation
   historique. Le V3 original n'est jamais modifié/recalculé.
6. Objectifs : le contrat de sortie V3 ne fournit pas d'objectif contextualisé
   et autorisé ; aucun objectif n'est inventé ni injecté depuis du texte libre.
   Prescription : seul le statut V3 autorisé est expliqué. Le seul conseil
   admis est la revue canonique d'un écart de type ; le conseil de confort
   générique de V3 n'est pas repris pour éviter une prescription concurrente.
7. Aucune connaissance RAG scientifique n'est chargée. Seuls le style
   conversationnel historique et le transport LLM existant sont réutilisés.

### Rédaction et contrôle factuel

Le LLM existant (`llm_coach._call_gpt`, modèle configuré par RunIndex) peut
réécrire **une phrase d'observation/interprétation**. Le prompt demande un JSON
compact avec l'indice de cette phrase et son texte rédigé, et fournit les
substitutions linguistiques admissibles FR/EN/ES. Par exemple, « Ta fréquence
cardiaque moyenne » peut devenir « Ta FC moyenne ». Contrairement au sélecteur
V3, le candidat est du texte, mais sa liberté reste volontairement bornée.

Le validateur reconstruit une grammaire à partir de la phrase autorisée :
substitutions exactes composables, tous les autres caractères littéraux.
Il ne vérifie pas seulement la présence des chiffres ou de références
existantes, n'utilise ni score de similarité ni juge LLM. Les nombres, signes,
unités, négations et réserves ne peuvent pas être remplacés librement. Une
phrase plausible extérieure à cette grammaire est rejetée. Les autres phrases
et leurs réserves obligatoires sont rendues localement. Le titre redondant
« type incertain » est supprimé quand l'explication porte déjà cette information.
Une classification non inconnue mais de confiance faible reste accompagnée
d'une réserve explicite.

Chaque phrase du résultat porte ses `evidence_refs` locaux. Le fournisseur ne
reçoit ni identifiant utilisateur/séance, date, chemin de preuve, conseil
arbitraire, historique brut ou texte libre issu du RAG. Les références ne sont
jamais acceptées du fournisseur. Les valeurs physiologiques viennent des faits
V3 ; aucun calcul de LT1/LT2, zone, progrès ou nouvelle prescription n'est ajouté.

Un seul appel, timeout externe de 8 s, aucune relance, aucun cache partagé,
aucune persistance. JSON dupliqué/invalide, unité/chiffre/confiance modifiés,
phrase non démontrable, erreur ou timeout → repli déterministe sur **le même
catalogue autorisé**, jamais sur le V3 complet non filtré. L'annulation du
demandeur se propage. Aucun contenu/exception fournisseur n'est journalisé ici.
Une seule phrase maintient la réponse sous la limite actuelle de nettoyage
de 700 caractères, sans changer le transport de production.

**Limite assumée : ce prototype n'est pas un générateur libre fiable.** Il
teste une liberté rédactionnelle limitée et auditable ; il ne prétend pas
avoir retrouvé toute la richesse conversationnelle V1 ni garantir une
équivalence sémantique générale. Une activation sur cette seule base ne serait
pas justifiée.

## 3. Tests et comparaison synthétique

### Protocole

Fixtures dans `backend/tests/test_hybrid_coach_c359.py:synthetic_case`.
Les deux textes partent de la même sortie du moteur déterministe V3.
Les seuils de laboratoire présents dans certaines fixtures sont **synthétiques** :
ils ne signifient pas que la production persiste ces données.

- Référence : `deterministic_fallback` de Narrative V3 actuel, flag C355 éteint.
- Hybride : flag C359 ouvert uniquement dans le processus de test ; historique
  et prescription explicitement autorisés pour cette comparaison à droits égaux.
- Le transport de test applique une substitution admissible au premier fait.
  Ce sont des **sorties de transport simulé validées**, pas des réponses
  réellement obtenues du modèle. Les tests couvrent aussi le nettoyage réel
  du transport partagé, via un fournisseur simulé.
- Aucun appel réseau LLM, MongoDB ou Garmin. Les tests de route préexistants
  emploient leurs doubles ; aucun cycle startup/synchronisation n'est lancé.
- Lecture qualitative ci-dessous : inspection des sorties, pas une notation
  humaine aveugle. Aucune supériorité conversationnelle n'est démontrée.

### Exactitude, pertinence, conseil et incertitudes — évalués séparément

| Cas | Exactitude factuelle V3 / hybride | Pertinence des observations | Utilité du conseil V3 / hybride | Incertitudes V3 / hybride |
| --- | --- | --- | --- | --- |
| Footing facile | Même position de FC moyenne sous LT1 synthétique ; pas de temps en zone déduit | Fait central conservé ; pas de nouveau fait | Pas de prescription exploitable : aucun conseil ajouté | « Probablement », comparaison historique insuffisante et limites de FC moyenne conservées |
| Sortie longue | Même type probable, dérivé de 100 min contre un historique habituel à 50 min | Le ratio n'est pas exposé dans le texte actuel : limite inchangée | Aucun conseil nouveau | Type probable et limites conservés ; type masqué si historique non autorisé |
| 4 × 4 min | Même décompte de 4 efforts / 3 récupérations | Le contrat V3 ne porte pas les durées individuelles : **ne pas affirmer 4 minutes dans la narration** | Pas de nouvelle allure/charge/récupération prescrite | Ne pas confondre régularité indisponible et irrégularité, dans les deux versions |
| Insuffisamment documentée | Aucun chiffre ni type inventé | Explication de l'abstention, pas une analyse physiologique | Pas de conseil personnalisé démontrable | Incertitude identique, redondance supprimée dans l'hybride |
| Tapis roulant | Aucune référence extérieure comparable utilisée dans cette fixture | Le V3 fourni ne porte pas un fait narratif spécifique « tapis » : aucune extrapolation ajoutée | Aucun conseil spécifique tapis inventé | Même prudence ; absence de comparaison valide conservée |
| Historique comparable | Même gain médian de 24 s/km, 6 observations sur 92 jours | Tendance V3 conservée, pas déduite par le LLM | Pas de prescription modifiée sur la base du gain | « amélioration probable, pas une preuve de gain de forme » conservé |
| Physiologie insuffisante | Aucun LT1/LT2 créé malgré une FC moyenne disponible | Abstention sur le type et la zone, comme V3 | Aucun conseil de zone/allure inventé | Absence de LT1 fiable explicite ; redondance supprimée |

### Lisibilité, naturel et répétitions

| Cas | Mots V3 / hybride¹ | Lecture qualitative et répétitions |
| --- | --- | --- |
| Footing facile | 58 / 57 | Abréviation FC plus directe ; pas de changement conversationnel substantiel |
| Sortie longue | 58 / 57 | Même constat ; contextualisation de la durée encore limitée |
| 4 × 4 min | 40 / 40 | Reformulation du constat Garmin ; réserve de régularité inchangée |
| Insuffisamment documentée | 61 / 53 | Une seule explication de l'incertitude au lieu du titre + explication |
| Tapis roulant | 58 / 57 | Pas de gain de pertinence spécifique au tapis |
| Historique comparable | 71 / 70 | Même phrase de tendance ; pas de répétition numérique supplémentaire |
| Physiologie insuffisante | 61 / 53 | Même déduplication de l'incertitude que pour la séance pauvre en données |

¹ Comptage mécanique par `split()`, pas un indicateur validé de qualité.
Le gain mesuré est surtout la déduplication déterministe et une reformulation
locale. La pertinence et l'utilité restent bornées par les preuves V3 ; il serait
incorrect d'attribuer ces écarts à une amélioration constatée du LLM.

### Coût et latence

30 répétitions locales par fixture, même processus Python 3.12.3, Pydantic
2.13.4. La construction scientifique V3 est exclue des deux chronométrages.
V3 mesure son rendu déterministe ; hybride mesure contexte, coroutine de
transport **simulé**, validation et rendu (son `elapsed_ms`, hors création
de la boucle de test). Pas un benchmark fournisseur ni un résultat production.

| Cas | Médiane locale V3 (ms) | Médiane locale hybride simulé (ms) | Latence LLM réelle | Coût LLM réel |
| --- | ---: | ---: | --- | --- |
| Footing facile | 0,025 | 0,147 | non mesurée | non mesuré |
| Sortie longue | 0,024 | 0,142 | non mesurée | non mesuré |
| 4 × 4 min | 0,020 | 0,133 | non mesurée | non mesuré |
| Insuffisamment documentée | 0,020 | 0,100 | non mesurée | non mesuré |
| Tapis roulant | 0,024 | 0,143 | non mesurée | non mesuré |
| Historique comparable | 0,031 | 0,151 | non mesurée | non mesuré |
| Physiologie insuffisante | 0,022 | 0,102 | non mesurée | non mesuré |

`cost=None` : aucun tarif/compteur de tokens fiable n'est renvoyé par le
transport actuel. `provider_duration_sec=None` pour ces simulations sans
métadonnée de durée. Les chemins désactivé/refusé ne simulent pas une latence
mesurée : `elapsed_ms=None`. L'exécution de cette évaluation n'a effectué aucun
appel fournisseur payant ; cela ne signifie pas que le coût futur est zéro.

### Exemples comparatifs anonymisés

Toutes les données sont synthétiques ; aucune identité ni séance réelle.

**Footing facile — V3 :**

> Probablement un footing facile. Ta fréquence cardiaque moyenne (140 bpm) se situe sous LT1, selon tes seuils personnels. Ton historique comparable ne permet pas encore de savoir avec confiance si tu progresses ou si tes performances baissent. Sans splits, la FC moyenne ne décrit pas le temps passé dans chaque zone. La conformité à la prescription reste indéterminée.

**Hybride simulé validé :**

> Probablement un footing facile. Ta FC moyenne (140 bpm) se situe sous LT1, selon tes seuils personnels. Ton historique comparable ne permet pas encore de savoir avec confiance si tu progresses ou si tes performances baissent. Sans splits, la FC moyenne ne décrit pas le temps passé dans chaque zone. La conformité à la prescription reste indéterminée.

**4 × 4 min — V3 :**

> Une séance fractionnée. Garmin a enregistré 4 phases d'effort et 3 phases de récupération. La comparaison disponible ne permet pas d'établir la régularité des répétitions ; cela ne signifie pas qu'elles étaient irrégulières. La conformité à la prescription reste indéterminée.

**Hybride simulé validé :**

> Une séance fractionnée. L'enregistrement Garmin montre 4 phases d'effort et 3 phases de récupération. La comparaison disponible ne permet pas d'établir la régularité des répétitions ; cela ne signifie pas qu'elles étaient irrégulières. La conformité à la prescription reste indéterminée.

**Séance insuffisamment documentée — V3 :**

> Type de séance incertain. Les données disponibles ne permettent pas d'identifier le type de séance de façon fiable. Ton historique comparable ne permet pas encore de savoir avec confiance si tu progresses ou si tes performances baissent. Sans splits ni LT1 fiable, les moyennes de séance ne permettent pas de confirmer une zone physiologique. La conformité à la prescription reste indéterminée.

**Hybride simulé validé :**

> Avec les données disponibles, le type de séance reste incertain. Ton historique comparable ne permet pas encore de savoir avec confiance si tu progresses ou si tes performances baissent. Sans splits ni LT1 fiable, les moyennes de séance ne permettent pas de confirmer une zone physiologique. La conformité à la prescription reste indéterminée.

**Historique comparable — V3 / hybride :**

Le début est respectivement « Ta fréquence cardiaque moyenne (140 bpm)… »
et « Ta FC moyenne (140 bpm)… ». La phrase spécifique est identique :

> Ton allure médiane est plus rapide de 24 s/km à fréquence cardiaque comparable sur 6 observations sur 92 jours : un signe encourageant d'amélioration probable, pas une preuve de gain de forme.

Les cas sortie longue et tapis reprennent le texte footing ci-dessus, avec
respectivement le titre « Probablement une sortie longue » et le titre footing.
Le cas sans physiologie reprend exactement le couple « séance insuffisamment
documentée ». Ces identités sont un résultat de la comparaison, pas des exemples
de personnalisation supplémentaire.

### Validation exécutée

Répertoire de travail des commandes :
`/home/runner/work/sauvegarde260708/sauvegarde260708/backend`.
Environnement de test isolé : `/tmp/c359-venv/bin/python` ; aucune modification
des dépendances du dépôt. Configuration pytest existante conservée
(`-n 2 --dist loadscope`).

| Vérification au head de code indiqué | Résultat |
| --- | --- |
| `python -m pytest tests/test_hybrid_coach_c359.py tests/test_narrative_coach_v3.py tests/test_workout_intelligence_v3.py -q --tb=short` | **390 réussis**, 7 avertissements préexistants de dépréciation |
| Même commande, plus `tests/test_workout_analysis_v2.py tests/test_coach_language.py tests/test_coach_workout_access_pr325.py` | **919 réussis, 3 échecs**, 14 avertissements |
| Base exacte extraite par `git archive 720fb5cd31faca5f9f6435bb0be4c7cbf0f3fcf6 backend`, puis `python -m pytest tests/test_workout_analysis_v2.py -k test_comparable_history_stays_separate_and_metrics_are_unchanged -q --tb=short` | Les **mêmes 3 échecs** en EN/FR/ES, sans code C359 |
| `python -m flake8 hybrid_coach_c359.py tests/test_hybrid_coach_c359.py --select E9,F63,F7,F82` | Réussi : contrôles de correction ciblés, pas une prétention de lint global |
| `git diff --check` | Réussi |
| Scanner de secrets sur chaque fichier modifié avant commit | Aucun secret détecté |
| CodeQL Python, deux passages dont le dernier après le head de code final | **0 alerte** |
| Revue automatisée incluse dans `parallel_validation` | **Indisponible** : modèle demandé absent du registre ; le statut global « Success » ne prouve pas son exécution |
| Revue indépendante read-only du diff et de la déduplication | Aucun problème significatif relevé |

Les 3 échecs existants sont à
`backend/tests/test_workout_analysis_v2.py:1838` :
`test_comparable_history_stays_separate_and_metrics_are_unchanged[en/fr/es]`
attend `meaning.consistent_pacing`, mais le moteur de base rend
`meaning.hr_without_intensity_with_pacing`. Aucun test ni moteur existant n'a
été modifié pour masquer cette divergence. La suite élargie n'est donc **pas
verte** ; la reproduction sur base distingue ce problème de C359.

Les premiers essais locaux ont nécessité de restaurer les dépendances de test
existantes (pytest, xdist, FastAPI/JWT, puis pytest-asyncio pour les anciennes
suites). Les résultats finaux ci-dessus sont ceux obtenus après restauration,
avec les versions centrales du dépôt (pytest 9.1.1, Pydantic 2.13.4,
flake8 7.3.0, python-dotenv 1.2.2).

Couverture nouvelle : sept fixtures, FREE/TRIAL/PREMIUM et flag, dépendances
indirectes historique/conformité, booléens stricts, références résolubles,
absence de mutation, unités/chiffres/signes/confiance/négations, LT1 inventé,
progrès/efficacité/récupération et prescriptions hallucinés, injection de texte
libre, nouvelles catégories inconnues, JSON malformé/dupliqué, exceptions,
timeout réel, annulation, absence de télémétrie et aucun branchement production.

## 4. Décision de livraison

PR **draft** uniquement. Flag désactivé par défaut. Attendre l'audit C359 avant
toute activation. Aucun déploiement, merge ou changement des écrans actuels.

Points non démontrés restant à l'audit : naturel réellement produit par le LLM,
taux de rejet en conditions réelles, pertinence/utilité jugées en aveugle, coût
et latence fournisseur, admission éventuelle de connaissances historiquement
sourcées. Le prototype n'autorise pas à déclarer ces critères satisfaits.

</details>

## C360 — Evidence-Grounded LLM Coach

### Portée et décision

Itération de la PR **#360** uniquement, branche existante
`copilot/c359-recovery`, base `copilot/dev`
(`720fb5cd31faca5f9f6435bb0be4c7cbf0f3fcf6`). HEAD du code C360 évalué :
`1ea72b1bd35698a1348947bb0e04a149fd7bfa48`. Cette référence désigne le code ;
le commit documentaire final est ultérieur. Flag `C359_HYBRID_COACH_ENABLED`
désactivé par défaut. Aucun branchement d'interface ou de route, aucun changement
V2/V3, accès Garmin/GCCLI, écriture MongoDB, séance réelle, déploiement ou merge.

**GO technique limité au contrat et aux contrôles testés ; GO produit : HOLD.**
Le texte libre simulé est accepté et les attaques testées sont rejetées, mais
aucune génération réelle n'a eu lieu : naturel, pertinence, taux de rejet, coût
et latence du modèle ne sont donc pas démontrés. Ce prototype ne doit pas être
activé en production sur cette preuve.

### Architecture avant / après

| Couche | Itération précédente de C360 | C360 — Evidence-Grounded LLM Coach |
| --- | --- | --- |
| Autorité scientifique | Workout Intelligence V3 | Workout Intelligence V3, inchangé : classification, intensité, répétitions, tendance, prescription, confiance |
| Entrée du LLM | Evidence Pack filtré | Evidence Pack filtré, sans assertion en prose ni provenance locale |
| Contrat de sortie | Plan d'IDs obligatoire puis rendu local | Prose originale libre dans la langue demandée |
| Contrôle | Validation stricte des IDs puis rendu contrôlé | Heuristiques format/longueur, valeurs/unités, catégories sensibles, réserves et contradictions ; repli déterministe en cas de doute |
| Autres Coachs | Transport existant, limite de nettoyage 700 caractères | Même comportement par défaut ; option C360 isolée à 2400 caractères et indicateur explicite de troncature |

`build_admissible_facts()` et les contrôles d'accès sont conservés. Le paquet
transmis au fournisseur ne contient que les faits admis, valeurs/unités,
conclusion autorisée, confiance, conditions d'usage et limites indispensables.
Les identifiants de séance, dates, chemins de source, assertions textuelles V3,
diagnostics libres et preuves non autorisées restent locaux. Les comparaisons
historiques, prescriptions et classifications dérivées de l'historique restent
conditionnées par les permissions explicites.

Le contrat final obligatoire de plan d'IDs, son parseur/validateur, les grammaires
de rendu local et les textes de clauses prédéfinis ont été supprimés. La sélection
déterministe conservée sert uniquement de fallback. Il n'y a ni second moteur
scientifique, ni RAG/connaissance externe, ni nouvelle dépendance.

### Prompt C360

Le prompt V1 historique `SYSTEM_PROMPT_SEANCE` (retrouvé dans l'audit C359)
privilégiait une réaction naturelle, un point concret, une explication simple,
un ton positif et un enseignement utile en quelques phrases. C360 en reprend
l'esprit sans restaurer ses heuristiques ou conseils non sourcés. La suggestion
historique de conseiller la prochaine sortie est volontairement exclue : une
prescription n'est permise que par l'autorité canonique.

Prompt système effectivement transmis :

> You are a running coach responding naturally to the workout described only by the authorized evidence pack in the user message. Write an original, useful analysis in the requested language; in French, address the runner as tu. React to a concrete session observation, explain why it matters simply, and use a positive but unforced tone. When evidence is rich, aim for 60–110 words; use fewer when it is limited. Use one natural paragraph unless another structure genuinely helps. Select and prioritize compatible facts yourself, and preserve the essential qualifications attached to them. Only V3-authorized facts and conclusions are scientific authority. Do not invent or recalculate values; infer no LT1/LT2 from average HR, repetition regularity, progression from one workout, fatigue causes, or a new prescription. A history-relative classification is not physiological intensity. Never claim a conclusion excluded by permissions. No RAG or outside knowledge. Return only the analysis prose, without headings, IDs, JSON, or a generic sign-off.

Le message utilisateur est uniquement le JSON de l'Evidence Pack (dont la langue).
Il ne comporte aucune donnée d'identité.

### Validation après génération et limites

La réponse est admise uniquement si elle est textuelle, non vide, comprise entre
8 et 150 mots et 2400 caractères, sans format structuré interdit. Les nombres
doivent apparaître dans les preuves admises ; les unités sont vérifiées contre
les unités associées, et les valeurs de FC moyenne ainsi que les positions
LT1/LT2 détectées sont comparées à V3. Les heuristiques refusent aussi les
conclusions physiologiques sans fait admis, une régularité non établie, une
tendance sans historique autorisé, une attribution causale et une prescription
inventées. Lorsque la formulation dépend d'un fait concerné, elles vérifient les
réserves obligatoires, dont l'incertitude, le caractère relatif à l'historique,
les limites des moyennes, l'absence de régularité, la prudence sur la tendance
et le maintien de la prescription.

Une réponse rejetée, tronquée, en erreur ou en timeout garde le fallback
déterministe construit à partir des seuls faits autorisés. Une durée fournisseur
n'est copiée que sur un appel réussi et les valeurs mesurées à zéro restent
valides. Les erreurs fournisseur de ce transport C360 sont journalisées sans
leur texte d'exception. `_call_gpt` conserve le nettoyage à 700 caractères pour
les appels existants ; C360 lui passe explicitement 2400 et vérifie
`response_truncated`. Le test adapte les deux chemins.

Ces contrôles sont des filtres heuristiques, **pas une validation sémantique**.
Ils ne peuvent pas reconnaître toutes les paraphrases, raisonnements trompeurs,
contradictions exprimées sans marqueur ni causalités déguisées ; des faits exacts
peuvent aussi être assemblés de façon incohérente. Le prompt et les tests
réduisent des risques identifiés, sans prouver toute la prose. Le modèle peut
encore produire une réponse générique, maladroite ou factuellement erronée non
couverte par les motifs détectés. Le fallback demeure nécessaire.

### Sept comparaisons synthétiques

Les sept fixtures sont synthétiques. Dans chaque ligne de preuves, `ID: valeurs
(unités), conclusion autorisée, confiance, conditions, limites obligatoires`
représente le paquet complet transmis au LLM. Le texte « proposé » est une
proposition **écrite dans le test et renvoyée par un transport simulé**, jamais
une sortie de modèle. `Accepté` reproduit exactement ce texte après contrôles.
La réserve « rejet » indique `aucun` pour ces sept propositions. Appréciations
qualitatives sont illustratives, non une évaluation aveugle du produit.

#### 1. Footing facile

- Evidence Pack : `session.kind`: `easy_run_probable`, conclusion `probable_session_type`, confiance moyenne, condition `v3_classification`, limite `probable_not_certain` ; `intensity.position`: FC moyenne 140 bpm, LT1 150 bpm, LT2 170 bpm, position `below_LT1`, conclusion `average_hr_threshold_position`, confiance moyenne, condition `reliable_v3_personal_thresholds`, limites `average_not_whole_effort`, `no_time_in_zones`, `no_physiological_cause`.
- Narrative V3 : « Probablement un footing facile. Ta fréquence cardiaque moyenne (140 bpm) se situe sous LT1, selon tes seuils personnels. Ton historique comparable ne permet pas encore de savoir avec confiance si tu progresses ou si tes performances baissent. Sans splits, la FC moyenne ne décrit pas le temps passé dans chaque zone. La conformité à la prescription reste indéterminée. »
- Proposition mock : « Tu as probablement fait un footing facile, d'après les critères disponibles. Ta FC moyenne de 140 bpm, sous LT1, va dans le même sens comme repère descriptif. Une moyenne ne décrit pas chaque moment de l'effort ni le temps passé dans les zones ; elle ne résume donc pas toute la sortie. La classification reste au conditionnel, et la FC ajoute un repère distinct sans décrire les variations d'un bout à l'autre. »
- Accepté : texte proposé, inchangé. Rejet : aucun.
- Évaluation : pertinence — relie type probable et moyenne observée ; naturel — lecture plausible du mock, non jugée sur génération ; fidélité — réserves et valeurs passent les heuristiques, sens global non prouvé.

#### 2. Sortie longue

- Evidence Pack : `session.long`: durée 100 min, habituelle 50 min, conclusion `probable_long_duration_comparison`, confiance moyenne, conditions `history_authorized` et `v3_classification`, limites `probable_not_certain` et `duration_not_effort` ; `intensity.position`: 140/150/170 bpm, `below_LT1`, conclusion `average_hr_threshold_position`, confiance moyenne, condition `reliable_v3_personal_thresholds`, limites `average_not_whole_effort`, `no_time_in_zones`, `no_physiological_cause`.
- Narrative V3 : « Probablement une sortie longue. Ta fréquence cardiaque moyenne (140 bpm) se situe sous LT1, selon tes seuils personnels. Ton historique comparable ne permet pas encore de savoir avec confiance si tu progresses ou si tes performances baissent. Sans splits, la FC moyenne ne décrit pas le temps passé dans chaque zone. La conformité à la prescription reste indéterminée. »
- Proposition mock : « Ta sortie a probablement été longue : 100 min, contre 50 min habituellement. Cet écart est le fait marquant par rapport à ton repère récent. Sa durée seule ne permet pas de déterminer l'intensité. Ta FC moyenne de 140 bpm se situe sous LT1, mais elle ne décrit pas tout l'effort ni le temps passé dans les zones. Cette comparaison situe la durée dans ton historique, sans prétendre décrire à elle seule tout le contenu de la sortie. »
- Accepté : texte proposé, inchangé. Rejet : aucun.
- Évaluation : pertinence — la comparaison temporelle est mise en avant ; naturel — synthèse du mock sans conseil ajouté ; fidélité — distinction durée/intensité et limites de FC conservées par les contrôles heuristiques.

#### 3. Séance fractionnée — 4 efforts / 3 récupérations

- Evidence Pack : `interval.count`: 4 efforts, 3 récupérations, conclusion `recorded_intervals_without_regularity`, confiance moyenne, condition `garmin_phases`, limites `no_repetition_durations` et `regularity_verdict_unavailable` ; `intensity.position`: 160/150/170 bpm, position `between_LT1_LT2`, conclusion `average_hr_threshold_position`, confiance moyenne, condition `reliable_v3_personal_thresholds`, limites `average_not_whole_effort`, `no_time_in_zones`, `no_physiological_cause`.
- Narrative V3 : « Une séance fractionnée. Garmin a enregistré 4 phases d'effort et 3 phases de récupération. La comparaison disponible ne permet pas d'établir la régularité des répétitions ; cela ne signifie pas qu'elles étaient irrégulières. La conformité à la prescription reste indéterminée. »
- Proposition mock : « Garmin a relevé 4 phases d'effort et 3 phases de récupération : la structure est le point marquant. Les durées de chaque répétition ne sont pas disponibles, donc leur régularité ne peut pas être jugée. Ta FC moyenne de 160 bpm se situe entre LT1 et LT2, mais elle ne décrit pas tout l'effort ni le temps passé dans les zones. On peut décrire l'organisation enregistrée, pas l'homogénéité des efforts. »
- Accepté : texte proposé, inchangé. Rejet : aucun.
- Évaluation : pertinence — pointe la structure réellement enregistrée ; naturel — prose plus directe dans le mock ; fidélité — aucune durée par répétition ni régularité n'est inventée, mais les heuristiques ne prouvent pas la cohérence sémantique totale.

#### 4. Données insuffisantes

- Evidence Pack : `session.unknown`: type `unknown`, `average_hr_available=0`, conclusion `session_type_unproven`, confiance nulle, condition `v3_classification`, limite `unknown_not_easy`.
- Narrative V3 : « Type de séance incertain. Les données disponibles ne permettent pas d'identifier le type de séance de façon fiable. Ton historique comparable ne permet pas encore de savoir avec confiance si tu progresses ou si tes performances baissent. Sans splits ni LT1 fiable, les moyennes de séance ne permettent pas de confirmer une zone physiologique. La conformité à la prescription reste indéterminée. »
- Proposition mock : « Le type de ta séance reste incertain avec les informations disponibles. Aucune FC moyenne n'est disponible pour compléter cette lecture, alors mieux vaut ne pas conclure sur l'intensité ou l'objectif de la sortie. »
- Accepté : texte proposé, inchangé. Rejet : aucun.
- Évaluation : pertinence — explique directement l'abstention et la FC manquante ; naturel — réponse courte, cohérente avec la preuve pauvre ; fidélité — ne transforme pas l'inconnu en séance facile.

#### 5. Tapis roulant

- Evidence Pack : identique au footing facile : `session.kind` probable, confiance moyenne, condition V3, réserve de probabilité ; FC moyenne 140 bpm sous LT1 150 bpm, seuil LT2 170 bpm, limites moyenne/temps en zones/causalité.
- Narrative V3 : même texte que le footing facile (voir cas 1). Le paquet filtré ne contient pas un fait narratif « tapis roulant », donc aucun texte ne le prétend.
- Proposition mock : même texte que le footing facile (voir cas 1).
- Accepté : texte proposé, inchangé. Rejet : aucun.
- Évaluation : pertinence — reprend ce que le paquet autorise, pas le contexte du tapis ; naturel — identique au cas 1 ; fidélité — aucune différence propre au tapis n'est inventée. Cette identité est une limite d'information, non une preuve de personnalisation.

#### 6. Historique comparable

- Evidence Pack : `session.kind`: footing probable, confiance moyenne, condition V3 ; `intensity.position`: FC moyenne 140 bpm, LT1 150, LT2 170, sous LT1 ; `trend.probable_improvement`: 6 observations, variation médiane −24 s/km, 92 jours, conclusion `qualified_historical_trend`, confiance moyenne, conditions `history_authorized`, `v3_trend_only`, `v3_sensitivity_agrees`, `v3_confirmed_variation`, limites `not_proof_of_fitness`, `no_cause`, `terrain_weather_not_controlled`.
- Narrative V3 : « Probablement un footing facile. Ta fréquence cardiaque moyenne (140 bpm) se situe sous LT1, selon tes seuils personnels. Ton allure médiane est plus rapide de 24 s/km à fréquence cardiaque comparable sur 6 observations sur 92 jours : un signe encourageant d'amélioration probable, pas une preuve de gain de forme. Sans splits, la FC moyenne ne décrit pas le temps passé dans chaque zone. La conformité à la prescription reste indéterminée. »
- Proposition mock : « Ton historique suggère une amélioration probable : 6 observations sur 92 jours montrent une variation médiane d'allure de -24 s/km. C'est un signal cohérent dans l'historique, pas une preuve de changement de forme à lui seul. La tendance mérite d'être lue comme telle, sans lui attribuer de cause : les effets du terrain et de la météo ne sont pas isolés. »
- Accepté : texte proposé, inchangé. Rejet : aucun.
- Évaluation : pertinence — donne la priorité à la tendance historique admise ; naturel — enseignement court, mais encore illustratif ; fidélité — chiffre, signe, période et réserve passent les contrôles, sans preuve sémantique complète.

#### 7. FC moyenne sans seuil physiologique fiable

- Evidence Pack : `intensity.hr`: FC moyenne 140 bpm, conclusion `descriptive_average_hr_only`, confiance nulle, condition `session_average_only`, limites `no_physiological_zone` et `average_not_whole_effort` ; `session.unknown`: type `unknown`, FC moyenne disponible, conclusion `session_type_unproven`, confiance nulle, condition V3.
- Narrative V3 : « Type de séance incertain. Les données disponibles ne permettent pas d'identifier le type de séance de façon fiable. Ton historique comparable ne permet pas encore de savoir avec confiance si tu progresses ou si tes performances baissent. Sans splits ni LT1 fiable, les moyennes de séance ne permettent pas de confirmer une zone physiologique. La conformité à la prescription reste indéterminée. »
- Proposition mock : « Ta FC moyenne enregistrée est de 140 bpm, mais le type de séance reste incertain avec les éléments dont on dispose. Cette moyenne est un repère descriptif, pas une intensité physiologique : elle ne suffit pas à établir une zone et ne décrit pas toute la séance. On peut rester sur ces observations sans deviner l'objectif ou la difficulté de la sortie. »
- Accepté : texte proposé, inchangé. Rejet : aucun.
- Évaluation : pertinence — exploite la seule mesure physiologique admise ; naturel — évite une classification inventée ; fidélité — la réserve sur l'absence de seuil est explicite et vérifiée par motif.

### Cas de reformulation et adversariaux

Les paraphrases acceptées FR/EN/ES expriment la même comparaison de FC moyenne,
la position sous LT1 et les réserves sur l'effort et le temps en zones sans
reprendre l'assertion locale à l'identique. Attaques synthétiques vérifiées :

| Proposition | Résultat |
| --- | --- |
| FC moyenne inventée à `999 bpm` | rejet `unsupported_numeric_value` |
| `LT2` affirmé sans preuve de seuil | rejet `unauthorized_physiological_conclusion` |
| zone d'entraînement numérique déduite d'une FC moyenne, même avec des seuils personnels | rejet `unsupported_physiological_zone` |
| `140 min` à la place d'une mesure bpm | rejet `unsupported_numeric_unit_or_value` |
| FC moyenne annoncée à 150 bpm alors que V3 vaut 140 | rejet `contradictory_average_hr` |
| moyenne 140 bpm dite au-dessus de LT2 alors que V3 dit sous LT1 | rejet `contradictory_threshold_position` |
| répétitions déclarées régulières | rejet `unsupported_regularity_claim` |
| progression affirmée sans tendance autorisée | rejet `unauthorized_trend_claim` |
| cause de FC attribuée à la fatigue | rejet `unauthorized_causality` |
| séance prescrite pour le lendemain | rejet `unauthorized_prescription` |
| réserve de régularité, de FC moyenne ou de tendance omise | rejet `missing_regularity_limit`, `missing_average_effort_limit` ou `missing_trend_limit` |
| tendance V3 probable rédigée comme une amélioration certaine | rejet `missing_trend_qualification` |
| tendance historique quand l'historique n'est pas autorisé | Evidence Pack vide de tendance, réponse rejetée |
| timeout, titre Markdown, réponse trop longue, fournisseur absent | fallback déterministe conservé |

Cette couverture cible les attaques connues et des paraphrases positives ; elle
ne constitue pas un benchmark exhaustif des formulations du modèle.

### Vérification du fournisseur, coût et latence

Le transport existant est le `llm_coach._call_gpt` utilisant Emergent LLM Key
et le modèle configuré. Son nettoyage historique à 700 caractères convient aux
messages existants, mais pas au prompt d'analyse libre. C360 emploie le même
transport explicitement à 2400 caractères ; la valeur par défaut des autres
Coach reste à 700, vérifiée par test. Une réponse tronquée est signalée par
l'adaptateur puis rejetée au lieu d'être traitée comme complète. Le chemin
absence de clé ne rapporte pas la durée placeholder de zéro ; un zéro réellement
mesuré sur une réponse réussie est conservé.

Le code du dépôt configure `gpt-4.1-mini` avec le fournisseur `openai` via
Emergent (`llm_coach.py`). Le timeout interne de cet adaptateur est 15 secondes ;
le timeout externe C360 est 8 secondes. La limite de 700 caractères est un
nettoyage local, pas une limite de capacité documentée du modèle. Aucun test
n'a vérifié la capacité réelle du fournisseur à produire 60–110 mots.

Aucun appel réel n'a été tenté : aucune clé n'a été utilisée, aucune séance ou
donnée personnelle transmise, et le transport de test est simulé. Les tests
simulés ne mesurent pas le modèle. **Coût fournisseur : non mesuré. Latence
fournisseur : non mesurée. Taux de réponses acceptées réelles et fréquence de
fallback réels : non mesurés.** La durée synthétique n'est pas publiée comme
latence ; les appels simulés sans métadonnée laissent `provider_duration_sec`
à `None`.

### Tests exécutés

Environnement Python de test isolé sous `/tmp/c360-validation-venv`, sans
modification de dépendances du dépôt. Commandes lancées depuis
`/home/runner/work/sauvegarde260708/sauvegarde260708/backend` :

| Vérification | Résultat |
| --- | --- |
| `PYTHONPATH=. /tmp/c360-validation-venv/bin/python -m pytest tests/test_hybrid_coach_c359.py -q -o addopts=''` | **49 réussis** |
| `PYTHONPATH=. /tmp/c360-validation-venv/bin/python -m pytest tests/test_hybrid_coach_c359.py tests/test_narrative_coach_v3.py tests/test_workout_intelligence_v3.py -q -o addopts=''` | **369 réussis**, 6 avertissements de dépréciation lors de l'import API |
| `python -m py_compile backend/hybrid_coach_c359.py backend/llm_coach.py backend/tests/test_hybrid_coach_c359.py` | réussi |
| `git diff --check` | réussi |

Le périmètre de tests synthétiques couvre le contrat libre, les sept fixtures,
paraphrases FR/EN/ES, les permissions, les attaques listées, les réserves,
le fallback, l'absence de mutation V3, l'absence de branchement production,
le logging sanitizé et les limites 700/2400 du transport simulé. Aucun vrai
fournisseur n'est invoqué.

### Risques résiduels et verdict

- Les vérifications en prose libre sont heuristiques et dépendantes de motifs ;
  elles ne prouvent pas la vérité sémantique et peuvent laisser passer une
  paraphrase trompeuse ou rejeter une formulation correcte.
- La qualité conversationnelle n'a pas été observée sur des réponses du modèle.
  Les sept propositions du tableau sont des textes de test fabriqués ; elles
  démontrent que le contrat autorise des paraphrases au lieu d'exiger une égalité
  littérale, pas que le modèle les produit ni qu'elles améliorent V3.
- Le fournisseur peut manquer, tronquer ou produire une réponse générique ;
  le fallback déterministe est conservé. Aucun gain produit n'est revendiqué.
- Les autorités scientifiques V3, calculs V2/V3, droits, routes, UI,
  persistance et activation restent inchangés ; flag OFF.

**GO technique : oui, pour l'essai isolé et les cas testés seulement. GO produit :
non démontré. Verdict global : HOLD** jusqu'à une évaluation de générations
réelles isolées, sans données personnelles/secrets, puis audit C360 demandé.
Le SHA du code validé est
`1ea72b1bd35698a1348947bb0e04a149fd7bfa48`; ce rapport sera ensuite livré dans
un commit documentaire. Aucun merge ni déploiement n'est effectué.
