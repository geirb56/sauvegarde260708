# C358 — Workout Analysis V3 Consistency & Loading UX

> **Reprise autorisée le 22 octobre 2026.** Les sections 1 à 10 conservent
> l'audit initial et son HOLD historique ; elles ne décrivent pas l'état de
> livraison après reprise. Voir les sections 11 et suivantes pour les
> corrections, validations et le verdict actualisé.

## 1. Périmètre, base et HEAD

Date : 22 octobre 2026. **Verdict : HOLD. Rapport d'audit uniquement.**

Après l'arrêt préalable, l'utilisateur a autorisé la création de ce rapport et
d'une PR en brouillon, **sans modification du code**. Ce document n'annonce pas
l'implémentation de C358.

- Base : `copilot/dev`, `bdb67314b3bb16ae166dc1e91f3ba11039d9b616`.
- HEAD de code audité : `bdb67314b3bb16ae166dc1e91f3ba11039d9b616`.
- Branche de livraison : `copilot/c358-workout-analysis-v3-ux`.
- C356 : PR #356 confirmée mergée dans `copilot/dev`, merge
  `6a96b4ab4f049a92070e56f5e0687978700bbaf7`.
- C357 : PR #357 confirmée mergée dans `copilot/dev`, merge
  `bdb67314b3bb16ae166dc1e91f3ba11039d9b616`.
- Le fetch de `copilot/dev` confirme que le HEAD audité est canonique.
- Arbre de travail propre avant création du rapport ; aucune modification
  préexistante à préserver.

Le SHA du commit documentaire de livraison est communiqué dans la PR et le
message final, distinctement du HEAD de code audité ci-dessus. Il ne peut pas
être inscrit dans son propre contenu avant sa création.

## 2. Provenance des deux dispersions

Les chemins cités sont relatifs à la racine du dépôt ; les numéros de ligne
désignent le HEAD de code audité.

| Propriété | Coach narratif : 6,6 s/km | Preuves : 7,7 s/km |
| --- | --- | --- |
| Calcul source | `backend/coach_language.py:103-170`, `_repetition_judgment` | `backend/workout_analysis_v2.py:1805-1838`, `_effort_regularity` |
| Champ V2 source | `coach_language.conclusions[i].evidence.absolute_deviation_sec_per_km` | `phase_analysis.effort_regularity.pace_dispersion_sec_per_km` |
| Définition | Moyenne des écarts absolus à la médiane des allures | Écart-type population des allures autour de leur moyenne |
| Formule | `D = somme(abs(p_i - médiane(p))) / n` | `sigma = racine(somme((p_i - moyenne(p))²) / n)` |
| Unité | Secondes par kilomètre | Secondes par kilomètre |
| Consommation | `backend/narrative_coach_v3.py:73-108,241-259` réutilise les preuves du jugement canonique | `frontend/src/components/workout/NarrativeWorkoutAnalysis.jsx:29-30,60-67` lit le contrat V2 |
| Arrondi d'affichage | `format_narrative_number`, une décimale maximum, virgule FR/ES, point EN (`backend/narrative_coach_v3.py:62-70`) | `formatAnalysisNumber`, précision 1, appelée par le composant de preuves |

Le premier calcul n'est **pas** la médiane des écarts absolus : il s'agit de
leur **moyenne**, avec une médiane comme centre. Aucun des deux calculs ne
pondère les répétitions par leur distance.

### Reconstruction numérique démontrée, non validation Garmin réelle

La fixture `reference_phases` de
`backend/tests/test_workout_analysis_v2_unified.py:23-35` fournit quatre efforts
de 240 secondes, aux distances respectives de 832,07 ; 851,11 ; 885,81 ;
825,41 mètres. Elle inclut également des récupérations, exclues des deux
populations d'effort.

Les allures calculées par `240 × 1000 / distance_m` sont :

| Effort | Allure (s/km) |
| --- | --- |
| 1 | 288,43727090268845 |
| 2 | 281,9847023298986 |
| 3 | 270,93846310156806 |
| 4 | 290,76458971904873 |

- Population identique : quatre efforts, comparables par durée.
- Médiane : **285,21098661629355 s/km**.
- Écart absolu moyen à la médiane : **6,569673797567631 s/km**, affiché **6,6**.
- Écart-type population : **7,687007906315586 s/km**, affiché **7,7**.
- Le test existant vérifie déjà l'écart-type voisin de 7,6870
  (`backend/tests/test_workout_analysis_v2_unified.py:49-59`).

La provenance de cette fixture est explicitement **synthétique**, pas un export
Mongo/Garmin : `backend/tests/fixtures/coach_session_synthesis_c351.json:2-11`.
La reproduction mathématique des deux chiffres est établie ; leur identité
avec les données runtime de la séance réelle du 10/10 ne l'est pas. Les exemples
C357 du 10/10 utilisent une autre entrée synthétique, avec 0,5 s/km :
`docs/reports/C357_NARRATIVE_COACH_POLISH.md:75-106`.

### Populations et exclusions

Pour l'écart-type, V2 cherche le plus grand groupe autour d'un effort ancre,
en parcourant d'abord les durées, puis les distances. Le critère de comparaison
est `abs(a-b) / max(a,b) × 100 <= 20`, avec des valeurs positives finies.
En cas d'égalité de taille, le premier groupe retenu reste sélectionné.
Les allures absentes, non finies ou non positives sont exclues ; au moins deux
allures sont requises. `partial_comparison` vaut vrai si le groupe ou sa
couverture d'allure ne couvre pas tous les efforts
(`backend/workout_analysis_v2.py:1767-1838`).

Le jugement Coach Language impose des garanties supplémentaires : ordre fiable,
structure cohérente, mesures positives exploitables pour tous les efforts,
groupe couvrant tous les efforts, comparabilité de chaque paire et
réconciliation allure/durée/distance à 1 %. Il peut s'abstenir à proximité des
frontières de catégorie compte tenu de l'incertitude
(`backend/coach_language.py:103-157`).

La narration V3 ne crée pas ce jugement : elle accepte exclusivement une
conclusion canonique versionnée, de portée `all_comparable_efforts`, métrique
`mean_absolute_deviation_from_median`, avec comptes et valeurs valides ; elle
exige notamment au moins trois efforts
(`backend/narrative_coach_v3.py:73-108`).

`backend/workout_intelligence_v3.py:263-300` extrait de l'analyse V2 les comptes
et la disponibilité de régularité ; cette extraction ne remplace pas les
définitions statistiques ci-dessus.

## 3. Cause de l'incohérence perçue

La reconstruction montre **deux métriques différentes et valides**, et non un
écart d'unité, une différence de population ou un simple arrondi. Cela explique
numériquement le couple 6,6 / 7,7, sans prouver l'origine exacte de l'observation
historique.

Le Coach décrit un écart moyen à une allure centrale, tandis que les preuves
présentent un autre nombre sous une entrée technique `regularity`. Ce voisinage
peut laisser croire à deux valeurs contradictoires d'une seule mesure.

## 4. Décision de présentation

Aucune décision n'est implémentée dans cette PR documentaire. Orientation à
confirmer après levée du HOLD : distinguer explicitement l'« écart absolu moyen
à l'allure médiane » de l'« écart-type des allures des efforts comparables », ou
réserver la seconde mesure aux détails si son affichage simultané n'aide pas.
Préserver FR/EN/ES et ne recalculer aucune valeur dans le frontend.

Ne jamais modifier une source pour forcer l'égalité. Le jugement reste sous
l'autorité canonique existante ; une dispersion seule ne démontre ni régularité
ni irrégularité. Les états démontré, non démontré, comparaison partielle et
données insuffisantes doivent rester distincts.

Pour le 19/09, l'origine runtime du **16,6 s/km** n'a pas été établie. L'exemple
C357 correspondant ne contient pas les mesures permettant cette vérification.
Il ne doit pas être utilisé comme preuve de régularité ou d'irrégularité.

## 5. Transition V2 → V3 : audit statique

Sources :
`frontend/src/hooks/useWorkoutIntelligence.js:5-31`,
`frontend/src/components/workout/NarrativeWorkoutAnalysis.jsx:5-10`,
`frontend/src/pages/WorkoutDetail.jsx:81-84,263-266`,
`frontend/src/pages/SessionDetail.jsx:53-56,171-203`,
`frontend/src/pages/DetailedAnalysis.jsx:29-74,167-194`.

| État | Comportement observé dans le code, non vérification navigateur |
| --- | --- |
| Initial autorisé | Le hook expose un état de chargement et lance V3 indépendamment de V2. |
| V2 rapide, V3 en attente | L'absence de récit valide déclenche les branches de fallback. WorkoutDetail et SessionDetail ne consomment pas le chargement V3 ; DetailedAnalysis le consomme, mais n'en fait pas une barrière locale au fallback dès que les autres données sont disponibles. |
| V3 valide | Le récit remplace les branches narratives historiques ; V2 n'est pas requis par le validateur du récit. |
| V3 absent ou incomplet | `getWorkoutNarrative` renvoie `null` ; fallback existant. |
| V3 en erreur | Le hook termine en erreur ; les pages exposent un message discret et le fallback disponible. |
| Changement de séance | La clé `[id, lang]` masque une réponse V3 d'une autre séance ; le nettoyage annule la requête V3. Les requêtes séance/V2 de SessionDetail ne sont pas toutes annulables : risque distinct à vérifier lors de la reprise. |
| Changement de langue | Même protection de clé et annulation V3 ; le validateur exige aussi la langue attendue. |
| Révocation Premium | `allowed` masque immédiatement les données V3 et le nettoyage annule la requête. Les pages conditionnent leur rendu analytique aux droits ; aucun test de révocation en vol n'a été exécuté dans cet audit. |
| FREE ou droits non confirmés | Aucun appel V3 lancé par le hook lorsque `allowed` est faux ; gating existant conservé. |

La cause du flash est donc l'assimilation, au rendu du fallback, de « V3 pas
encore disponible » à « V3 définitivement absent ». Le test existant
`frontend/src/__tests__/workout-analysis-v3-pages.test.jsx:518-527` attend
explicitement un Coach V1 pendant l'attente de V3 ; il devra changer lors de
l'implémentation, pas dans cette PR documentaire.

Le hook ne définit pas lui-même de timeout réseau. L'absence de chargement
infini reste à vérifier ; cet audit ne certifie pas cette garantie.

## 6. Correction effectivement implémentée et fichiers modifiés

**Aucune correction applicative.** Seul ce rapport est ajouté :

`docs/reports/C358_WORKOUT_ANALYSIS_CONSISTENCY_LOADING.md`.

Aucun contrat API, calcul, seuil LT1/LT2, Training, Garmin/GCCLI, abonnement,
cache ou traduction n'est modifié. Aucune écriture MongoDB, aucun déploiement
et aucun merge.

## 7. Tests et contrôles exécutés

- Vérification Git de l'arbre propre, du HEAD et du HEAD distant canonique :
  effectuée.
- Vérification GitHub des merges C356 et C357 : effectuée.
- Lecture des sources et tests cités : effectuée.
- Reproduction numérique indépendante en lecture seule avec la bibliothèque
  standard Python (`statistics.median`, moyenne des écarts absolus,
  `statistics.pstdev`) : effectuée ; résultats consignés en section 2.
- Cette reproduction n'exécute pas le pipeline applicatif complet.
- Suites backend/frontend, lint et build : **non exécutés** ; changement
  documentaire uniquement.
- Aucun nouveau test n'est ajouté ; aucun test existant n'est modifié.
- Les contrôles de diff, secrets et revue documentaire sont effectués au cours
  de la livraison ; leurs résultats sont indiqués dans la PR, sans les
  présumer ici.

Les matrices fonctionnelles FR/EN/ES, valeurs absentes/nulles/non finies,
comparaison partielle, chargements croisés, erreurs, navigation, révocation et
absence de doublons restent à exécuter après autorisation de reprise.

## 8. Captures et validation visuelle

**Aucune capture ni validation Playwright effectuée.** Les trois pages n'ont pas
été vérifiées sur mobile/desktop, ni pendant un délai V3 simulé de 2,5 secondes.
Les scénarios V3 immédiat, indisponible, valide avec V2 en erreur, métriques
distinctes et séance indéterminée restent non validés visuellement.

Aucune validation Garmin réelle n'est revendiquée. Les fixtures décrites ici
sont synthétiques ; aucune capture historique n'est réutilisée comme preuve
de cette livraison.

## 9. Risques résiduels et déblocage

- Les deux problèmes applicatifs restent inchangés.
- La provenance numérique et le chemin de code sont établis sur fixture ;
  l'identité avec les observations runtime historiques n'est pas prouvée.
- L'origine du 16,6 s/km du 19/09 reste non vérifiée.
- Les garanties de navigation, timeout et révocation n'ont pas été exercées
  dans un navigateur ou par des tests pendant cette intervention.

Pour reprendre, fournir les réponses API V2/V3 anonymisées des séances du
10/10 et du 19/09, incluant phases d'effort, mesures, comptes, preuves et
métadonnées de comparaison, avec date d'extraction. Retirer les identifiants
personnels, cookies et jetons ; aucun accès en écriture ni dump complet de base
n'est demandé. Une clarification explicite du périmètre autorisant la seule
reconstruction synthétique peut également permettre de réévaluer le gate.

## 10. Verdict

**HOLD pour l'implémentation C358 et toute validation fonctionnelle.**

La PR en brouillon sert uniquement à conserver l'audit demandé, conformément
à l'autorisation utilisateur après le STOP. Elle n'est pas une livraison
fonctionnelle de C358 et ne doit pas être présentée comme prête au merge.
Attendre la levée du blocage et l'audit humain ; aucun merge automatique.

## 11. Autorisation et périmètre de la reprise

L'utilisateur a explicitement levé le HOLD et autorisé l'implémentation à partir
de fixtures synthétiques :

> « Il n'est pas nécessaire d'obtenir les réponses API réelles des séances
> Garmin du 10/10 et du 19/09 pour commencer les corrections. »

La même PR #358 et la même branche sont conservées. Base de comparaison :
`copilot/dev` à `bdb67314b3bb16ae166dc1e91f3ba11039d9b616`. HEAD de reprise :
`c263d318dd72fef6b3e19c2130ef8868d48ccfea` (rapport initial uniquement).
HEAD applicatif validé (code et tests unitaires) :
`3c4a12e4eae5ee47e86b7af203eda649ba4b19d9`.
Les commits suivants ajoutent les preuves navigateur et le rapport.
Le SHA final de livraison est communiqué dans la PR avec les résultats exacts.

Les fixtures ne deviennent pas des observations réelles par cette autorisation.
Aucune connexion Garmin/GCCLI, aucune écriture MongoDB et aucun déploiement
ne sont nécessaires ni effectués.

## 12. Présentation corrigée des métriques

Les formules et leurs champs sources restent inchangés. Les seules
modifications backend sont des constantes textuelles et le numéro de génération
du catalogue narratif (`c358-controlled-1`), pour invalider les anciens textes
dans le cache existant, sans créer de cache.

- Le Coach garde le jugement canonique et l'écart absolu moyen existant.
  « Allure centrale » devient explicitement « allure médiane », « median pace »
  ou « mediana de los ritmos ».
- Les textes V2 de preuves et de fallback décrivent explicitement un
  écart-type ; les codes et champs de contrat, dont `fact.effort_dispersion`,
  restent inchangés.
- Sans jugement canonique, la narration peut toujours citer l'écart-type
  fourni, sans conclure à la régularité ; les réserves deviennent elles aussi
  explicites sur la métrique concernée.
- L'écart-type quitte la grille de preuves principale V3. Il reste dans les
  détails des phases, avec les libellés « Écart-type des allures »,
  « Pace standard deviation » et « Desviación estándar de los ritmos ».
  Le résumé principal ne juxtapose donc plus 6,6 et 7,7 comme deux valeurs
  supposées d'un même indicateur.
- Zéro est conservé ; une valeur absente ou non finie n'est pas remplacée par
  zéro. La couverture partielle reste affichée ; aucun seuil de catégorie
  n'est ajouté au frontend.

Le contrôle AST des trois modules backend modifiés confirme que, après
neutralisation des constantes de chaînes, leurs arbres syntaxiques sont
identiques à la base. Les définitions des classes de modèles sont identiques,
sans neutralisation. Aucun calcul, seuil ou contrat n'a été changé.

## 13. Machine à états de chargement

L'état réseau V3 devient une condition explicite des branches de rendu des
trois pages :

| Situation | Rendu Coach |
| --- | --- |
| FREE ou droit non confirmé | Pas de requête V3 ni de placeholder V3 ; gating conservé. |
| Autorisé, requête en attente | Placeholder local et discret, aucun récit V1/V2 ; données factuelles disponibles conservées. |
| Réponse valide dans la langue courante | Coach V3 directement, sans attendre V2 et sans doublon historique. |
| Réponse absente ou incomplète | Fin du placeholder, fallback V1/V2 disponible. |
| Erreur réseau/HTTP ou timeout | Fin du placeholder, fallback et message d'indisponibilité existant. |
| Nouvelle séance/langue/droits | Invalidation du périmètre précédent au rendu et annulation des requêtes obsolètes au nettoyage. |
| Démontage | Annulation ; les réponses tardives ne mettent plus à jour l'état. |

Le hook V3 utilise une identité de périmètre renouvelée lors d'un changement
d'identifiant, langue ou autorisation. Elle protège également une révocation
suivie d'un rétablissement des droits, même pour la même séance/langue.
Un timeout réseau Axios de 15 secondes borne l'attente V3 : ce n'est ni un
délai artificiel avant affichage, ni un nouveau cache.

Les requêtes séance et V2 de SessionDetail deviennent annulables, et les données
de séance sont masquées tant qu'elles appartiennent à la route précédente.
DetailedAnalysis conserve l'affichage des données disponibles sans dépendre
de la fin de V2 pour présenter V3.

## 14. Validation backend de la reprise

Exécution depuis le répertoire `backend`, avec `python -m pytest` et la
configuration existante `-n 2 --dist loadscope`.

### Suites ciblées

```text
python -m pytest tests/test_workout_consistency_c358.py tests/test_narrative_coach_v3.py tests/test_workout_intelligence_v3.py tests/test_coach_repetition_judgment.py tests/test_coach_language.py -q --tb=short
750 passed, 7 warnings
```

Les 18 nouveaux cas C358 couvrent FR/EN/ES : même population de quatre efforts,
valeurs distinctes 6,6 et 7,7, vocabulaire médiane/écart-type, absence de
recalcul dans la narration, sources non mutées et enveloppe narrative
inchangée. Ils couvrent aussi six efforts dont quatre comparables, avec une
observation **injectée synthétiquement** de 16,5621, sans jugement canonique,
et les valeurs absentes/non finies.

### Régression étendue

```text
python -m pytest tests/test_workout_consistency_c358.py tests/test_narrative_coach_v3.py tests/test_workout_intelligence_v3.py tests/test_workout_analysis_v2.py tests/test_workout_analysis_v2_phases.py tests/test_workout_analysis_v2_facts.py tests/test_workout_analysis_v2_unified.py tests/test_coach_language.py tests/test_coach_session_synthesis_c351.py tests/test_coach_repetition_judgment.py -q --tb=short
1346 passed, 3 failed, 14 warnings
```

Les trois échecs sont exactement les cas historiques
`test_workout_analysis_v2.py::test_comparable_history_stays_separate_and_metrics_are_unchanged[en/fr/es]` :
attendu `meaning.consistent_pacing`, obtenu
`meaning.hr_without_intensity_with_pacing`.

Ils ont été reproduits indépendamment depuis une archive Git de la base exacte
`bdb67314b3bb16ae166dc1e91f3ba11039d9b616`, dans le même environnement :

```text
python -m pytest tests/test_workout_analysis_v2.py::test_comparable_history_stays_separate_and_metrics_are_unchanged -q --tb=short
3 failed, 14 warnings
```

Aucun test historique n'est supprimé ou affaibli pour les masquer. Les
premières tentatives ont rencontré une dépendance de test manquante et une
assertion C358 initialement trop stricte sur l'emplacement d'une réserve
(déjà portée par la couverture du récit) ; après restauration des dépendances
et correction de ce nouveau test, les résultats finaux sont ceux ci-dessus.

## 15. Fichiers applicatifs et tests concernés

| Fichier | Changement |
| --- | --- |
| `backend/coach_language.py` | Vocabulaire médiane dans la conclusion existante, sans toucher au jugement. |
| `backend/narrative_coach_v3.py` | Vocabulaire médiane/écart-type FR/EN/ES et génération du catalogue. |
| `backend/workout_analysis_v2.py` | Six textes localisés de preuves/conseils précisent l'écart-type. |
| `backend/tests/test_workout_consistency_c358.py` | Dix-huit régressions synthétiques. |
| `frontend/src/hooks/useWorkoutIntelligence.js` | Périmètre de requête et timeout réseau V3. |
| `frontend/src/components/workout/WorkoutCoachPending.jsx` | Placeholder localisé, accessible via `role="status"`. |
| `frontend/src/components/workout/NarrativeWorkoutAnalysis.jsx` | Suppression de l'écart-type de la grille de résumé V3. |
| `frontend/src/components/workout/WorkoutPhaseAnalysis.jsx` | Libellé explicite et couverture du nombre d'efforts ; distinction avec la variation premier/dernier effort. |
| `frontend/src/lib/i18n.js` | Libellés et chargement FR/EN/ES. |
| `frontend/src/pages/WorkoutDetail.jsx` | Garde d'attente V3, périmètres et placeholder. |
| `frontend/src/pages/SessionDetail.jsx` | Même garde ; annulation et protection des requêtes séance/V2. |
| `frontend/src/pages/DetailedAnalysis.jsx` | Même garde ; affichage indépendant des données disponibles. |
| `frontend/src/__tests__/workout-analysis-v3-pages.test.jsx` | Nouveau comportement pendant l'attente et matrice de concurrence/accès/langues sur les trois pages. |
| `tests/e2e/c358-consistency-loading.spec.ts` | Vérifications navigateur sur composants réels, API simulée. |
| `tests/fixtures/c358-workouts.ts` | Entrées et textes synthétiques explicitement identifiés. |
| `docs/reports/assets/c358/` | Captures et résultats structurés simulés, distincts des données Garmin. |
| `docs/reports/C358_WORKOUT_ANALYSIS_CONSISTENCY_LOADING.md` | Audit conservé et compte rendu de reprise. |

Les fichiers de modèles narratifs/V3 et le moteur Workout Intelligence V3 ne
sont pas modifiés. Aucun manifeste ni lockfile de dépendances n'est changé.

## 16. Tests frontend et build

Dépendances existantes restaurées depuis `frontend` avec :

```text
npm ci --legacy-peer-deps --no-audit --no-fund
```

Commande finale, exécutée sur les derniers changements applicatifs :

```text
CI=true REACT_APP_BACKEND_URL=http://localhost:8000 npm test -- --watchAll=false --runInBand src/__tests__/workout-analysis-v3-pages.test.jsx src/__tests__/workout-analysis-v2-pages.test.jsx src/__tests__/analysis-format.test.js
3 suites passed, 946 tests passed

REACT_APP_BACKEND_URL=http://localhost:8000 npm run build
Production build succeeded
```

La suite historique V3 qui attendait un Coach V1 pendant l'attente attend
désormais le placeholder, vérifie explicitement l'absence des anciens textes
et conserve le contrôle des phases factuelles.

La matrice des trois pages couvre :

- V2 avant V3 et V3 avant V2, y compris V2 en erreur ;
- délai réseau synthétique de 2 500 ms (test à horloge contrôlée), avec absence
  des récits historiques jusqu'à la réponse ;
- HTTP 500, réponse absente/incomplète et erreur de timeout ;
- données factuelles disponibles pendant l'attente, et absence d'erreur
  prématurée quand les requêtes factuelles/V2 sont encore en cours ;
- absence des résumés historiques même lorsque toutes les métriques principales
  sont absentes ou non finies ;
- changements de séance/langue avec réponses désordonnées et annulation ;
- démontage, révocation des droits pendant l'attente, masquage immédiat des
  données déjà reçues et rétablissement avec un nouveau périmètre ;
- FREE, droits en cours de confirmation et TRIAL/PREMIUM autorisés ;
- absence de doublon, FR/EN/ES, chiffres distincts, détail replié, couverture
  partielle et valeurs absentes/non finies/zéro ;
- variation premier/dernier effort correctement nommée quand l'écart-type
  manque, sans la présenter comme un écart-type.

Une revue indépendante en lecture seule a signalé une erreur d'indisponibilité
V2 affichée prématurément dans DetailedAnalysis lorsque V3 était terminal mais
V2 encore en cours. Un état `analysisLoading` séparé et 18 cas d'ordonnancement
FR/EN/ES ont été ajoutés. Le dernier passage de 946 tests inclut ce correctif ;
la revue de suivi ne relève plus de problème significatif.

## 17. Protocole navigateur simulé

La validation utilise les véritables composants de l'application React locale,
pas une maquette HTML. Le navigateur Chromium intercepte les réponses
d'authentification, de droits, de séance et d'analyse ; les autres origines
(polices distantes et télémétrie incluses) sont bloquées avant accès réseau.
Cette interception ne valide pas les mécanismes réels d'authentification ou
d'abonnement.

Le protocole couvre les trois routes en 1920 × 1080 et 390 × 844, dans les
trois langues. Scénarios : V3 immédiat, V3 retardé de 2,5 secondes, HTTP 500,
réponse absente, réponse incomplète, V3 valide avec V2 en erreur et comparaison
partielle sans jugement. Les tests vérifient le DOM pendant l'attente, et pas
seulement après la réponse : placeholder, absence de textes historiques et
métriques factuelles visibles.

Les captures représentatives anglaises distinguent, pour chaque route et
chaque taille :

1. chargement initial, avant libération des données simulées ;
2. données factuelles avec placeholder Coach local ;
3. attente V3 simulée de 2,5 secondes ;
4. Coach V3 valide, sans doublon ;
5. fallback après HTTP 500.

Les états FR/ES sont contrôlés par assertions de visibilité, texte et mesures
de mise en page, avec résultats structurés ; ils ne sont pas présentés comme
une galerie de captures FR/ES. Les détails sont vérifiés initialement repliés
puis ouverts, avec libellé explicite, couverture et absence de débordement
horizontal. Les images sont capturées mais ne font pas l'objet d'une revue
humaine pixel par pixel dans cette intervention ; les contrôles visuels
automatisés reposent sur le DOM et les mesures de géométrie.

Le manifeste `docs/reports/assets/c358/validation-summary.json` et les
enregistrements par cas conservent commandes, dimensions, textes observés,
requêtes simulées, empreintes des sources et captures. Ils indiquent
explicitement le HEAD présent lors de l'exécution et l'arbre de travail
modifié ; ce HEAD de capture ne doit pas être confondu avec un commit de code
déjà publié. La base d'intégration de cette PR reste le SHA indiqué en
section 11.

### Résultats navigateur finaux

```text
cd tests
./node_modules/.bin/playwright test e2e/c358-consistency-loading.spec.ts --retries=0
133 passed, 0 failed, 0 skipped, 0 flaky (3,5 minutes)
```

Soit les 126 combinaisons de la matrice, une vérification arithmétique et six
cas supplémentaires DetailedAnalysis : V3 en erreur alors que V2 reste en
attente, pour chaque langue et chaque taille. Ces six cas vérifient que les
métriques restent visibles et qu'aucune erreur V2 prématurée n'est affichée
avant la fin de sa propre requête.

Résultats persistés :

- **30 PNG**, soit cinq états pour chaque couple page/taille ;
- **132 enregistrements de cas**, manifeste, journal et résultats du runner ;
- aucun débordement horizontal observé dans les états mesurés, y compris
  après ouverture des détails ;
- aucune exception de page, aucune requête API inattendue ;
- aucun récit historique pendant l'attente V3, puis un seul Coach V3 valide ;
- textes FR/EN/ES visibles, écart-type seulement dans les détails ;
- couverture partielle 4/6 et absence de jugement, avec 16,5621 injecté ;
- absence de répétition des paragraphes dans les fixtures narratives finales.

Les fixtures ont été corrigées pendant leur élaboration : une expression
régulière confondait 16,6 et 6,6, une réponse fallback n'incluait pas la
conclusion synthétique attendue sur deux pages, et les textes partiels
réutilisaient un titre quatre efforts et une réserve répétée. Ces problèmes
de fixtures/tests ne sont pas présentés comme des défauts Garmin. Les passages
précédents ont été remplacés par le passage final sans retry ; le manifeste
en conserve les limites. Les textes de référence reflètent maintenant la
catégorie canonique « variations perceptibles », et la moyenne d'allure V2 est
la moyenne arithmétique des allures individuelles, pas un rapport global
durée/distance.

Les empreintes des sources enregistrées ont été comparées aux fichiers finaux :
elles correspondent. Les preuves enregistrent le HEAD de capture
`c263d318dd72fef6b3e19c2130ef8868d48ccfea` et l'arbre modifié, pas un faux
HEAD de livraison. Leur contenu applicatif correspond au commit
`3c4a12e4eae5ee47e86b7af203eda649ba4b19d9`. Les captures générées
automatiquement dans `tests/test-results` ont été supprimées ; seules les
captures persistantes listées par le manifeste sont livrées.

Exemples comparatifs :

- [WorkoutDetail mobile — placeholder](assets/c358/WorkoutDetail-mobile-en-delayed-local-placeholder.png)
  → [Coach V3](assets/c358/WorkoutDetail-mobile-en-delayed-valid.png)
  → [fallback HTTP 500](assets/c358/WorkoutDetail-mobile-en-http500-fallback.png).
- [SessionDetail desktop — attente](assets/c358/SessionDetail-desktop-en-delayed-delayed-2500ms.png)
  → [Coach V3](assets/c358/SessionDetail-desktop-en-delayed-valid.png).
- [DetailedAnalysis mobile — attente](assets/c358/DetailedAnalysis-mobile-en-delayed-delayed-2500ms.png)
  → [Coach V3](assets/c358/DetailedAnalysis-mobile-en-delayed-valid.png).

## 18. Sécurité, limites et verdict de reprise

- Contrôles de diff : sans erreur d'espacement.
- Scans de secrets des fichiers applicatifs, tests, rapport et 168 fichiers
  de tests navigateur/preuves (PNG inclus) : aucune détection.
- Revue indépendante en lecture seule : le défaut V2 prématuré a été corrigé,
  puis aucun autre problème significatif signalé.
- Validation parallèle Code Review/CodeQL demandée après publication des
  changements : l'outil a refusé l'exécution faute de budget de temps restant,
  avec consigne de ne pas le relancer. **Aucun résultat CodeQL final n'est
  revendiqué sur ce HEAD.** Le contrôle automatisé reste à effectuer avant
  toute décision de merge ; la revue indépendante ci-dessus a bien été faite.

**Risques résiduels :**

1. Les trois échecs V2 historiques sont toujours présents et reproduits sur la
   base ; ils ne sont ni nouveaux ni corrigés par cette PR.
2. Les réponses réseau, droits et données du navigateur sont simulés. Les
   tests ne certifient ni les valeurs exactes des séances Garmin citées, ni
   l'authentification ou l'application réelle des abonnements côté serveur.
   L'autorisation utilisateur a explicitement retiré cette dépendance pour
   commencer et livrer C358.
3. Les captures utilisent les polices locales de repli, les origines externes
   étant bloquées. Une revue humaine des images et de la lisibilité finale
   reste nécessaire.
4. Le timeout V3 de 15 secondes privilégie un fallback explicite plutôt
   qu'une attente infinie si le service réel est exceptionnellement lent.
5. Aucun test réel Garmin, aucun LLM réel, aucune écriture MongoDB, aucun merge
   et aucun déploiement ne sont effectués.

**Verdict : GO conditionnel pour audit humain de la PR #358 en brouillon**,
avec contrôle automatisé de sécurité encore requis et acceptation explicite des échecs V2
préexistants. Les deux corrections applicatives sont livrées, sur preuves
synthétiques déclarées, sans changer les formules ni les contrats. Le HOLD
historique des sections 1 à 10 est levé par l'autorisation de reprise.
Attendre l'autorisation utilisateur avant tout merge ou intégration Emergent.
