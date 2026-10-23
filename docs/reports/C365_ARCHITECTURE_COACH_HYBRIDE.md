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

## Contrat et mécanisme livré

`backend/hybrid_coach_editorial_c365.py` définit une sélection avec une clause
principale, zéro à deux supports et une intention éditoriale. Chaque clause ne
contient qu’un ID de fait et une forme autorisée. Le schéma est envoyé au
fournisseur avec les faits, valeurs/unités, catégories, permissions additionnelles,
conclusions admissibles, limites et formes disponibles. La provenance précise
reste locale dans `AdmissibleFact.source_paths` puis `HybridClaim.evidence_refs` ;
ni chemins arbitraires, textes V3, dates ni identifiants privés ne partent au LLM.
L’accès global `coach_workout_analysis` est vérifié avant tout fait.

Le backend rejette les champs supplémentaires à tous les niveaux, types coercibles,
IDs inconnus/non autorisés/dupliqués, formes incompatibles, intention incompatible,
sélection vide, supports redondants et clés JSON dupliquées. Aucun champ texte
scientifique, valeur ou transition n’est accepté. La réalisation revalide aussi
les sélections locales ; l’éditeur ne transmet jamais ses propres nombres.

Formes : directe, explicative, appellation complète des seuils, comptages en
lettres (français, domaine 0–10), comparaison approximativement arrondie et
limite de portée d’une moyenne. L’arrondi est **explicitement approximatif**,
ne peut transformer un petit écart en zéro et ne change jamais le signe. Les
autres formes conservent la précision admise, y compris près d’un seuil.
La portée « cette moyenne ne permet pas de conclure à une progression » porte
sur la moyenne seule, pas sur l’existence éventuelle d’une tendance V3.

Les comparaisons conservent leur unité, effectif de cohorte et convention
courant moins moyenne des références ; les tendances conservent médianes entre
périodes, effectif propre, durée, qualification et limite de forme physiologique.
Le constat de prescription reste limité au type. Aucune nouvelle relation
entre faits distincts n’est inférée.

`generate_hybrid_coach` conserve un snapshot immuable des faits admis avant
l’attente fournisseur. Un succès devient `editorial_realization`, avec les claims
conservés et `verification_scope=closed_realization`. Le texte est exclusivement
la concaténation des réalisations locales, jamais la réponse fournisseur.
`verdict=HOLD` reste explicite : ce prototype n’est pas validé comme produit.

Le fallback reste déterministe et traçable. Sa sélection préfère désormais
l’observation FC/seuil au type qui en est dérivé, et peut juxtaposer la FC moyenne
aux comptages Garmin **sans expliquer les répétitions par cette moyenne**.
Timeout, exception, troncature, refus fournisseur, réponse malformée ou sélection
invalide conservent atomiquement ce fallback, sans texte rejeté ni erreur privée.
Coût et latence fournisseur absents restent `None` ; une durée mesurée nulle
reste zéro. Flag et transport par défaut inchangés.

### Quatre niveaux distincts

1. **Validité des données** : relève de V3 et de ses entrées ; l’adaptateur contrôle
   notamment finitude, comptages, seuils et conditions d’admission. Un objet JSON
   bien formé n’est pas une preuve de provenance réelle.
2. **Validité des conclusions** : autorité V3 et admission conditionnée par droits,
   confiance et limites ; aucun calcul physiologique nouveau.
3. **Fidélité de formulation** : réalisateurs locaux finis et composition neutre,
   valeurs et relations non modifiables par le LLM ; chaque claim garde son ID,
   sa conclusion et ses chemins de preuve.
4. **Pertinence éditoriale** : sélection/ordre/omission par le LLM ; seule la
   cohérence structurelle est testée ici. Pas de preuve que le modèle réel
   choisit toujours le fait le plus intéressant.

## Vérification des défauts C364

Les **32 textes adversariaux originaux sont conservés** dans
`backend/tests/test_hybrid_coach_c364_audit.py`, sans xfail.

- Les 15 acceptations dangereuses ne peuvent plus être affichées comme prose
  fournisseur : aucune voie de réalisation de régularité, stabilité FC, bénéfice,
  mauvaise direction, référence/période ou effectif inventé n’existe.
- Les autres attaques (prescription, nombre, unité, signe, intensité globale)
  sont également exclues au même contrat, sans nouvelle regex.
- Les contenus factuels admissibles passent séparément par des clauses typées :
  comptages en chiffres/lettres, moyenne sous seuil, comparaison exacte/arrondie,
  appellation « seuil lactique 1 » et négation de progression issue d’une moyenne.
- Les trois faux rejets ne sont **pas** déclarés corrigés pour la prose libre.
  Cette entrée n’existe plus. Leur sens admissible dispose d’une réalisation
  contrôlée, sans confusion entre chiffre d’appellation et mesure, ni portée
  approximative de négation. L’arrondi est signalé, pas assimilé à une valeur exacte.
- `validate_generated_narrative` est conservé uniquement comme **diagnostic
  historique C362 non sûr**, pour les régressions lexicales anciennes. Il n’est
  plus appelé par la génération ; un test le remplace par une fonction qui
  échoue si elle est appelée. Ses défauts sémantiques ne sont pas réparés.

Les xfail ne sont donc ni masqués ni comptés comme succès scientifiques :
les mêmes attaques sont rejouées sur une architecture qui supprime l’entrée
de prose arbitraire, avec un test positif distinct des significations admises.

## Tests et résultats

Base exacte : `e12f543f89d6cf9e64b4b581430512d96ac7724a`.
HEAD applicatif testé : `0ecc3edd5b2965c21712e8da49edfb045b461946`.
Les commits suivants ajoutent les tests C365 et complètent ce rapport ;
le HEAD final exact et les tests réexécutés sont consignés dans la PR.

Depuis `/home/runner/work/sauvegarde260708/sauvegarde260708/backend` :

```sh
python -m pytest tests/test_hybrid_coach_c359.py tests/test_hybrid_coach_c362.py tests/test_hybrid_coach_c364_audit.py tests/test_hybrid_coach_c365.py tests/test_workout_intelligence_v3.py tests/test_narrative_coach_v3.py -q
python -m flake8 hybrid_coach_c359.py hybrid_coach_editorial_c365.py tests/test_hybrid_coach_c359.py tests/test_hybrid_coach_c362.py tests/test_hybrid_coach_c364_audit.py tests/test_hybrid_coach_c365.py --select=E9,F63,F7,F82
```

Passage intégré final : **564 passed, 7 avertissements préexistants, zéro
xfail**. Flake8 (sélection d’erreurs Python existante) et `git diff --check` :
aucune erreur. Les 32 cas C364 passent, y compris les 18 anciens xfail migrés.
Les dépendances de test existantes ont été restaurées dans l’environnement
uniquement ; pas de changement de manifeste ni nouvel outil. Des tentatives
intermédiaires ont échoué sur les imports absents `email-validator`, puis `redis`,
avant leur restauration. Aucun changement de test API pour contourner ces imports.

Les tests C365 couvrent structures strictes, champs/IDs/formes/intention,
duplication de clés, redondances, toutes formes admises sur sept fixtures et trois
langues, permutations/sous-ensembles jusqu’à trois clauses dans la fixture riche,
signes/unités/effectifs distincts, zéro ≠ absent, précision près des seuils,
approximations, ordre/omissions, permissions, flag, absence d’accès/faits,
timeout effectif avec annulation, exception, troncature et snapshot d’autorité.
Ce sont des tests déterministes, pas une mesure du comportement d’un véritable LLM.
Une revue indépendante du diff en lecture seule n’a signalé aucun problème
significatif ; elle ne certifie pas une garantie absolue de vérité scientifique.

### Sorties synthétiques constatées (sélecteur simulé)

| Fixture | Fait principal choisi par la doublure | Réalisation représentative |
| --- | --- | --- |
| easy | intensity.position | Ta FC moyenne est de 140 bpm, sous ton LT1 de 150 bpm. |
| long | session.long | Ta sortie est probablement longue : 100 min, contre 50 min habituellement. Puis observation distincte de FC moyenne sous LT1. |
| intervals_4x4 | interval.count | Garmin a enregistré 4 phases d’effort et 3 phases de récupération. Puis FC **moyenne** de 160 bpm entre LT1 et LT2. |
| sparse | session.unknown | Le type de ta séance reste incertain ; aucune FC moyenne n’est disponible. |
| treadmill | intensity.position | Ta FC moyenne est de 140 bpm, sous ton LT1 de 150 bpm. |
| comparable_history | trend.probable_improvement | Amélioration **probable**, 6 observations / 92 jours / variation médiane −24 s/km, pas une preuve de changement de forme. |
| no_physiology | intensity.hr | Ta FC moyenne enregistrée est de 140 bpm ; elle ne suffit pas à établir une zone physiologique. |

Les « puis » de ce tableau décrivent le test, pas une transition générée.
Ce choix simulé est défendable par les preuves ; il n’atteste pas la qualité
du choix qu’effectuera `gpt-4.1-mini`.

## Limites et risques résiduels

- La garantie est **structurelle et conditionnelle** à la correction de V3,
  de l’admission des faits et des réalisateurs audités, pas une garantie absolue
  sur la vérité des données de capteur ou de leur provenance.
- La pertinence, le naturel et la valeur ajoutée réelle ne sont **pas validés**.
  Risque de répétition stylistique et de narration encore trop rigide ; les
  formes bornées peuvent donner moins de diversité qu’une prose libre.
- Le LLM peut omettre une observation importante ou choisir un fait banal,
  tout en restant scientifiquement fidèle ; aucun taux d’acceptation cible.
- Une seule lecture historique par sélection est autorisée pour limiter
  les redites. Ce filtre conservateur peut omettre deux observations réellement
  complémentaires. Aucune prétention de résolution générale du discours.
- Comptages en lettres limités au français 0–10 ; replis chiffrés ailleurs.
  Les nouvelles langues/formes nécessiteront leur propre revue de fidélité.
- L’ancien diagnostic lexical reste non sûr et ne doit jamais redevenir
  un chemin d’admission. Le prototype demeure isolé, sans authentification
  autonome des permissions transmises par un futur appelant.
- Aucun changement V3, Training V2, prescription, route, UI, abonnement,
  ingestion Garmin/MongoDB, activation du flag ou déploiement.
- Aucun appel réel au LLM, aucune donnée personnelle ni métrique fabriquée.

## Protocole proposé pour gpt-4.1-mini — non exécuté

1. Attendre l’autorisation explicite du propriétaire : budget, nombre de
   générations, paramètres et environnement. Fixer base/HEAD, versions et modèle
   réellement utilisés ; ne pas déduire les paramètres manquants des essais C363.
2. Reprendre uniquement les sept fixtures synthétiques, permissions explicites
   et contrat C365 ; pas de Garmin, MongoDB, profil réel ni activation de route.
   L’ancien lot C363 n’est comparable que si ses réponses brutes sont fournies.
3. Un appel de sélection par génération, pas de second juge LLM, pas de retry
   silencieux. Conserver paquet, JSON brut, décision de validation, mode,
   claims/texte réalisé ou fallback, motif et données de transport réellement
   disponibles. Coût/latence absents restent absents.
4. Vérifier automatiquement la traçabilité finale, nombres, signes, unités,
   cohortes, modalités et permissions. Réexécuter les attaques C364 et injections
   structurelles ; distinguer échec de transport et refus de contrat.
5. Évaluation humaine séparée et comparative avec le fallback : fait principal
   défendable, intérêt des supports, omissions, répétitions, fluidité, rigidité,
   limites réellement utiles, valeur supérieure à une liste de métriques.
   Rapporter exemples exacts et désaccords ; aucun pourcentage arbitraire exigé.
6. Séparer les cinq axes : sécurité structurelle, exactitude des valeurs,
   pertinence, naturel et valeur ajoutée. Les résultats des trois derniers axes
   ne sont pas déductibles de JSON valides ou de doublures déterministes.
7. Toute assertion hors autorité impose STOP et analyse du réalisateur/admission,
   pas une nouvelle regex ni une extension opportuniste de V3. Revenir au
   propriétaire après le rapport ; aucun merge ou déploiement automatique.
