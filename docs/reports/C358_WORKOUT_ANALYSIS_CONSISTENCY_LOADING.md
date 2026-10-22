# C358 — Workout Analysis V3 Consistency & Loading UX

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
