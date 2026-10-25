# C372 — Réutilisation du verdict V2 dans le Coach hybride

## 1. Base canonique et dépendance

- Dépôt : `geirb56/sauvegarde260708` ; cible unique : `copilot/dev`.
- Base locale et HEAD canonique vérifié par `git ls-remote` :
  `8368f7e9f720c52db439848bc4ee8e1c5b15d77a`.
- GitHub confirme #367 / C371 mergée le 25 octobre 2026 à 08:44:33 UTC.
  La base est précisément ce merge ; aucune fusion effectuée par C372.
- L’audit et le choix B ont été commités **avant l’implémentation**, dans
  `01e541df4f5d514ccbe447776c20ab4285dec595`.
- Le HEAD testé et la vérification de sécurité seront consignés après commit ;
  le HEAD documentaire final sera fourni dans la PR, sans autoréférence.
- Racine des références ci-dessous :
  `/home/runner/work/sauvegarde260708/sauvegarde260708/`.

## 2. Audit de l’autorité réelle

Les implémentations V2, Narrative V3, Intelligence V3 (modèles, extraction,
service), hybride C359 et réalisation C365 ont été inspectées, ainsi que les
tests et rapports historiques C359–C371. Aucun fichier
`backend/workout_analysis_v2_models.py` : les modèles sont dans V2.

- `backend/workout_analysis_v2.py:1805-1849` fournit une disponibilité, un
  écart-type, une cohorte et une variation première/dernière. **Ce bloc ne
  contient pas de verdict catégoriel.** Deux allures suffisent à son
  écart-type ; cela n’autorise pas un jugement de série.
- Le verdict réel vient de `backend/coach_language.py:103-201,671-701`,
  appelé par le builder V2 et exposé dans `coach_language.conclusions`.
  Codes : `coach.repetitions.pacing` ou `coach.repetitions.pace_hr`.
  `kind=conclusion`, `category=repetitions`, `available=True`.
- Métadonnées : `judgment_version=v1`,
  `comparison_scope=all_comparable_efforts`,
  `metric=mean_absolute_deviation_from_median`,
  `comparability_basis=duration|distance`,
  `regularity_band=homogeneous|noticeable|variable`.
  Ce sont des catégories descriptives, pas des jugements bon/mauvais.
- Minimum : **trois** efforts pour une série. Deux efforts donnent
  `kind=descriptive`, `regularity_band=not_assessed`,
  `comparison_scope=two_efforts_only` : non admissible ici.
- V2 exige phases disponibles, ordre fiable, structure cohérente, mesures
  positives, cohorte couvrant tous les efforts et comparabilité de toutes les
  paires selon la base V2. Une simple cohorte autour d’un ancrage ne suffit pas.
  La tolérance de comparabilité et les seuils restent exclusivement dans V2.
- V2 s’abstient pour phases absentes, effectif insuffisant, ordre/structure
  incohérents, mesures invalides/imprécises, comparabilité insuffisante ou
  catégorie incertaine près d’une frontière. L’absence n’est jamais `variable`.
- La preuve numérique contient effectifs, médiane et écart absolu moyen, ainsi
  que les mesures individuelles. C372 ne transporte pas ces dernières au LLM.
- `backend/narrative_coach_v3.py:73-108,193-259` admet déjà cette conclusion
  versionnée, unique, avec effectifs concordants et preuve numérique finie.
  Il ne transforme ni confiance V3 ni écart-type en verdict.
- V3 copie les allures/durées individuelles C368/C369, mais ne publie que la
  disponibilité de régularité dans sa classification. Le loader construit
  déjà V2 puis V3 dans un même passage, avec lectures filtrées par utilisateur.
- L’hybride est un prototype hors routes, désactivé par défaut. Son catalogue
  est local ; le fournisseur ne choisit que des identifiants et formes.

## 3. Les trois échecs V2 connus

Inspection de `backend/tests/test_workout_analysis_v2.py:1800-1838` :
la fixture contient des splits kilométriques, des moyennes cardiaques et un
`consistency_score`, **aucune phase d’effort**. Le builder est appelé sans
`phases`. Les métriques et comparaisons sont vérifiées avant l’assertion finale.

`backend/workout_analysis_v2.py:1589-1614` sélectionne le code de présentation
`meaning.hr_without_intensity_with_pacing` lorsque la FC existe sans intensité
fiable. Le code attendu `meaning.consistent_pacing` est un ancien code de
présentation de pacing global ; il n’est ni `regularity_band`, ni une conclusion
`coach.repetitions.*`. Les trois langues partagent ce même chemin.

Ces échecs portent sur la sélection narrative legacy, pas sur le verdict de
répétitions réutilisé. Aucun seuil, algorithme ou test V2 ne sera modifié pour
les masquer. Plus précisément, `_advice_primary_code` ne retourne pas
`advice.maintain_consistency` : la correspondance legacy vers
`meaning.consistent_pacing` ne s’applique donc pas à cette fixture. C372 ne
réintroduit aucun seuil à partir du `consistency_score`.
La comparaison exécutée sur une archive de la base exacte confirme les trois
mêmes échecs. **La suite élargie n’est pas verte.**

## 4. Architectures comparées et décision préalable

| Option | Avantages | Coût / risque |
| --- | --- | --- |
| A — observation publique V3 | Exposition API future centralisée | Nouveau contrat et copies entrée/sortie ; risque de confondre disponibilité V3 et verdict V2 ; migration API/frontend sans besoin actuel |
| B — contexte V2 explicite séparé | Réutilisation du résultat déjà calculé et de l’admission Narrative ; preuve V2 conservée ; aucun champ public V3 | Appelant interne tenu d’utiliser le loader scopé ; future exposition API à décider explicitement |

**Choix B, avant implémentation.** Un contexte local lie le résultat V2 à
l’utilisateur du loader ; son identité de séance est vérifiée contre V3.
Un loader additif expose ce résultat du même passage, sans lecture ni calcul
supplémentaire ; les signatures/résultats publics existants restent compatibles.
L’admission catégorielle existante du Narrative est réutilisée, pas recopiée.
Des vérifications de disponibilité, provenance et cohérence des déclarations
encadrent ce transfert ; elles ne calculent pas la comparabilité ou la dispersion.

## 5. Contrat factuel prévu

`interval.regularity` n’existe que pour une conclusion admissible :
valeur exacte de `regularity_band`, source V2, disponibilité positive,
base de comparabilité et effectif déjà fournis. L’identité de séance et
l’utilisateur restent locaux, jamais envoyés au fournisseur.
Les références pointent vers la conclusion V2 réelle, ses métadonnées et sa
preuve ; les conditions et limites bornent le constat aux allures des efforts
comparables. Aucun texte arbitraire V2 n’est recopié.

Le transfert utilise `ScopedV2Evidence(user_id, analysis, source)` exclusivement
côté backend. La source doit être `workout_analysis_v2`, la version `v2`,
l’utilisateur celui de `UserAccess`, et l’identité V2 celle de V3.
L’admission réutilise `_approved_repetition_judgment` du Narrative, puis exige
la cohérence des déclarations V2 : phases Garmin disponibles, liste d’efforts
concordante, effectifs identiques à la classification V3, disponibilité de
régularité, comparaison complète, base identique aux métadonnées.
Ces contrôles ne relisent pas les allures pour établir une catégorie.
La confiance vaut `none` : V2 ne fournit pas de confiance scientifique chiffrée.

Le fait contient uniquement les valeurs `regularity_band`, `source`,
`status=available`, `efforts`, `comparability_basis`. Les chemins de preuve
pointent vers l’identité V2, les phases, le code, la disponibilité, le type de
conclusion, la version du jugement, la portée, la métrique, la catégorie,
la base et la preuve numérique déjà présente (effectifs, médiane, écart absolu).
Le LLM reçoit les valeurs/conditions/limites contrôlées, pas l’identité privée,
les chemins, le texte source ou les allures individuelles V2 de cette preuve.
Les deux bornes C371 peuvent rester dans leur propre catalogue descriptif,
mais ne participent jamais à un calcul de régularité.

Absence, indisponibilité, source/identité incohérente, verdict inconnu,
conclusion ambiguë ou preuve incohérente : omission du fait, sans verdict négatif.
Les faits C371 restent inchangés. Le fallback privilégiera le verdict lorsqu’il
existe, sans réciter comptage, première borne, dernière borne et couverture.
Le contrat reste une principale et au maximum deux soutiens.

Le fait legacy `interval.count` impose la limite « verdict indisponible ».
Il est donc omis **seulement quand le verdict V2 est admis**, pour ne pas envoyer
deux autorités contradictoires dans le même catalogue. Sa définition et le
catalogue sans V2 restent inchangés. La sélection interdit également cette
paire et limite à un seul soutien descriptif d’effort aux côtés du verdict.
Le fallback choisit le verdict, puis éventuellement prescription, première
borne ou observation FC/seuil, dans la limite de trois clauses indépendantes.
Il n’ajoute ni comparaison de bornes, ni causalité entre phrases.

## 6. Fichiers modifiés

- `backend/hybrid_coach_v2_c372.py` : liaison locale scopée et admission par
  réutilisation du lecteur catégoriel Narrative existant.
- `backend/workout_intelligence_v3_service.py` : wrapper interne additif
  `load_scoped_workout_intelligence_v3_with_v2` ; V2 et V3 du même passage.
  Les deux loaders publics préexistants conservent exactement leurs tuples
  à deux et trois éléments. Aucun accès supplémentaire au stockage.
- `backend/hybrid_coach_c359.py` : paramètre optionnel `v2_evidence`, fait
  fermé, références locales, préférence éditoriale et fallback.
- `backend/hybrid_coach_editorial_c365.py` : catégorie conclusion,
  non-redondance et réalisation fermée directe/explicative FR/EN/ES.
- `backend/tests/test_hybrid_coach_c372.py` : tests synthétiques et intégration.
- `docs/reports/C372_V2_REGULARITY_HYBRID.md` : présent rapport.

Ni V2, ni `coach_language`, ni Narrative, ni les modèles publics V3, ni les
algorithmes C368/C369, ni les tests existants ne sont modifiés. Aucune dépendance
du dépôt ajoutée/mise à jour. Routes, frontend, Training, abonnements et flag
par défaut inchangés.

## 7. Tests exécutés et CI

### Environnement et commande

Python 3.12.3, environnement isolé `/tmp/c372-venv` : pytest 9.1.1,
pytest-xdist 3.8.0, pytest-asyncio 1.4.0, Pydantic 2.13.4, FastAPI 0.110.1.
Les dépendances existantes ont été installées pour la validation ; les paquets
`emergentintegrations` et la wheel privée `litellm` sont inaccessibles et non
installés. Les suites offline demandées n’en ont pas eu besoin.

Depuis `/home/runner/work/sauvegarde260708/sauvegarde260708/backend`,
commande exécutée avec les options parallèles inchangées de `pytest.ini` :

```sh
PYTHONPATH=.:tests /tmp/c372-venv/bin/python -m pytest \
  tests/test_workout_analysis_v2.py \
  tests/test_workout_analysis_v2_facts.py \
  tests/test_workout_analysis_v2_phases.py \
  tests/test_workout_analysis_v2_unified.py \
  tests/test_coach_language.py \
  tests/test_coach_repetition_judgment.py \
  tests/test_narrative_coach_v3.py \
  tests/test_workout_intelligence_v3.py \
  tests/test_hybrid_coach_c359.py \
  tests/test_hybrid_coach_c362.py \
  tests/test_hybrid_coach_c364_audit.py \
  tests/test_hybrid_coach_c365.py \
  tests/test_hybrid_coach_c371.py \
  tests/test_hybrid_coach_c372.py -q --tb=short
```

Résultat : **1 831 réussites, 3 échecs, 14 avertissements**.
Les **71 nouveaux cas C372 réussissent**. Les trois seuls échecs sont les
variantes `[en]`, `[fr]`, `[es]` de
`test_comparable_history_stays_separate_and_metrics_are_unchanged`, à
l’assertion `meaning.code` décrite en section 3.

Même commande sans le nouveau fichier C372, depuis une archive indépendante
`git archive 8368f7e9f720c52db439848bc4ee8e1c5b15d77a backend` :
**1 760 réussites, les mêmes 3 échecs, 14 avertissements**.
Pas de régression supplémentaire constatée. Les tests C359–C365 comprennent
les anciennes fixtures C360/C361 ; pas de suite autonome C363 dans le périmètre.

Les 14 avertissements préexistants concernent `python_multipart`, `crypt`,
la configuration Pydantic class-based et les événements startup/shutdown
FastAPI ; ils sont dupliqués par les deux workers.
Contrôle fatal du linter existant :
`/tmp/c372-venv/bin/python -m flake8` sur les cinq fichiers Python modifiés,
avec `--select=E9,F63,F7,F82` : réussi. `git diff --check` : réussi.
Pas de lint stylistique global ni de build frontend, hors périmètre.

Itérations non finales conservées explicitement :
- premier passage C372 : 59 réussites / 3 erreurs d’import d’un helper de test
  inexistant ; le test utilise désormais le mock `UserAccess.can` existant
  dans le style C365 ;
- passage suivant élargi : 1 830 réussites / 4 échecs, dont les trois legacy
  et une fixture de comparabilité distance choisissant en réalité une cohorte
  par durée ; fixture corrigée, aucun algorithme V2 modifié.

### Couverture C372

Les cas passent par le **vrai builder V2**, pas seulement par un verdict forgé :
homogène, variations perceptibles et importantes, égalité des bornes avec
variations intérieures, minimum trois efforts, deux efforts descriptifs,
comparabilité par durée et distance, non-comparabilité et catégorie incertaine.
Les autres tests altèrent ensuite ces résultats réels pour vérifier l’abstention :
absence/indisponibilité, phases absentes, couverture partielle, métadonnées ou
preuves invalides, doublons, source/version/utilisateur/séance incohérents.

La disponibilité des allures C371 ne conditionne pas le verdict V2 ; les faits
C371 restent identiques avec et sans cette entrée supplémentaire.
Les tests couvrent sélection d’un ID absent, injection de valeurs ou
d’interprétations physiologiques, limites de sélection, FR/EN/ES, fallback sur
échec fournisseur ou absence de permission LLM, flag désactivé et refus d’accès.
Le snapshot admis reste immuable pendant l’attente du transport simulé.

L’intégration cache synthétique → loader scopé → **builder V2 espionné et
réellement exécuté une fois** → V3 → hybride vérifie le verdict `variable`,
l’absence de lectures supplémentaires, les mêmes résultats V3 et les filtres
utilisateur sur chaque requête. Un autre utilisateur reçoit `None`.
Les tests C372 bloquent les sockets et le transport par défaut ; aucun appel
Garmin/GCCLI, MongoDB production ou LLM réel.

### CI GitHub

`actions_list(list_workflow_runs)` a été consulté pour le dépôt et `copilot/dev`.
Les seuls runs retournés pour cette dernière branche sont historiques
(dernier `32418652111`, autre SHA) : ils ne certifient pas C372.
`get_job_logs(failed_only=True)` pour ce run et le run C371 `40176341382`
ne retourne aucun job échoué. Le run agent C372 `40178227563` est en cours,
pas une preuve d’exécution de ces suites par une CI de tests.
Le statut du HEAD livré sera revérifié avant ouverture de la PR.
Les contrôles GitHub non exécutés ne sont pas remplacés par un statut vert
historique.

## 8. Exemples FR / EN / ES

Réalisations backend testées, à partir de séances synthétiques analysées par V2 :

| Verdict V2 | FR | EN | ES |
| --- | --- | --- | --- |
| `homogeneous` | Les allures des répétitions comparables sont homogènes. | The comparable repetitions have homogeneous paces. | Los ritmos de las repeticiones comparables son homogéneos. |
| `noticeable` | Les répétitions comparables présentent des variations d’allure perceptibles. | The comparable repetitions show noticeable pace variations. | Las repeticiones comparables presentan variaciones de ritmo perceptibles. |
| `variable` | Les répétitions comparables présentent des variations d’allure importantes. | The comparable repetitions show large pace variations. | Las repeticiones comparables presentan variaciones de ritmo importantes. |

La forme explicative ajoute une limite fermée, par exemple :
« Ce verdict V2 décrit uniquement les allures, pas une stabilité physiologique. »
Les formes EN/ES portent la même limite. Le provider ne produit aucune prose.
En l’absence de verdict admissible, aucun de ces commentaires n’est autorisé.

## 9. Limites scientifiques

Constat descriptif des allures agrégées des répétitions comparables seulement.
Aucune stabilité physiologique, fatigue, progression, dégradation, causalité,
conformité ou prescription déduite. Pas de nouvelle formule, tolérance ou
seuil ; pas d’utilisation des bornes C371 pour produire ce verdict.
Les modèles et métadonnées ne sont pas une preuve cryptographique : le loader
scopé reste la frontière de confiance. Aucun appel Garmin/GCCLI, MongoDB
production ou LLM réel n’est autorisé pour cette validation.

## 10. Décision de livraison

**HOLD pour activation / production.** Objectif scientifique et intégration
offline C372 vérifiés ; aucun nouveau calcul ni échec supplémentaire.
La suite élargie reste rouge à cause des trois échecs legacy connus.
La qualité éditoriale d’un vrai LLM et une CI de tests du HEAD livré ne sont pas
certifiées par ces tests synthétiques. Les réserves produit C365 restent valides.

Une seule PR vers `copilot/dev`, pour revue. Aucun merge, déploiement,
changement de frontend, remplacement du Narrative ou activation du flag.
Arrêt après livraison du rapport.
