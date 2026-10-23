# C365 — Coach hybride : autorité scientifique et édition séparées

## Audit préalable, avant modification applicative

Base : `copilot/dev`, `e12f543f89d6cf9e64b4b581430512d96ac7724a`.
Branche de livraison : `copilot/c365-architecture-coach-hybride`.
Le HEAD final de livraison est donné dans la PR et le message final (pas
d’autoréférence au commit contenant ce rapport). Date : 2026-10-23.

Vérifications en lecture seule :

- `git ls-remote origin refs/heads/copilot/dev` = HEAD local ci-dessus.
- GitHub confirme #362 mergée le 2026-10-23 à 14:43:56Z, merge
  `e12f543f89d6cf9e64b4b581430512d96ac7724a`, head
  `0b38edfbfd0e058dc2f19a5bd1d7b6f145a25fab`, ancêtre du HEAD.
- Rapport C364 lu intégralement. Ses observations C363 (21 générations,
  9 acceptations, 4 erreurs) ne sont ni reproduites ni une garantie statistique.
- Contrats inspectés : `backend/workout_intelligence_v3_models.py:183-335` ;
  calculs inspectés : `backend/workout_intelligence_v3.py:621-740,803-870,877-1025`.
- Adaptateur inspecté : `backend/hybrid_coach_c359.py:161-467,474-972`
  **à la base auditée**. FC moyenne ≠ intensité de chaque instant ; phases
  Garmin ≠ durées ou régularité ; comparaison courant/moyenne ≠ tendance
  entre médianes de périodes ; prescription = type, jamais nouvelle consigne.
- Admissions : comptages entiers finis ; durées positives ; classification
  probable et incertitude conservées ; seuils V3 fiables, ordonnés et cohérents ;
  comparaisons fortes, cohorte propre avec ≥2 références ; tendances de confiance
  medium/high et sensibilité concordante, signes cohérents. V3 reste l’autorité :
  l’adaptateur n’est pas un second moteur physiologique.
- Permissions : `UserAccess.can("coach_workout_analysis")`, puis `llm_access` ;
  historique et prescription uniquement si permission explicitement `True`.
  Le filtre `history or not history_classification` est correct ; aucune raison
  de l’inverser. Les permissions sont fournies par l’appelant, pas authentifiées
  par ce prototype isolé.
- Fallback : sélection locale de faits et assertions locales avec preuves.
  Pas de causalité entre phrases ; omission de supports redondants. Faiblesse
  éditoriale : moyenne cardiaque non retenue en support des phases et priorité
  d’un type dérivé devant l’observation directe.
- Flag `C359_HYBRID_COACH_ENABLED` absent = désactivé. Prototype non branché
  aux routes. Transport existant `_call_gpt`, identité `anonymous`, contexte
  `c359_hybrid`, 8 s, 2 400 caractères, erreurs assainies et troncature signalée.
  Modèle configuré : `gpt-4.1-mini`. Aucun appel réel effectué.
- Ancien chemin : prompt de prose libre → heuristiques lexicales → affichage
  du texte brut et suppression des claims. Une valeur numérique autorisée ne
  garantit pas son rôle, sa portée, sa référence ni sa conclusion.
- Les 32 cas C364 et leurs **18 xfail** ont été inspectés : 15 acceptations
  dangereuses (6 régularité/comptage, 3 portée FC, 3 bénéfices, 3 comparaison)
  et 3 faux rejets (arrondi, négation, appellation du seuil).
- Première exécution avant édition : **467 passed, 18 xfailed, 1 failed**
  (dépendance existante `email-validator` absente lors de l’import API).
  Aucun échec applicatif hybride constaté dans ce passage.

## Comparaison des architectures

| Architecture | Sécurité | Rédaction / personnalisation | Maintenance / i18n | Coût / latence | Risque robotique |
| --- | --- | --- | --- | --- | --- |
| 1. Clauses typées, réalisation backend | Domaine fini auditable, valeurs et relations non fournies par le LLM | Ordre, sélection, omission, formes explicatives ; liberté linguistique bornée | Contrat et réalisateurs localisés à maintenir | Un appel court, rendu local | Réel, à mesurer |
| 2. Composition déterministe, édition LLM | Même garantie si transitions fermées et toutes assertions réalisées localement | Bonne organisation, pas de prose libre ; transitions libres interdiraient la garantie | Proche de 1, moins explicite sans clauses typées | Un appel | Réel |
| 3. Prose libre et vérification formelle | Aucun vérificateur fiable disponible pour toute assertion, négation, modalité et portée | Liberté maximale | Sémantique générale non résolue dans ce périmètre | Vérification additionnelle indéterminée | Faible mais erreurs scientifiques |

**Choix : 1 avec composition neutre de 2.** Le LLM est éditeur, pas auteur
des propositions scientifiques finales. Il choisit des clauses typées et
leurs formes autorisées, leur ordre et les omissions. Le backend résout chaque
clause vers un fait autorisé et réalise les valeurs et relations. Seul un espace
sépare les phrases : aucune transition libre, causale, évaluative ou prescriptive.
Les relations internes (moyenne/seuil, durée/usuel, comparaison/cohorte,
tendance/périodes) sont celles déjà admises par V3.

Il s’agit d’une **réalisation déterministe pilotée par le LLM**, pas de prose
libre certifiée, ni d’une simple sélection d’IDs suivie de rédaction arbitraire.
Ce compromis abandonne volontairement la liberté de paraphrase illimitée :
le gain hybride recherché est l’édition contextuelle, pas une nouvelle science.
Sa valeur et son naturel nécessitent encore un essai réel autorisé.

## Réalisation, tests et limites

Résultats finaux et protocole complétés après implémentation et validation.
