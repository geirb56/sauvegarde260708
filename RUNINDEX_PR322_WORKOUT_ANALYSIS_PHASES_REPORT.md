# RUNINDEX — PR322 — Workout Analysis V2 : analyse des phases structurées

## 1. Audit du moteur avant modification

### Références Git

- Base de travail `copilot/dev` après merge de #321 : `3ad759622f92fe250db512b14d8be8c4a821d013`.
- HEAD initial de la branche : le même merge #321, vérifié comme premier parent du commit de merge.
- HEAD de code testé et HEAD final sont à relever après les commits de livraison.
- Aucun merge supplémentaire, déploiement, appel GCCLI ou accès à MongoDB réel n'a été effectué.

L'audit préalable a porté sur `backend/workout_analysis_v2.py`,
`backend/workout_analysis_v2_service.py`, `backend/activity_phases.py`,
`backend/garmin/domain_adapter.py`, `backend/training_v2/domain_activity.py`,
`backend/garmin/activity_details.py`, les routes Garmin et Workout Analysis V2,
les tests concernés, ainsi que les rapports #305, #318, #319 et #321 présents
dans le dépôt.

### Constats établis dans le code

1. **Chargement et autorisation** — `load_scoped_workout_analysis_v2()` commence
   par charger `workouts` avec `{id, user_id}`. Une activité absente ou étrangère
   n'est pas analysée. Pour un workout Garmin, son activité source est ensuite
   recherchée par utilisateur et identifiant externe dans `garmin_activities`.
2. **Normalisation et frontière métier** — `activity_phases.py` définit déjà
   `ActivityPhase`, contrat immuable et neutre, avec ordre, type natif et
   normalisé, mesures facultatives et provenance. `garmin.data_layer` normalise
   les lignes avant persistance. `DomainActivity` reste une activité sommaire de
   Training V2 et ne porte pas de phases.
3. **Analyse actuelle** — le moteur analyse les métriques d'activité, `km_splits`
   et `split_analysis`. `signals.session_type` emploie les catégories
   `short`/`standard`/`long`; `evidence.has_splits` indique spécifiquement des
   splits kilométriques ou leur analyse. Il ne doit donc pas devenir un indicateur
   de phases.
4. **Allure et FC** — l'allure actuelle provient des métriques workout et de
   `km_splits`; physiologie utilise les FC disponibles et n'autorise pas une
   classification d'intensité par simple présence de zones sans provenance
   vérifiée. Ces calculs restent inchangés. La phase calcule l'allure depuis
   durée/distance positives; si les deux sont disponibles, une vitesse native
   positive et cohérente est prioritaire, sinon durée/distance est utilisée.
   Une divergence supérieure à 20 % est signalée et l'allure de cette phase
   reste absente. Si durée ou distance manque, seule une vitesse positive
   enregistrée peut fournir l'allure.
5. **Prescription** — le loader et le moteur de Workout Analysis V2 n'associent
   pas de prescription à l'activité. Training V2 et ses snapshots/payloads sont
   des autorités séparées; aucun lien fiable d'association prescription–séance
   n'a été identifié ici. L'analyse ajoutée est descriptive et ne tente aucun
   matching.
6. **API et frontend** — la route existante est
   `/api/coach/workout-analysis/{workout_id}`, authentifiée et typée avec
   `WorkoutAnalysisV2Response`. L'analyse est aussi consommée dans le contexte
   Coach. Le frontend actuel continue de recevoir tous les champs V2 existants.
7. **Cache de phases #321** — `activity_details` est persisté dans le document
   Garmin avec `schema_version=2`, statut, source, endpoint et phases. GET est
   cache-only; le POST explicite et le worker sont les voies d'enrichissement,
   non appelées par Workout Analysis V2.
8. **Rapports historiques** — #305 documente le chargement factuel scoped et
   l'absence de mutation de `workouts`; #318/319 documentent les contrats V2 et
   leur usage frontend; #321/C321 documente les phases normalisées, cache-only
   et les limites des données synthétiques. Ils sont traités comme preuves
   historiques, pas comme validation d'une base runtime actuelle.

## 2. Architecture réelle et point d'injection retenu

Chaîne mise en place :

`activité workout déjà autorisée → source d'activité de même utilisateur → cache versionné → ActivityPhase → moteur V2 → réponse API`

Le point d'injection est `workout_analysis_v2_service.py`, après le contrôle
`workouts.id + user_id` et pendant la lecture source déjà existante et
scopée. Une fonction locale valide le cache et convertit ses phases vers le
modèle existant `ActivityPhase`. Elle vérifie la version, le statut `complete`,
la provenance/endpoint, l'ordre contigu, les types, les valeurs finies et les
mesures non négatives. Toute absence ou donnée invalide reprend l'analyse
standard.

Le moteur ne dépend que du modèle neutre `ActivityPhase`; il n'importe aucun
module `garmin.*`. Le changement de `activity_details.SCHEMA_VERSION` fait
référence à la constante unique définie auprès de ce contrat neutre. Aucun
changement n'a été apporté à GCCLI, synchronisation, Training V2, Readiness,
Coach IA ou frontend.

## 3. Contrats existants préservés

- Les champs de réponse V2 préexistants gardent leurs noms et sémantiques; seul
  `phase_analysis` est ajouté avec une valeur par défaut compatible avec les
  anciens payloads.
- `evidence.has_splits`, `km_splits`, leurs calculs et `split_analysis` restent
  exclusivement liés aux splits kilométriques.
- Aucun ancien enregistrement, analyse historique, document `workouts` ou cache
  n'est modifié.
- Aucun jugement de réussite/échec, zone FC, score physiologique ou prescription
  n'est produit.
- L'absence de phases renvoie `available=false`, `analysis_type="standard"` et
  les mêmes résultats historiques hors champ additif.

## 4. Nouveaux champs et calculs

`phase_analysis` expose disponibilité, type d'analyse, provenance, liste ordonnée
des phases, efforts numérotés, récupérations numérotées, statistiques
descriptives par groupe, régularité descriptive, valeurs manquantes et
limitations. Chaque phase conserve son type natif, ses mesures d'origine et ses
valeurs `None`.

- Allure : `duration_s * 1000 / distance_m` lorsque les deux mesures sont
  positives et cohérentes; vitesse native positive prioritaire lorsqu'elle
  concorde. Vitesse native seule peut être utilisée si une des deux mesures
  manque. L'écart de cohérence toléré est 20 %, exposé dans les limitations de
  données comme `incoherent_pace` au-delà de ce seuil.
- FC : moyenne et maximum de chaque phase sont retransmis tels quels. Aucune
  baisse ou vitesse de récupération cardiaque n'est calculée.
- Régularité : une répétition est comparable à la première si sa durée **ou**
  sa distance est à moins de 20 % de celle-ci. Dispersion des allures calculée
  comme écart-type descriptif; évolution premier–dernier et changement des FC
  moyennes sont descriptifs, sans attribuer de cause à une variation.
- Les métriques absentes restent `None`; une métrique partielle n'est pas
  complétée par zéro. Les phases inconnues restent dans l'ordre chronologique,
  sans être reclassées en effort/récupération.

## 5. Données de référence synthétiques

Les assertions reproduisent les valeurs de référence fournies dans le besoin,
sans fixture personnelle ni lecture MongoDB réelle :

| Effort | Durée | Distance synthétique de référence | Allure calculée | FC moyenne/max |
|---|---:|---:|---:|---:|
| 1 | 240 s | 832,07 m | 288,44 s/km (4:48/km) | 151/160 |
| 2 | 240 s | 851,11 m | 281,98 s/km (4:42/km) | 157/165 |
| 3 | 240 s | 885,81 m | 270,99 s/km (4:31/km) | 159/175 |
| 4 | 240 s | 825,41 m | 290,76 s/km (4:51/km) | 159/166 |

Le test synthétique retrouve 10 phases, dont 4 efforts et 4 récupérations,
conserve les FC, valide la régularité descriptive et ne fabrique ni zone ni
conformité. Les distances/FC des récupérations ne sont pas présentes dans cette
référence et restent donc absentes dans le test. Ce résultat n'est pas une
validation du runtime Emergent.

## 6. Tests exécutés

Environnement : Python 3.12.3; dépendances de test backend existantes installées
pour cette exécution uniquement, sans modification des manifestes.

| Commande depuis `backend/` | Résultat |
|---|---|
| `python -m pytest tests/test_workout_analysis_v2_phases.py -q` | **21 passed** |
| `python -m pytest tests/test_workout_analysis_v2.py tests/test_coach_context_v2.py tests/test_activity_details_pr321.py -q` | **377 passed, 14 warnings** |

Les tests couvrent activité sans phases, alternance et ordre, échauffement,
retour au calme, type inconnu, mesures absentes/nulles, FC absente, allure
incohérente, comparabilité, répétition unique, régularité régulière/irrégulière,
compatibilité du payload antérieur, cache versionné absent/invalide, scoping
utilisateur, maintien des km splits et absence d'enrichissement/appel fournisseur.

Contrôles additionnels : `python -m compileall -q` sur les fichiers Python
modifiés et `git diff --check` réussis. Aucune connexion à MongoDB/GCCLI réel ni
aucun test runtime Emergent n'a été exécuté. Le scan de secrets et
`parallel_validation` sont à effectuer après le commit final.

## 7. Risques résiduels et points à vérifier dans Emergent

- Vérifier en environnement Emergent que les documents de phases issus de #321
  emploient effectivement le contrat version 2 prévu et que l'association entre
  identifiant externe et workout dérivé correspond aux données déployées.
- Confirmer les unités et l'interprétation de `average_speed_mps`, `duration_s`
  et `distance_m` sur un enregistrement synthétique/autorisé. GitHub ne relit pas
  la base MongoDB ni l'activité réelle.
- Le seuil descriptif de cohérence et de comparabilité de 20 % est une règle
  technique transparente, non une conclusion physiologique; sa pertinence
  produit peut être revue sur fixtures synthétiques contrôlées.
- Aucun matching de prescription n'est fourni; une future évolution devra
  établir un lien fiable avant toute comparaison.
- Toute vérification runtime future doit confirmer l'absence de requête
  d'enrichissement à l'analyse et l'isolation inter-utilisateurs, sans lancer
  GCCLI ni déclencher un POST depuis ce moteur.
