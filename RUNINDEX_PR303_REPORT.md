# RUNINDEX — PR303 — Réparer la régression de l'analyse automatique des séances

- **Dépôt** : `geirb56/sauvegarde260708`
- **Base** : `copilot/dev` (HEAD distant au démarrage : `8f0b2e1`, merge de la PR #302)
- **Head** : branche `copilot/runindex-pr303-reparer-analyse-sessions`
- **Référence historique comparée** : `9b7947ec2e1bcd40d520b775f6d4f14a5ef4bcff` (avant PR #287)
- **Périmètre** : analyse automatique déterministe affichée dans `WorkoutDetail`
  (`GET /api/coach/workout-analysis/{workout_id}`). Le Coach IA conversationnel
  **n'est pas** modifié.

---

## 1. Tableau de comparaison du code avant/après PR287

| Capacité | Avant PR287 (`9b7947ec`) | Après PR287/PR290 (base `copilot/dev`) | Après PR303 |
|---|---|---|---|
| Texte factuel de la séance (distance, durée, allure, FC, cadence) | `analysis_engine.generate_session_analysis()` bloc `execution` via `EXECUTION_TEMPLATES_*` avec placeholders `distance_km`, `duree`, `allure_moy`, `fc_moy`, `cadence` | **Supprimé** : `summary`/`meaning`/`advice` sont des phrases fixes sans aucune valeur mesurée | Restauré et branché sur le contrat V2 (`summary`, `meaning`) |
| Recherche de séances similaires | `rag_engine.retrieve_similar_workouts()` : même sport, ±30 % de distance, séance courante exclue, tri par date, `limit=3` | **Supprimé** avec `rag_engine.py` ; seule reste une baseline 14 jours « même type » sans critère de distance | Réintroduit dans `workout_analysis_v2.retrieve_similar_workouts()` (bornes explicites, sans `rag_engine.py`) |
| Dérive cardiaque | `rag_engine` : `hr_drift` commenté mais avec attribution causale (« hydrate well ») | Champ `physiology.hr_drift` calculé mais **jamais exploité** dans un texte | Exploité, formulé sans attribution causale |
| Fractions kilométriques | Pas de lecture textuelle des splits | `pacing.fastest/slowest/pace_drop/negative_split/consistency/variability` calculés mais **jamais exploités** | Exploités tels quels (aucun recalcul) |
| Comparaison historique | `baseline` + `comparison` calculés côté `server.py` et verbalisés | `comparison.*` calculé et renvoyé, mais **jamais verbalisé** | Verbalisé dans `meaning` avec taille d'échantillon explicite |
| Sélection des conseils | `pick()` = `random.choice()` | Conseils déterministes mais réduits à « utilise des zones individualisées » | Déterministe, priorisé sur des faits observés |
| Classification d'intensité | Déduite des zones sans preuve de provenance | Indisponible sans provenance (`_has_trusted_zone_provenance=False`) | Inchangé (garde-fou conservé) |
| Fenêtre de requête historique | Historique complet chargé | 14 jours (`server.py`) | 180 jours bornés + `limit 200` (nécessaire à la recherche comparable) |

---

## 2. Capacités perdues identifiées et preuves dans le code

1. **Verbalisation factuelle de la séance.**
   Avant : `backend/analysis_engine.py@9b7947ec:394-406` construit `placeholders`
   (`distance_km`, `duree`, `allure_moy`, `fc_moy`, `cadence`) puis
   `execution = pick(EXECUTION_TEMPLATES_*).format(**placeholders)`.
   Après PR287 : `backend/workout_analysis_v2.py` (base) — `_build_summary()`,
   `_build_meaning()` et `_build_advice()` retournent `_template(language, key)`
   **sans aucun paramètre**. Aucune valeur mesurée n'apparaît dans les textes.

2. **Recherche historique par distance comparable.**
   Avant : `backend/rag_engine.py@9b7947ec:437-462` (`retrieve_similar_workouts`,
   même type, `abs(d - dc) <= dc * 0.3`, exclusion de la séance courante,
   tri décroissant par date, `limit`).
   Après PR287 : fonction supprimée avec le module ; `_build_baseline()` ne filtre
   que par `type` et par fenêtre de 14 jours, sans critère de distance.

3. **Mesures calculées mais mortes.**
   `pacing.fastest_split_min_km`, `slowest_split_min_km`, `pace_drop_min_km`,
   `negative_split`, `consistency_score`, `variability`, `physiology.hr_drift`,
   `comparison.*` : tous produits par `build_workout_analysis_v2()` mais aucun
   n'était lu par les générateurs de texte (aucune de ces variables n'apparaissait
   dans `_build_summary/_build_meaning/_build_advice`).

4. **L'absence de classification d'intensité était devenue l'explication principale.**
   `_build_meaning()` (base) retournait `meaning.hr_without_intensity_*` comme
   texte **unique**, et `_build_advice()` retournait `advice.hr_without_intensity`
   dès que la FC existait — soit le cas de toutes les séances Garmin sans zones
   validées.

---

## 3. Capacités effectivement restaurées

### Correctif 1 — Analyse contextualisée (`backend/workout_analysis_v2.py`)

`summary` = phrase structurelle existante **+** observations factuelles :
distance, durée, allure moyenne (ou vitesse pour le vélo), FC moyenne et maximale.

`meaning` = **faits d'abord**, réserve d'intensité en dernier :
- amplitude des fractions kilométriques + nombre de fractions réellement enregistrées ;
- `negative_split` uniquement quand il est établi (`is True`) ;
- perte d'allure enregistrée ;
- score de régularité, sinon variabilité ;
- dérive cardiaque, sans attribution causale ;
- dénivelé et cadence lorsqu'ils sont présents (cadence rapportée sans cible universelle) ;
- comparaison baseline (distance, allure, FC) avec taille d'échantillon et fenêtre ;
- comparaison historique « distances comparables » et ses limites.

`advice` = code déterministe priorisé sur les faits :
`even_pacing` → `negative_split_confirmed` → `maintain_consistency` →
`monitor_hr_drift` → `recover_after_long` → `hr_without_intensity` → `no_hr`,
complété par une seconde recommandation concrète
(`record_splits`, `build_history`, `use_hr`) pour que l'obligation de zones
individualisées ne soit jamais le seul conseil.

Génération 100 % déterministe (aucun `random`), FR/EN/ES.

### Correctif 2 — Recherche historique utile

`retrieve_similar_workouts(current_workout, candidate_workouts, ...)` :
- même utilisateur (garanti par la requête `server.py`, testé par isolation) ;
- même sport ;
- séance courante exclue ;
- séances **strictement antérieures** ;
- distance comparable `±30 %` (`SIMILAR_DISTANCE_TOLERANCE_PCT`), tolérance
  reprise de l'ancien moteur et vérifiée sur les fixtures ;
- fenêtre bornée à 180 jours (`SIMILAR_HISTORY_WINDOW_DAYS`) et 5 résultats max ;
- séparation entraînement/compétition **uniquement** sur métadonnées réelles
  (`is_race`, `race`, `event_type`, `workout_type`, `activity_category`) ;
  rien n'est déduit du nom ni de la distance ;
- résultat exposé dans `comparison.similar` avec `sample_count`, `comparable`,
  `limitations` (`sample_too_small`, `session_nature_unknown`,
  `no_comparable_reference`) et `reason_unavailable`.

Une différence d'allure ou de FC n'est jamais présentée comme une progression :
sous `SIMILAR_MIN_COMPARABLE_SAMPLE = 2`, la limite est écrite explicitement.
Sans référence pertinente, la comparaison est déclarée indisponible.

### Correctif 3 — Exploitation des mesures déjà calculées

Aucune métrique n'est recalculée : `pacing.*`, `physiology.hr_drift` et
`comparison.*` sont lus tels que produits par les constructeurs existants.
`comparison.similar` est le seul ajout, **additif** : les dix clés racine du
contrat V2 sont inchangées.

---

## 4. Anciens comportements volontairement exclus

- `pick()` / `random.choice()` : aucune sélection aléatoire de conseils.
- `rag_engine.py` et les anciens endpoints RAG : non restaurés.
- Enrichissement LLM dans l'endpoint déterministe : non réintroduit.
- Classification d'intensité à partir des zones sans provenance :
  `_has_trusted_zone_provenance()` reste `False`.
- Classification d'intensité à partir de la seule FC moyenne : non faite.
- Attribution causale de la dérive cardiaque (fatigue / déshydratation) :
  supprimée par rapport à l'ancien `rag_engine`.
- Cadence universelle (ancien seuil « < 165 ppm ») : non réintroduite.
- Prescription d'une nouvelle séance : aucune. Training Today/Week V2 restent
  les seules autorités de prescription.
- Aucun second moteur d'analyse, aucun nouvel endpoint.

---

## 5. Fichiers modifiés et justification

| Fichier | Justification |
|---|---|
| `backend/workout_analysis_v2.py` | Correctifs 1, 2 et 3 : observations factuelles, recherche historique bornée, exploitation des champs existants, nouveaux libellés FR/EN/ES |
| `backend/server.py` | Élargissement strictement nécessaire de la fenêtre de la requête historique (14 → 180 jours, `limit 200` inchangé) pour alimenter la recherche comparable. Endpoint, contrat et filtre `user_id` inchangés |
| `backend/tests/test_workout_analysis_v2.py` | Fixtures A et B, tests de contenu factuel, déterminisme, FR/EN/ES, données incomplètes, absence de référence, échantillon insuffisant, exclusion du futur, isolation/IDOR, contrat V2 ; mise à jour des 3 assertions devenues obsolètes |
| `RUNINDEX_PR303_REPORT.md` | Rapport obligatoire |

`frontend/src/pages/WorkoutDetail.jsx` **n'a pas été modifié** : la page lit déjà
`analysis.summary.text`, `analysis.meaning.text` et `analysis.advice.text`, donc
les observations restaurées s'affichent sans adaptation. Les tests frontend
existants passent sans changement.

---

## 6. Exemples des analyses générées pour les deux fixtures

### Séance A — course à pied, 21,27 km, 122 min, 5:43/km, FC moyenne 160 bpm
(fractions fournies, dérive 9 bpm, D+ 210 m, cadence 172 ppm, aucune zone de provenance validée)

- **summary** (`summary.long_structural`) :
  « Long-duration session completed. 21.27 km covered in 2h02 at 5:43/km.
  Average heart rate 160 bpm, peak 174 bpm. »
- **meaning** (`meaning.hr_without_intensity_with_pacing`) :
  « Kilometre splits ran from 5:24/km to 6:00/km (10 splits recorded).
  Recorded pace drop of 0:36/km across the session. Split consistency score: 88/100.
  Heart-rate drift measured at 9 bpm between the start and the end; this
  measurement alone does not establish its cause. Elevation gain: 210 m.
  Average cadence: 172 spm, reported as recorded and not compared with any
  universal target. […comparaison baseline et historique…] Heart-rate facts are
  available, but intensity classification is unavailable without trustworthy zone
  evidence, so this session is interpreted structurally. »
- **advice** (`advice.even_pacing`) :
  « Target a more even pace distribution: start slightly more conservatively so
  the recorded pace drop shrinks on the next session of this distance. »
- **FR** : « Séance longue réalisée. 21.27 km parcourus en 2h02 à 5:43/km.
  Fréquence cardiaque moyenne 160 bpm, maximale 174 bpm. »

### Séance B — course à pied, 10,18 km, 71 min, 6:59/km, FC moyenne 127 bpm
(aucune fraction, aucune zone de provenance validée, une seule séance comparable antérieure)

- **summary** (`summary.standard_structural`) :
  « Standard-duration session completed. 10.18 km covered in 1h11 at 6:59/km.
  Average heart rate 127 bpm. »
- **meaning** (`meaning.hr_without_intensity_with_pacing`) :
  observations de comparaison historique + « Only 1 comparable earlier session(s)
  were found, which is below the 2 needed to read any difference as progression. »
  + « The training-versus-race nature of these sessions is not recorded, which
  limits the comparison. » + réserve d'intensité en clôture.
- **advice** (`advice.hr_without_intensity`) :
  conseil zones **suivi** de « Recording kilometre splits would also let the pace
  distribution of this session be analysed. »

Les deux analyses sont bien différentes et spécifiques ; aucune fraction, zone
ou nature de séance n'est inventée pour B, et l'intensité n'est déduite d'aucune
FC moyenne.

---

## 7. Résultats exacts des tests exécutés

Environnement : Python 3.12.3, dépendances installées depuis
`backend/requirements.txt` **sauf** `litellm` et `emergentintegrations`
(non téléchargeables depuis ce bac à sable).

```
backend$ python -m pytest tests/test_workout_analysis_v2.py -q
57 passed, 14 warnings in 1.92s
```

```
backend$ python -m pytest tests/test_rag_enrichment.py tests/test_idor_integration.py \
    tests/test_rag_endpoints.py tests/test_detailed_analysis.py \
    tests/test_pr211_coach_llm_cleanup.py tests/test_idor_authorization.py \
    tests/test_mobile_workout_analysis.py -q
1 failed, 63 passed, 14 warnings in 2.37s
```

Le seul échec,
`test_pr211_coach_llm_cleanup.py::test_server_coach_analyze_no_hr_speed_vma_exposure`,
est **pré-existant** : il échoue à l'identique sur la base `copilot/dev` sans les
modifications de cette PR (vérifié par `git stash`).

```
frontend$ CI=true npx craco test --watchAll=false --forceExit \
    --testPathPattern "workout-analysis-v2-pages"
Tests: 5 passed, 5 total
```

Aucun test susceptible de se connecter à Redis ou à des workers réels/partagés
n'a été exécuté.

---

## 8. Tests restant à effectuer dans Emergent

- Suite backend complète (les modules dépendant de `litellm` /
  `emergentintegrations` n'ont pas pu être installés ici).
- Tous les tests Redis / workers / SSE / scheduler : **non exécutés**.
- Validation sur de véritables séances Garmin : fractions réelles, `hr_drift`
  réel, dénivelé et cadence réels, et vérification des libellés FR/ES dans
  l'interface mobile.
- Vérification du coût de la requête historique élargie à 180 jours sur une base
  de production (index `user_id` + `type` + `date`).

---

## 9. Risques et limites résiduels

- **Fenêtre historique élargie** : la requête `workouts` passe de 14 à 180 jours
  (toujours plafonnée à 200 documents). Le volume lu augmente ; à surveiller
  côté performance sur les gros comptes.
- **Tolérance ±30 %** reprise de l'ancien moteur : pertinente sur les fixtures,
  mais elle reste large pour les très longues distances. Le champ
  `comparison.similar.distance_tolerance_pct` l'expose pour un réglage ultérieur.
- **Nature entraînement/compétition** : aucune métadonnée de course n'existe
  aujourd'hui sur les documents `workouts`. La séparation est donc implémentée
  mais inactive en pratique, et la limite `session_nature_unknown` est affichée
  systématiquement.
- **Unité de `hr_drift`** : interprétée en bpm, conformément à l'ancien
  `rag_engine`. À confirmer sur données Garmin réelles.
- **Textes plus longs** : `meaning` peut atteindre plusieurs phrases ; le rendu
  mobile doit être vérifié visuellement.
- **Le Coach n'est pas réparé** : la restauration du contexte conversationnel
  appartient à la PR suivante. La validation finale doit être faite par Emergent
  sur de véritables séances Garmin.
