# C364 — Audit de sécurité scientifique du Coach hybride — STOP

## Décision et périmètre de livraison

**STOP : sécurisation fonctionnelle non réalisée.** Cette PR livre l'audit et
des spécifications adversariales, pas un Coach hybride déclaré sûr.
La validation existante laisse passer des conclusions hors autorité V3.
Aucun validateur de correspondance sémantique fiable entre chaque affirmation
de prose libre et une conclusion V3 n'a été identifié dans l'architecture
inspectée. Ajouter une sélection d'IDs ne résout pas cette dernière étape.

La clause STOP de C364 est donc appliquée, plutôt que d'ajouter une nouvelle
liste de regex ou de réintroduire Narrative V3 sous un autre nom.
Ce constat porte sur les mécanismes disponibles et le périmètre autorisé ;
ce n'est pas une démonstration d'impossibilité de toute recherche future.

- Base canonique et HEAD audité : `copilot/dev`,
  `6abbd1b63c664a62bd31b11a4d9dedb7878bc5f3`.
- Branche de livraison : `copilot/c364-secure-hybrid-coach-architecture`.
- Date de vérification : 2026-10-23.
- HEAD du code applicatif testé : identique à cette base ; aucun fichier
  applicatif n'est modifié.
- HEAD commité des spécifications et du rapport revus et retestés :
  `08d1a46e85df047993d6cace1f30428593b803e8`.
  Le commit suivant complète uniquement les références et résultats de revue
  de ce rapport ; son HEAD de livraison est consigné dans la PR et le message
  final, sans référence circulaire au commit qui contient ce texte.
- Aucun appel réel au LLM ; aucune requête Garmin ou MongoDB ; aucune donnée
  utilisateur réelle. Les contrôles utilisent uniquement les fixtures synthétiques.
- Aucun changement V3, Training V2, routes, interface, abonnements, dépendances
  déclarées, secrets, transport fournisseur ou valeur par défaut du flag.
- Aucun merge, activation ou déploiement.

## 1. Audit préalable en lecture seule

Cette section consigne les observations effectuées **avant toute édition**.
Les références ci-dessous portent sur les fichiers de la base exacte indiquée
ci-dessus, sous `/home/runner/work/sauvegarde260708/sauvegarde260708/`.
Les rapports historiques ne sont pas utilisés comme autorité sur le code courant.
L'audit a été commité avant l'ajout des tests C364 :
`e451fcd2d4cad6e8254246cd95286e4b8a3f0e1c`.

### 1.1 HEAD et intégration C360 / C361 / C362

`git rev-parse HEAD` et `git ls-remote origin refs/heads/copilot/dev` ont
retourné le même SHA : `6abbd1b63c664a62bd31b11a4d9dedb7878bc5f3`.
L'historique initialement superficiel a été approfondi en lecture seule.

| Élément | Preuve effective |
| --- | --- |
| Recovery C359/C360 | PR GitHub **#360**, mergée le 2026-10-22 ; head `55b33d2df573b651ce364804988ce1586dc670b0`, merge `0132fb031accc35cea59c08f785c0ae5ee400ab9` |
| C362 | PR GitHub **#361** (numéro de PR, **pas** nom d'itération), mergée le 2026-10-23 ; head `c8112f43c4c73ba48c3650cfdde29142e55df659`, merge `6abbd1b63c664a62bd31b11a4d9dedb7878bc5f3` |
| Ascendance | Les deux heads ci-dessus sont ancêtres du HEAD audité (`git merge-base --is-ancestor`) |
| C361 expérimental | Aucun merge autonome C361 identifié dans l'historique inspecté ni dans la recherche GitHub C361 ; ne pas inventer une PR ou assimiler son nom à **#361** |
| Expériences C361 / C363 | Chiffres rapportés par le propriétaire, pas réexécutés : C361 cité dans le rapport C362 ; C363 fourni dans l'énoncé. Les 21 réponses brutes C363 ne sont pas disponibles dans les artefacts suivis inspectés |

Les résultats C363 (9 acceptations, 12 fallbacks, 4 erreurs parmi les textes
acceptés, dont 2 irrégularités inventées) restent des observations fournies,
pas des mesures reproduites dans cette PR.

### 1.2 Contrats réels V3 : faits et conclusions

| Contrat | Autorité disponible et limites |
| --- | --- |
| `WIV3IntensityAssessment` | Position de la **FC moyenne** (`hr_metric=session_average_hr`), seuils retenus avec provenance/confiance, limitations ; pas de stabilité cardiaque ni de temps en zone. `backend/workout_intelligence_v3_models.py:183-199` |
| `WIV3SessionClassification` | Type énuméré, niveau de décision, confiance, preuves numériques, règles et limitations. Les labels easy/steady/tempo/long sont **probables**. `backend/workout_intelligence_v3_models.py:234-248` |
| Fractionné | La classification réutilise les phases Garmin. La disponibilité de régularité module confiance/limitation, mais la sortie ne contient pas de verdict catégoriel régulier/irrégulier ni de durées de répétition. `backend/workout_intelligence_v3.py:621-652`, `backend/workout_intelligence_v3_models.py:234-248` |
| Comparaison ponctuelle | Deux cohortes distinctes : allure à FC comparable et FC à allure comparable ; effectifs, IDs des références, tolérances, moyennes et différences. `backend/workout_intelligence_v3_models.py:251-284` |
| Sens des différences | Courant moins moyenne des références : allure négative = plus rapide ; FC négative = plus basse. Calculs et arrondis existants : `backend/workout_intelligence_v3.py:833-847`. Ce n'est pas une comparaison médiane entre périodes |
| Tendance | Statut probable/stable/possible/insuffisant, confiance, observations, médianes entre périodes, sensibilité et limitations. Une variation ponctuelle n'est pas une tendance ni une preuve de forme. `backend/workout_intelligence_v3_models.py:293-307` |
| Prescription | Correspondance du **type** à un snapshot historique autorisé ; pas conformité de toute la séance ni nouvelle prescription. `backend/workout_intelligence_v3.py:980-1025` |
| Coach V3 | `WIV3CoachItem` contient `code: str`, `text: str`, preuves numériques et chemins ; pas une ontologie typée de toutes les propositions de langue naturelle. `backend/workout_intelligence_v3_models.py:323-335` |

**Limitation de contrat :** V3 distingue bien plusieurs observations et
conclusions métier par ses blocs structurés. Il ne fournit ni une représentation
formelle de chaque assertion de prose, ni un vérificateur d'implication de
phrases arbitraires. Les `allowed_conclusion` de l'adaptateur sont des noms
locaux résumant ces blocs, pas une nouvelle autorité scientifique V3.
On peut vérifier les valeurs/conditions de l'admission ; on ne peut pas déduire
de cette admission que toute paraphrase produite est autorisée.

### 1.3 Inventaire complet des admissions dans l'Evidence Pack

Source : `backend/hybrid_coach_c359.py:161-416`.
Chaque fait expose valeurs, unités, significations, confiance, conclusion
autorisée, conditions, interdictions et priorité (`:73-97`).
Les textes locaux, chemins et IDs privés ne sont pas envoyés (`:419-435`).

| ID | Conclusion autorisée | Conditions principales et frontière |
| --- | --- | --- |
| `interval.count` | `recorded_intervals_without_regularity` | Type intervals autorisé ; comptages entiers finis, efforts ≥2, récupérations ≥1. Comptage de phases uniquement, jamais durée ou régularité |
| `session.long` | `probable_long_duration_comparison` | Classification accessible, permission historique, durées positives disponibles dans les preuves V3 ; probable, durée ≠ effort |
| `session.kind` | `probable_session_type` | easy/steady/tempo probable ; permission historique si classification issue de l'historique ; confiance faible et caractère relatif conservés |
| `intensity.position` | `average_hr_threshold_position` | FC finie, LT1/LT2 positifs et ordonnés, sources admises, confiance medium/high, cohérence avec position V3 ; moyenne seulement |
| `intensity.hr` | `descriptive_average_hr_only` | FC finie mais position/seuils non admissibles ; aucune zone physiologique |
| `session.unknown` | `session_type_unproven` | Classification unknown accessible ; disponibilité/valeur éventuelle de FC, jamais unknown → easy |
| `comparison.pace` | `observed_pace_difference_at_comparable_hr` | Historique autorisé, comparaison available/strong, pas de structure inconnue, différence finie et ≥2 références de cette cohorte |
| `comparison.hr` | `observed_hr_difference_at_comparable_pace` | Mêmes conditions, mais cohorte et unité propres ; pas de bénéfice ni cause |
| `trend.probable_improvement`, `trend.stable`, `trend.possible_decline` | `qualified_historical_trend` | Historique autorisé, confiance medium/high, sensibilité concordante, variation confirmée pour les directions, effectif/span positifs, signe cohérent ; pas preuve de changement de forme |
| `prescription.review` | `review_training_prescription` | Permission prescription, classification accessible, statut consistent/deviation ; type seulement, Training demeure autorité prescriptive |

`VALIDATED_KNOWLEDGE` est vide ; son interface de provenance est réservée au
futur, sans chargeur ni API d'admission (`:61-70`). Aucune connaissance
physiologique générale supplémentaire n'est autorisée.

### 1.4 Génération → validation → acceptation → fallback

Source : `backend/hybrid_coach_c359.py:884-972`.

1. Vérifier `UserAccess` et `coach_workout_analysis`, sinon `denied`.
2. Vérifier `C359_HYBRID_COACH_ENABLED`, absent/désactivé par défaut, sinon
   `disabled` sans appel fournisseur (`:891-894`).
3. Construire les faits admissibles et le fallback local avec ses `HybridClaim`
   (`:895-902`, `:438-467`).
4. Sans faits ou sans `llm_access`, retourner le fallback (`:905-908`).
5. Envoyer le paquet et un prompt de prose libre, un seul appel avec timeout
   de 8 s et limite de 2 400 caractères ; transport existant inchangé
   (`:909-942`, `:875-881`).
6. Sur succès non tronqué, reconstruire les faits et appeler
   `validate_generated_narrative` (`:946-956`).
7. Si les heuristiques passent, remplacer le texte par la prose brute et
   **vider `claims`**, passer à `generated_narrative`, scope
   `heuristic_risk_checks` (`:957-963`). Aucune correspondance assertion/preuve
   n'est construite ni vérifiée.
8. Sinon, garder la synthèse déterministe ; timeout/exception/troncature
   conservent également le fallback, sans exposer le texte rejeté.

Le LLM peut introduire une interprétation à l'étape 5, même sans ajouter de
nombre. L'étape 7 accepte l'absence d'un motif connu, pas la présence d'une
preuve pour chaque affirmation. Le résultat reste `verdict=HOLD` avec le
blocker `heuristic_checks_are_not_semantic_proof` (`:111-122`) : cette
transparence est utile mais ne neutralise pas une assertion fausse affichée.

### 1.5 Protections lexicales et limites observées

Source : `backend/hybrid_coach_c359.py:474-872`.

- Nombres en chiffres comparés à un ensemble **global** de valeurs autorisées ;
  contrôle d'unités et de certains rôles via motifs spécifiques (`:674-765`).
  Les nombres en lettres échappent à ce parcours ; l'égalité numérique ne
  prouve ni la cohorte, ni le rôle, ni le sens de la phrase.
- Bénéfices, causes, prescriptions, régularité, généralisation de FC et
  classifications : motifs finis (`:488-605`, `:766-871`). Une paraphrase
  inconnue ne devient pas sûre parce qu'aucun motif ne la reconnaît.
- Négation : recherche dans les 90 caractères précédents, avec découpage
  lexical de phrases (`:606-614`, `:684-689`), pas analyse de portée.
  « ne permettent pas » n'est pas « ne permet pas ».
- Identité des seuils : `LT1` ne fait pas émerger le chiffre 1 du motif numérique,
  mais « seuil lactique 1 » le fait ; rejet d'une appellation correcte.
- Les arrondis ne bénéficient d'aucune tolérance sémantique : une valeur
  raisonnablement arrondie peut être rejetée, tandis qu'une valeur exacte
  peut être attribuée à la mauvaise conclusion.
- `required_limits` n'est pas une preuve de respect effectif de toutes les
  limites dans la prose ; certaines sont uniquement transmises au fournisseur.

### 1.6 Permissions, flag et isolation

`_authorized` exige une instance `UserAccess` et
`access.can("coach_workout_analysis")` (`:132-133`).
Les droits `llm_access` / `coach_workout_analysis` sont Premium/Trial dans
`backend/access_control.py:84-97,187-205`. Historique et prescription sont
désactivés par défaut et admis uniquement si leur permission vaut exactement
`True` (`backend/hybrid_coach_c359.py:55-58,177-182,402-408`).
L'adaptateur reçoit ces permissions de son appelant ; il ne résout pas lui-même
une identité ni un consentement. Les filtres de prose ne garantissent pas
l'absence d'une paraphrase d'une conclusion non autorisée.

La recherche des références Python trouve l'import du prototype uniquement
dans ses tests, pas dans les routes/services de production.
Le flag absent reste désactivé ; cette PR ne le modifie pas. Cela ne constitue
pas une inspection des variables d'un environnement déployé.

## 2. Options comparées et décision architecturale

| Option | Gain démontrable | Limite / décision |
| --- | --- | --- |
| Ajouter les expressions C363 aux regex | Rejet de quelques phrases connues | Pas de couverture des assertions ; explicitement insuffisant, rejeté |
| A : sélectionner des IDs, puis B : rédiger librement | Existence, permissions, conditions, cohérence structurelle et sous-ensemble sélectionné vérifiables | B peut ajouter n'importe quelle proposition non couverte ; les IDs et citations déclarés par le même LLM ne prouvent pas la prose. Non implémenté comme fausse garantie |
| Prose structurée en phrases + IDs/citations | Meilleure localisation pour un audit humain | Omission de propositions dans les annotations, mauvaise portée ou faux rattachement toujours possibles ; pas de certificateur disponible |
| Grammaire fermée / variantes approuvées / phrases préécrites | Correspondance mécanique possible dans le vocabulaire borné | Compromet la liberté rédactionnelle exigée ; retour à Narrative V3, rejeté |
| LLM sélectionneur + assertion déterministe, transitions libres | Traçabilité des assertions copiées | Les transitions peuvent elles-mêmes introduire cause/bénéfice ; si elles sont fermées également, retour au cas précédent |
| Juge LLM ou nouveau moteur physiologique | Non évalué | Hors périmètre et n'apporterait pas à lui seul une preuve formelle |
| Forcer tous les textes libres en fallback / supprimer la génération | Évite d'exposer cette prose non certifiée | Neutralise la fonction hybride, sans résoudre B ; ne pas présenter ce changement comme une solution préservant la liberté |
| **Audit + STOP** | Rend le blocage et ses contre-exemples vérifiables | **Retenu conformément à la clause STOP ; aucun durcissement applicatif livré** |

Une architecture A/B ne serait admissible qu'avec une validation finale
indépendante des annotations du générateur : identifier **toutes** les
propositions, lier sujet/mesure/unité/cohorte/période, quantificateurs temporels,
modalité et négation, puis démontrer leur couverture par des conclusions V3
autorisées. Le code actuel ne sait pas le faire. Aucun nouveau bénéfice,
jugement de régularité ou savoir physiologique ne doit être créé pour combler
ce manque.

En cas d'incertitude, le comportement souhaité est le fallback déterministe.
**Ce n'est pas une garantie ajoutée par cette PR** : les chemins d'acceptation
C362 restent inchangés et contournables lorsque le flag expérimental est actif.
Ne pas considérer C364 comme prêt pour activation ou déploiement.

## 3. Validation et spécifications adversariales

Avant édition, les quatre suites existantes ont donné **454 passed**,
7 avertissements de dépréciation, après restauration des dépendances de test
existantes sans changement de manifeste. La première tentative donnait
453 passed / 1 failed (import `motor` absent), pas une régression applicative.

Les sondes synthétiques en lecture seule ont notamment accepté :
« Sans régularité dans leur durée », « Les intervalles manquent de régularité »,
« Ta fréquence cardiaque est restée stable », « Tu as limité ta fatigue »,
et un faux comptage écrit en lettres. Elles ont rejeté la négation correcte
« Ces données ne permettent pas de conclure à une progression ».

### 3.1 Spécifications exécutables A–E

Fichier ajouté :
`backend/tests/test_hybrid_coach_c364_audit.py`.
Les 32 cas vérifient à la fois le validateur direct et le chemin complet avec
transport injecté, flag actif, permissions explicites et fixtures V3 existantes.
Pour les rejets conformes, le texte et les claims du fallback sont comparés
à la synthèse déterministe existante. Aucun test préexistant n'est modifié.

Les lacunes connues sont marquées **`xfail(strict=True, raises=AssertionError)`** :
ce sont des exigences **non satisfaites**, pas des cas corrigés ou ignorés.
Un futur succès inattendu rendra le test rouge et imposera de réexaminer son
marqueur. `--runxfail` réexécute les mêmes assertions sans suppression.

| Groupe | Cas conformes à la spécification | Lacunes non corrigées |
| --- | --- | --- |
| A — Régularité / comptages / paraphrase inédite | 4 | 6 |
| B — FC moyenne / portée temporelle | 2 | 3 |
| C — Bénéfices et paraphrase inédite | 3 | 3 |
| D — Comparaisons / unités / signe / références / forme | 4 | 4 |
| E — Négation et identité du seuil | 0 | 2 |
| Prescription ajoutée sans autorité | 1 | 0 |
| **Total** | **14** | **18** |

Les 18 lacunes sont **15 acceptations indues** et **3 faux rejets** :

| ID du test | Observation actuelle, non résultat souhaité |
| --- | --- |
| `regularity-without` | « Sans régularité dans leur durée. » accepté |
| `regularity-lacking` | « Les intervalles manquent de régularité. » accepté |
| `regularity-stable-intensity` | « Les intervalles ont une intensité stable. » accepté |
| `regularity-no-strict-structure` | « Sans structure stricte des intervalles. » accepté |
| `invented-count-words` | Cinq efforts / deux récupérations acceptés pour quatre / trois |
| `unseen-regularity-paraphrase` | « Chaque effort reproduit exactement le précédent. » accepté |
| `hr-stability` | « Ta fréquence cardiaque est restée stable. » accepté |
| `hr-low-throughout` | Intensité faible pendant toute la sortie acceptée |
| `hr-entire-session-paraphrase` | Ensemble de la séance sous LT1 accepté |
| `benefit-conditional` | Bénéfice conditionnel pour l'endurance accepté |
| `benefit-fatigue` | Fatigue limitée acceptée |
| `unseen-benefit-paraphrase` | Organisme renforcé accepté |
| `comparison-direction` | « plus lent » avec un écart V3 d'allure négatif accepté |
| `comparison-wrong-reference` | Écart courant/moyenne de −14,4 s/km attribué aux médianes entre périodes accepté |
| `comparison-wrong-observation-count` | Cinq observations empruntées au nombre de références, au lieu des six de la tendance, acceptées |
| `comparison-reasonable-rounding` | −14 s/km pour −14,4 s/km rejeté : égalité numérique exacte exigée |
| `negated-progression` | Négation correcte « ne permettent pas de conclure à une progression » rejetée |
| `threshold-label-not-measurement` | « seuil lactique 1 » pris pour une valeur numérique non autorisée |

La fixture historique conserve exactement les résultats de V3 :
`comparison.pace = −14,4 s/km / 5 références`,
`comparison.hr = 0 bpm / 2 références`,
`trend = −24 s/km / 6 observations / 92 jours`.
Aucun calcul scientifique alternatif n'est ajouté.
Les descriptions factuelles demandées (quatre/trois phases et FC moyenne
140 bpm sous LT1 150 bpm) restent acceptées sans réserve automatique.

### 3.2 Commandes et résultats

Depuis `/home/runner/work/sauvegarde260708/sauvegarde260708/backend` :

```sh
python -m pytest tests/test_hybrid_coach_c364_audit.py -q -rx
python -m pytest tests/test_hybrid_coach_c359.py tests/test_hybrid_coach_c362.py tests/test_hybrid_coach_c364_audit.py tests/test_workout_intelligence_v3.py tests/test_narrative_coach_v3.py -q
python -m pytest tests/test_hybrid_coach_c364_audit.py --runxfail --tb=no -q
python -m flake8 tests/test_hybrid_coach_c364_audit.py --select=E9,F63,F7,F82
```

- Nouvelle spécification : **14 passed, 18 xfailed**.
- Ensemble ciblé : **468 passed, 18 xfailed, 7 avertissements préexistants**.
  Les 454 tests existants restent verts ; les xfails ne sont pas inclus dans
  les réussites. Ce résultat ne satisfait **pas** la sécurité C364.
- Contre-vérification sans marqueurs : **18 failed, 14 passed**, sortie pytest
  **1 attendue** ; les 15 textes dangereux atteignent réellement
  `generated_narrative`, les trois descriptions correctes partent en fallback.
- Flake8, sélection existante d'erreurs Python : aucune erreur.
- `git diff --check` depuis
  `/home/runner/work/sauvegarde260708/sauvegarde260708` : aucune erreur.
- Imports de dépendances existantes restaurés dans l'environnement seulement ;
  aucun nouveau framework, manifeste ou lockfile.
- Aucun appel de service réel. Le test API existant utilise ses doublures,
  sans démarrage de l'application ni requête MongoDB/Garmin.
- Scan de secrets avant chaque commit des fichiers livrés : aucun secret
  détecté.
- `parallel_validation` exécuté après commit :
  **revue automatique indisponible** (modèle absent du registre), malgré le
  libellé global « Success » ; ne pas interpréter l'absence de commentaires
  comme une revue accomplie. **CodeQL non exécuté**, car diff uniquement
  documentaire et tests, déclaré trivial selon les critères de l'outil.
- Revue indépendante du diff en lecture seule : aucun problème significatif
  signalé. Elle n'a modifié aucun fichier ni exécuté de tests. Ces revues ne
  certifient pas l'architecture de prose libre.

Aucune réussite produit réelle n'est revendiquée.

## 4. Risques résiduels et garanties

- **Non résolu :** textes libres dangereux encore acceptés, chiffres en lettres,
  direction/référence/cohorte incorrecte malgré des valeurs admises, négations
  et arrondis corrects rejetés, absence de traçabilité claim-by-claim.
- **Garanti par le diff :** aucun changement de comportement applicatif,
  calcul scientifique, fallback, permissions ou flag ; aucun contournement
  lexical prétendument universel.
- **Constaté par les tests existants :** les scénarios couverts de permissions,
  flag désactivé, fallback et nombres inventés restent conformes à leurs
  assertions. Cela ne garantit pas toutes les formulations possibles.
- Le fallback expose des assertions locales reliées aux faits sélectionnés,
  pas une validation de prose LLM ; il dépend toujours de la correction V3
  et de l'adaptateur. Aucun audit ne le transforme en nouvelle autorité.
- Les observations C363 ne sont pas des générations reproduites ici.
  Les tests simulés ne mesurent ni pertinence, ni style, ni qualité réelle.

## 5. Protocole futur Emergent — proposé, non exécuté

1. Attendre l'audit propriétaire et une décision sur le blocage de B avant
   toute nouvelle expérimentation ; ne pas activer de route ou de flag global.
2. Obtenir une autorisation explicite des appels, du budget et du protocole.
   Fixer base/HEAD effectifs, modèle et paramètres, permissions, versions et
   fixtures synthétiques ; ne pas extrapoler des paramètres manquants C363.
3. Reprendre les sept fixtures existantes et les cas adversariaux A–E,
   sans Garmin, MongoDB ou profils réels ; budget à décider par le propriétaire,
   aucun retry implicite ni seuil de réussite produit fixé.
4. Conserver, dans l'environnement expérimental autorisé seulement, les paquets
   et sélections éventuelles, textes bruts, sorties retenues, modes, motifs,
   checks, statut fournisseur, latences et coûts réellement disponibles.
   Une valeur absente reste absente, jamais zéro inventé.
5. Auditer humainement **chaque** affirmation des réponses acceptées et rejetées :
   extrait exact, conclusion V3, preuves, unités, rôles, signe, références,
   portée temporelle, incertitude, négation et éventuelles causes/prescriptions.
   Une citation d'ID ne vaut pas validation de ce lien.
6. Séparer transport, fidélité scientifique, faux rejets, pertinence, naturel
   et concision ; comparer aux artefacts C363 uniquement s'ils sont fournis.
   Toute assertion sans couverture démontrée est non validée et doit rester
   hors affichage validé ; l'audit humain expérimental n'est pas un juge
   automatique intégré ni une preuve générale.
7. Rapporter les résultats sans masquer les fallbacks ou les inconnues.
   Revenir au propriétaire ; aucun merge, activation ou déploiement automatique.
