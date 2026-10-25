# C372 — Réutilisation du verdict V2 dans le Coach hybride

## 1. Base canonique et dépendance

- Dépôt : `geirb56/sauvegarde260708` ; cible unique : `copilot/dev`.
- Base locale et HEAD canonique vérifié par `git ls-remote` :
  `8368f7e9f720c52db439848bc4ee8e1c5b15d77a`.
- GitHub confirme #367 / C371 mergée le 25 octobre 2026 à 08:44:33 UTC.
  La base est précisément ce merge ; aucune fusion effectuée par C372.
- Ce document est commencé **avant l’implémentation**. Les résultats de
  validation et le HEAD testé seront complétés après exécution.
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
les masquer. Les résultats effectivement exécutés seront consignés ci-dessous ;
la suite élargie ne sera pas annoncée verte si ces échecs persistent.

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

Absence, indisponibilité, source/identité incohérente, verdict inconnu,
conclusion ambiguë ou preuve incohérente : omission du fait, sans verdict négatif.
Les faits C371 restent inchangés. Le fallback privilégiera le verdict lorsqu’il
existe, sans réciter comptage, première borne, dernière borne et couverture.
Le contrat reste une principale et au maximum deux soutiens.

## 6. Fichiers modifiés

À compléter après implémentation.

## 7. Tests exécutés et CI

À compléter après exécution ; aucun résultat n’est présumé.

## 8. Exemples FR / EN / ES

À compléter à partir des réalisations effectivement testées.

## 9. Limites scientifiques

Constat descriptif des allures agrégées des répétitions comparables seulement.
Aucune stabilité physiologique, fatigue, progression, dégradation, causalité,
conformité ou prescription déduite. Pas de nouvelle formule, tolérance ou
seuil ; pas d’utilisation des bornes C371 pour produire ce verdict.
Les modèles et métadonnées ne sont pas une preuve cryptographique : le loader
scopé reste la frontière de confiance. Aucun appel Garmin/GCCLI, MongoDB
production ou LLM réel n’est autorisé pour cette validation.

## 10. Décision de livraison

En cours. Aucun merge, déploiement, changement de frontend ou activation.
