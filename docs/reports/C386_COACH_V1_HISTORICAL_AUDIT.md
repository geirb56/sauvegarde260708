# C386 — Audit historique vérifié du Coach V1 — PR #377

## 1. Périmètre, méthode et conclusion

Audit statique corrigé le 29 octobre 2026 ; remplace le rapport partiel initial.

- **H — historique effectivement consulté :** `9b7947ec2e1bcd40d520b775f6d4f14a5ef4bcff`.
- **C — base cible et HEAD applicatif comparé :** `b80bfb174a0e64150b597503e79835a11bf9079d`.
  `git ls-remote origin refs/heads/copilot/dev` confirme ce SHA pour `copilot/dev`.
- **HEAD documentaire avant correction :** `39ad1c2bf3d9615b68ce39e9847657270352a392`,
  sur la branche de la PR #377 ; aucun changement de branche ni nouvelle PR.
- Historique récupéré par `git fetch` puis `git fetch --unshallow` ;
  lecture des blobs avec `git show`, recherche des appels avec `git grep`,
  comparaison des commits et des parents de merge. Aucun module applicatif importé.
- **Seul fichier modifié :** `docs/reports/C386_COACH_V1_HISTORICAL_AUDIT.md`.
  Tests applicatifs/build/lint non exécutés : documentation seule et aucun
  appel LLM, Garmin ou MongoDB autorisé. Contrôles documentaires : références
  Git, plages de lignes, diff et secrets ; pas de validation runtime.

**Résultat central :** H possède plusieurs Coach distincts. Le chat
`/coach/analyze` appelle directement le LLM **sans RAG**. En revanche,
`/rag/workout/{id}` et `/rag/weekly-review` transmettent une sélection de
résultats locaux au LLM via `coach_service`. Le retrait de ces derniers est
réel ; il n'est pas le retrait du Coach conversationnel. Les capacités
factuelles et la recherche de séances similaires ont ensuite été réintroduites
dans V2, puis accessibles au chat. **GO pour réutiliser l'existant ;
HOLD pour un rollback V1 ou une promesse de qualité retrouvée sans évaluation.**
Preuves détaillées ci-dessous, sans recours aux anciens rapports comme preuve primaire.

### Convention de lecture des références

Les liens **H-** et **C-** en fin de document pointent vers des fichiers figés
aux deux SHA ci-dessus. Chaque mention donne les lignes du fichier à ce SHA.
Les liens de commits renvoient aux diffs réellement inspectés. « V1 » désigne
ici le snapshot H demandé, pas toutes les versions antérieures du produit.

## 2. Les sept fichiers historiques : présence et interfaces

**Tous les sept existent à H**, vérifiés par `git cat-file` et `git show`.
À C, seuls `analysis_engine.py` et `rag_engine.py` sont absents.
`chat_engine.py` et `knowledge_base.json` sont strictement inchangés entre H et C
(`git diff H C --` sur ces deux chemins ne produit aucun delta).

### Entrées HTTP et orchestration (`server.py`)

Périmètre de l'inventaire : fonctions Coach/RAG/dashboard et leurs auxiliaires,
pas les routes de paiement ou de synchronisation étrangères à cet audit.
Toutes les routes ci-dessous portent le préfixe `/api`.

| Fonctions publiques à H, paramètres utiles | Données et appels entrants → sorties |
|---|---|
| `analyze_with_coach(request: CoachRequest, user)` → `process_coach_message(*, request, user)` | `POST /coach/analyze` ; message, langue, `workout_id`, utilisateur authentifié → contexte, historique, LLM → `CoachResponse(response, message_id)` ; [H-S] L1756–1762, L1895–2059. |
| `get_mobile_workout_analysis(workout_id, language="en", user)` ; `get_detailed_analysis(...)` | GET `/coach/workout-analysis/{id}` et `/coach/detailed-analysis/{id}` ; 100 workouts de l'utilisateur, baseline → analyse locale, traduction éventuelle → résumé/signaux/insight/guidance ou cartes détaillées ; [H-S] L2685–2885. |
| `get_rag_dashboard(user)` ; `get_rag_weekly_review(user, language="fr")` ; `get_rag_workout_analysis(workout_id, user, language="fr")` | GET `/rag/dashboard`, `/rag/weekly-review`, `/rag/workout/{id}` ; workouts, digests et objectif → générateurs RAG, enrichissement LLM seulement pour bilan/séance → JSON avec `rag_summary`, faits, tips, provenance et indicateur LLM selon route ; [H-S] L2458–2582. |
| `get_weekly_review(user, language="en")` ; `get_adaptive_guidance(request, user)` | GET `/coach/digest`, POST `/coach/guidance` ; workouts courants/précédents → `analysis_engine.generate_weekly_review` → bilan ou guidance, persistés ; [H-S] L2102–2192, L2342–2423. |
| `get_dashboard_insight(language="en", user)` ; `get_stats(user)` | GET `/dashboard/insight`, `/stats` ; activités Garmin adaptées au domaine → agrégats ; le premier ajoute la phrase locale `generate_dashboard_insight` ; [H-S] L1645–1753. |
| `get_conversation_history(user, limit=50)`, `clear_conversation_history(user)`, `get_messages(user, limit=20)` ; `get_latest_guidance(user)`, `get_latest_digest(user)`, `get_digest_history(user, limit=10, skip=0)` | Historique/effacement des conversations ou lecture des productions stockées, pas de génération LLM ; `/messages` est une lecture legacy des mêmes conversations ; [H-S] L2067–2099, L2204–2231, L2426–2453. |
| `calculate_baseline_metrics(workouts, current_workout, days=14)` ; `calculate_mobile_signals(workout, baseline)` | Appelées par les analyses locales ; même sport, séances strictement antérieures sur 14 jours pour la baseline → moyennes/écarts, cartes intensité/volume/type ; [H-S] L673–777, L2597–2682. |
| `calculate_review_metrics(workouts, baseline_workouts)` ; `generate_review_signals(workouts, baseline_workouts)` | Appelées par `/coach/digest` → métriques/comparaison et signaux ; [H-S] L2234–2372. |

### Modules métier et rédaction

| Composant, fonctions publiques et paramètres à H | Appels entrants, données réellement utilisées et sorties |
|---|---|
| `analysis_engine.generate_session_analysis(workout, baseline=None, language="en")` | Appelée par les deux routes locales de séance. Distance, durée, allure, FC, zones, cadence → `summary`, `execution`, `meaning`, `recovery`, `advice`, `metrics`. **`baseline` et `language` ne sont pas exploités dans le corps** ; branche FC/zones ou structure ; tirages de templates, pas LLM. [H-A] L370–501. |
| `analysis_engine.generate_weekly_review(workouts, previous_week_workouts=None, user_goal=None, language="en")` | Guidance et digest : volumes, fréquence, zones moyennes, comparaison de volume, objectif daté → textes, métriques, signaux ; templates anglais, horloge et aléatoire ; [H-A] L508–674. |
| `analysis_engine.generate_dashboard_insight(week_stats, month_stats, recovery_score=None, language="en")` | `/dashboard/insight` : utilise fréquence/volume de semaine et récupération, pas `month_stats` ni `language` → phrase aléatoire ; [H-A] L681–721. |
| Utilitaires publics d'`analysis_engine` | `has_hr_data(workout)` → bool ; `calculate_intensity_from_zones(zones)` → catégorie/None ; `get_dominant_zones_label(zones)`, `get_intensity_qualifier(intensity)` → libellés ; `calculate_session_type_structural(distance_km, duration_min)` → long/short/medium ; `format_duration(minutes)`, `format_pace(pace_min_km)`, `pick(templates)` → chaînes. Appelés par les générateurs, aucune récupération externe ; [H-A] L254–363. |
| `rag_engine.load_knowledge_base()` ; `retrieve_similar_workouts(current_workout, all_workouts, limit=3)` ; `retrieve_previous_bilans(bilans, weeks=4)` ; `retrieve_relevant_tips(category, context)` | Chargement JSON local à l'import ; filtrage/tri de listes fournies par les routes ; choix aléatoire de conseils. Aucun embedding, index vectoriel, requête documentaire distante ou LLM ; [H-R] L13–24, L437–496. |
| `rag_engine.calculate_metrics(workouts, period_days=7)` ; `detect_points_forts_ameliorer(metrics, prev_metrics=None)` | Appelées par les générateurs RAG → agrégats et deux listes de jugements ; périodes ancrées sur la dernière séance et comparaisons parfois fondées sur des tranches de listes ; [H-R] L499–673. |
| `rag_engine.generate_dashboard_rag(workouts, bilans=None, user_goal=None)` ; `generate_weekly_review_rag(workouts, previous_bilans=None, user_goal=None)` ; `generate_workout_analysis_rag(workout, all_workouts=None, user_goal=None)` | Appelées par leurs trois routes `/rag/*` → dictionnaires `summary`, faits, points forts/faibles, tips ; séance : comparaison et `rag_sources`. `bilans` est inutilisé dans le dashboard ; `prev_bilans` est sélectionné mais non consommé dans le bilan ; `user_goal` n'est pas utilisé par les générateurs bilan/séance. [H-R] L680–935, L942–1275. |
| `llm_coach.enrich_chat_response(user_message, context, conversation_history, user_id="unknown")` | Route chat directe et wrapper de service → JSON canonique, question et historique → `(texte ou None, succès, métadonnées)` ; [H-L] L111–146. |
| `llm_coach.enrich_weekly_review(stats, user_id="unknown", language="fr")` ; `enrich_workout_analysis(workout, user_id="unknown", language="fr")` | Appelées par `coach_service.weekly_review/analyze_workout` → formatage des champs non vides et prompts dédiés → même triplet ; `_call_gpt` assure transport, timeout et nettoyage ; [H-L] L149–245. |
| `coach_service.analyze_workout(workout, rag_result, user_id=None, language="fr")` ; `weekly_review(rag_result, user_id=None, language="fr")` | Routes RAG séance/bilan → cache, sélection de faits du résultat RAG, LLM ; sinon `rag_result.summary` → `(summary, used_llm)` ; [H-CS] L137–263. |
| `coach_service.chat_response(message, context, history, user_id, workouts=None, user_goal=None)` | Wrapper LLM sans cache → triplet ; `workouts/user_goal` non utilisés. **Aucun appel entrant de la route chat** : elle appelle `llm_coach` directement ; [H-CS] L266–304, [H-S] L2025–2031. |
| `coach_service.generate_dynamic_training_plan(db, user_id, sessions_override=None)` | Routes `/training/plan`, `/training/refresh`, `/training-plan`, `/training/dynamic-plan` : préférences, cycle, profil, activités → assemblage Training V2 et plan runtime, cache et mises à jour de cycle ; pas de LLM et pas de maillon RAG/chat. [H-CS] L578–902 ; [H-S] L3400–3452, L3517–3522. |
| `coach_service.get_metrics()`, `reset_metrics()`, `clear_cache()`, `get_cache_stats()` | Routes diagnostics `/metrics`, `/metrics/reset`, `/cache/clear`, `/cache/stats` → compteurs ou état/effacement de caches ; [H-CS] L72–86, L909–946 ; [H-S] L5214–5242. |
| `chat_engine.load_knowledge_base()`, `detect_intent(message)`, `fill_template(template, context)`, `generate_response(message, context, category=None)`, `get_personalized_suggestions(category, context, num_suggestions=4)` | JSON chargé mais moteur de réponse fondé sur mots-clés/templates/context ; texte et suggestions aléatoires, tips lus dans **`context.rag_tips`**, pas récupérés par le générateur. Aucune référence entrante trouvée hors de ce module dans le backend de production H. [H-CH] L13–25, L1427–1545, L1891–2068, L2311–2387. |
| `knowledge_base.json` | Objet catégories → `description` et liste `tips`, aucune fonction ; effectivement chargé par `rag_engine` et `chat_engine`. Le RAG utilise les tips ; aucun chargement dans `llm_coach` ou le contexte canonique. [H-KB] L1–287 ; [H-R] L478–496. |

**Correction importante du premier rapport :** « local » ne signifie pas
« déterministe » ici : `analysis_engine`, `rag_engine` et `chat_engine` utilisent
`random`. La base et le module chat inchangés ne constituent pas une capacité
conversationnelle perdue : ils étaient déjà déconnectés du chat à H.

## 3. Pipelines historiques réels

### A — Conversation, sans RAG

`POST /api/coach/analyze`
→ `analyze_with_coach` → `process_coach_message`
→ droits/quota
→ **5 derniers messages de l'utilisateur, toutes séances confondues**, remis en ordre
→ activités Garmin stockées (plafond 2 000, fenêtre 90 jours pour charge/contexte),
  métriques quotidiennes stockées (30 derniers documents si connecté), objectif
→ `build_training_load`, readiness canonique, `predict_races`,
  `load_canonical_training_paces`, Today et Week
→ séance sélectionnée dans `workouts` si ID fourni
→ `build_coach_context_v2(...).model_dump(...)`
→ sauvegarde du message
→ **`llm_coach.enrich_chat_response` directement**
→ `_call_gpt` → sauvegarde du texte → `CoachResponse`, sinon HTTP 503.

Preuves : [H-S] L1895–2059 ; [H-L] L111–236. Ces lectures de collections
décrivent le code, elles n'ont pas été exécutées pendant l'audit.

Le LLM ne reçoit **pas tous les documents Garmin chargés** : le contexte
sérialise objectifs, états Training, agrégats 7/30 jours, prescription,
readiness/charge/allures/prédictions. Le détail sélectionné est limité à
ID/nom/distance/durée/FC/zones/**5 km_splits** ; pas de `recent_workouts`,
pas d'analyse locale/RAG embarquée. [H-CTX] L21–31, L296–327, L397–467.
Aucun `retrieve_*`, `rag_engine`, `knowledge_base` ni `chat_engine` dans ce
chemin. Le commentaire « cascade » à l'import du service ne change pas cet appel réel.

### B — Analyse locale de séance, indépendante du chat

`GET /api/coach/workout-analysis/{id}` ou `/coach/detailed-analysis/{id}`
→ workouts de l'utilisateur (100 plus récents)
→ `calculate_baseline_metrics(..., days=14)` : même sport et antériorité
→ `calculate_mobile_signals` pour la première route
→ `analysis_engine.generate_session_analysis(workout, baseline, language)`
→ branche zones/FC ou structure → templates de commentaire/récupération/conseil
→ `localization.localize_fields` → réponse mobile ou cartes.

Preuves : [H-S] L2685–2885 ; [H-A] L370–501.
**Nuances vérifiées :**

- `baseline` est passé au générateur mais non lu ; les routes l'utilisent
  séparément dans les signaux/écarts. Les objets `workout_summary` et
  `baseline_summary` construits L2704–2729 ne sont transmis à aucun LLM.
- Le texte chiffré se trouve notamment dans **`execution`** ; la réponse mobile
  n'expose pas ce champ et la route détaillée reconstruit sa propre carte
  `execution`. Il est donc faux d'affirmer que toutes ces valeurs étaient
  injectées dans le résumé affiché.
- « NO LLM » qualifie le calcul, pas toute la requête : la localisation
  non anglaise peut appeler `_call_gpt`, avec cache et repli sur le texte
  original ; l'anglais est un no-op. [H-LOC] L39–76.

### C — RAG séance/bilan : récupération locale puis enrichissement partiel

`GET /api/rag/workout/{id}`
→ séance scoped + 100 workouts les plus récents + objectif
→ `generate_workout_analysis_rag`
→ `retrieve_similar_workouts` + mesures/splits/FC/cadence + tips JSON
→ `coach_service.analyze_workout(workout, rag_result, user_id, language)`
→ cache ou `enrich_workout_analysis(workout_stats)`
→ `_call_gpt(SYSTEM_PROMPT_SEANCE, ...)`
→ texte enrichi, sinon résumé local → `rag_summary` et faits séparés.

Preuves : [H-S] L2525–2582 ; [H-R] L942–1275 ; [H-CS] L137–197.

**Sélection des comparables H :** même `type`, distance ±30 %, exclusion de
l'ID courant, tri décroissant par date, **3 résultats**. Aucun cutoff temporel,
aucune fenêtre en jours, aucun filtre course/entraînement : la route fournit
les 100 plus récents, donc une analyse d'ancienne séance peut regarder le futur.
La comparaison utilise **le premier résultat**, ses écarts d'allure et de
ralentissement. [H-R] L437–462, L1021–1048.

**Ce qui atteint réellement le LLM :** distance, durée, FC moyenne/max,
dénivelé, type, zones, `comparison.progression`, points forts/faibles.
La base de connaissances et `tips` ne sont **pas** envoyés au LLM ; ils restent
dans le résumé de repli et les champs HTTP. De plus le service lit
`rag_result.pace_str` et `rag_result.splits_analysis`, alors que le générateur
renvoie `workout.allure` et `workout.split_analysis` : le LLM reçoit donc
`pace="N/A"` et `splits={}` sur cette voie. Pas de transmission du détail
`hr_analysis/cadence_analysis` ni des séances comparables brutes.
[H-CS] L157–179 ; [H-R] L1246–1274.

`GET /api/rag/weekly-review`
→ 50 workouts + 8 digests + objectif
→ `generate_weekly_review_rag`
→ `coach_service.weekly_review`
→ `enrich_weekly_review(stats)` ou résumé local de repli.

Les digests sélectionnés (`prev_bilans`) ne sont ensuite pas utilisés ; les
tips ne sont pas envoyés au LLM. Autre défaut : le service demande
`allure_moyenne/cadence_moyenne/comparison.evolution` alors que le générateur
produit `allure_moy/cadence_moy` et `comparison.vs_prev_week/km_prev/km_current` :
des valeurs par défaut remplacent donc ces informations dans le prompt.
[H-S] L2487–2522 ; [H-R] L612–620, L796–814, L924–935 ; [H-CS] L200–263.

`GET /api/rag/dashboard`
→ 100 workouts + 8 digests + objectif → `generate_dashboard_rag`
→ templates/métriques/tips → JSON, **sans enrichissement LLM**.
Les tips sont sélectionnés par catégorie, puis ratio/cadence, avec `random`,
pas par recherche sémantique. [H-S] L2458–2484 ; [H-R] L478–496, L680–789.

### D — Synthèses hors RAG et preuve d'affichage

`/coach/digest` et `/coach/guidance` appellent le bilan **local**
`analysis_engine.generate_weekly_review`, pas le service LLM.
`/dashboard/insight` ajoute une phrase locale aux agrégats Garmin.
[H-S] L2102–2192, L2342–2423, L1645–1686.

Ce n'était pas seulement du code dormant : `WorkoutDetail.jsx` lançait les
**trois** requêtes séance locale/détaillée/RAG, affichait le résumé RAG
(quatre premières lignes), la comparaison et des points forts/faibles.
Son bouton Coach ouvrait seulement `/coach`, sans ID.
[H-UI] L375–398, L687–859. C'est une source démontrée de richesse de la
fiche séance ; ce n'est pas une preuve que le chat consommait ce RAG.

## 4. Pipelines actuels de `copilot/dev`

### Conversation

`POST /api/coach/analyze` → `process_coach_message`
→ droits/quota ; refus explicite d'analyse si non autorisée, 404 si séance introuvable
→ `load_scoped_workout_analysis_v2` si séance autorisée sélectionnée
→ historique **scoped par utilisateur + workout_id**, 5 derniers messages
→ autorités Training/observations comme à H
→ `build_coach_context_v2(..., workout_analysis=...)`
→ **`build_llm_coach_context`** (allures affichables, permissions, séparation temporelle)
→ `llm_coach.enrich_chat_response` → LLM → persistance/réponse ou 503.
[C-S] L1879–2099 ; [C-CTX] L321–387, L787–1022.

`recent_workouts` apporte jusqu'à **30 observations sur 30 jours**, fenêtre
ancrée sur la séance sélectionnée si applicable ; antériorité filtrée avec
précision disponible et couverture explicite. `workout_detail.analysis`
embarque le payload V2, donc aussi comparaison/faits/synthèse quand disponibles.
Le chat ne charge toujours pas la base de tips ni les prototypes hybrides.
[C-CTX] L27–78, L638–661, L854–988, L1021.
La navigation transmet désormais l'ID : [C-UI] L145.

### Fiche séance : V2 puis V3, pas le chat

`GET /api/coach/workout-analysis/{id}`
→ `load_scoped_workout_analysis_v2`
→ workout scoped + enrichissement depuis les activités/phases **en cache**
→ candidats antérieurs, même sport, 180 jours, maximum 200 lus
→ `build_workout_analysis_v2`
→ faits/mesures, phases, `comparison.similar`, `coach_language`,
`session_synthesis`. Pas de LLM dans ce calcul.
[C-S] L2132–2154 ; [C-V2S] L351–413 ; [C-V2] L2187–2260.

Le retrieve V2 conserve distance ±30 %, exclut la séance courante et les
natures explicitement incompatibles ; il exige l'antériorité, retient jusqu'à
5 références et calcule populations/limites **par métrique**. Une différence
descriptive reste possible quand la comparabilité est insuffisante.
[C-V2] L23–27, L875–1031. Ce n'est pas une suppression de tout l'historique.

`GET /api/coach/workout-intelligence/{id}`
→ chargeur V3 réutilisant V2 + contexte de prescription historique
→ `build_workout_intelligence_v3`
→ `generate_narrative_coach_v3` : rendu local par défaut ; option LLM
sélectionnant toutes les assertions et variantes approuvées, **sans prose libre**.
[C-S] L2157–2182 ; [C-V3S] L143–229 ; [C-N] L612–712.
`WorkoutDetail` demande V2 et V3 et privilégie la narration V3 quand disponible,
avec détails V2 ; ce rendu ne passe pas par le prompt du chat.
[C-UI] L120–143, L190–196, L266–268.

`/dashboard/insight` et `/stats` servent les agrégats semaine/mois/RunIndex,
sans ancienne phrase de coach ni bilan RAG. Les anciennes routes RAG,
guidance et digest ne sont plus définies. [C-S] L1638–1737 ;
retraits vérifiés dans les commits de la section suivante.

## 5. Différences démontrées et commits responsables

| Fonctionnalité | V1 historique H | Actuel C | Changement responsable vérifié |
|---|---|---|---|
| Analyse contextualisée | Trois réponses locales/détaillée/RAG, dont enrichissement LLM de séance ; limites de transmission décrites §3. | V2 factuelle déterministe, puis V3/narration contrôlée sur fiche ; chat libre séparé. | **#287**, merge `c49c6ca` : `4ef8d40` remplace les routes et l'UI par V2. Dans ce merge, `_build_summary/_build_meaning/_build_advice` produisent des templates sans valeurs injectées (L522–581). **#304**, `70caa06`, réintroduit faits chiffrés et historique ; enrichissements ultérieurs ci-dessous. |
| Comparaison historique | Baseline locale 14 jours ; RAG ±30 %, 3 résultats sans antériorité garantie ; plus récent utilisé. | Baseline conservée et `comparison.similar` 180 jours/5 références, populations et limites explicites. | #287 retire le retrieve RAG du chemin séance, ne garde que baseline 14 jours ; **#304** `70caa06`, `24086e1`, `6d4fc65` restaurent recherche/texte/couverture. [C-V2] L875–1031. |
| RAG | Récupération locale de séances/tips/bilans ; séance et bilan partiellement envoyés au LLM, jamais le chat. | Module et routes retirés ; capacité de recherche réimplémentée dans V2 ; base JSON/chat à templates conservés mais non câblés. | **#287** retire `/rag/workout` ; **#290**, `794d77cb`, retire `rag_engine.py`, `/rag/dashboard`, `/rag/weekly-review`, guidance/digest. |
| Conseils personnalisés | Templates et prompts séance/bilan prescrivent la prochaine sortie, volume, récupération, cadence. | Observations/limites de séance ; le chat explique seulement Training Today/Week. Pas de retour du bilan LLM autonome. | #290 `5e917a9` retire `analysis_engine.py`, le service/prompt bilan ; **#294** `968a604` retire service/prompt séance déjà sans route. **#304** `3f11f5d` rend explicitement la V2 non prescriptive. |
| Conversation LLM | `process_coach_message` → `enrich_chat_response` ; contexte déjà Training V2. | Même route/fonction, même modèle, rédaction encore libre ; données factuelles supplémentaires et permissions. | Ni #287 ni #290 ne supprime le chat. **#305** `106d7ee`, `be6f37b`, `163e10d` ajoutent contexte récent, analyse V2 scoped, observations Garmin et navigation avec ID. |
| Mémoire conversationnelle | 5 messages lus globalement par utilisateur ; 4 × 200 caractères envoyés ; persistance sans mémoire longue. | Même budget, mais scope général/séance et protection après perte de droits. | **#310** `49a43b7` introduit le scope par `workout_id` ; **#325** `c9720f9` filtre l'historique assistant selon droits. Réduction de continuité inter-séances démontrée ; intention d'isolation, pas preuve d'une baisse qualitative globale. |
| Synthèses dashboard/hebdomadaires | Phrase dashboard locale, digest/guidance locaux et bilan RAG/LLM distinct. | Agrégats toujours présents ; ces anciens textes/endpoints ne sont pas rétablis par V2 séance. | **#288** `715ef1c` retire la phrase/autorité dashboard ; **#290** retire les autres synthèses. Ne pas annoncer leur restauration au motif que V2 séance existe. |

### Chaîne de commits inspectés

- [#287 — `c49c6ca`][p287] : disparition des trois analyses parallèles au profit
  du contrat V2. **Les fichiers moteurs ne sont pas supprimés dans cette PR**.
- [#290 — `8eb3a08`][p290] : [`794d77cb`][d-rag] supprime le RAG et les routes
  restantes ; [`5e917a9`][d-analysis] supprime l'analyse locale et l'enrichissement bilan.
- [#294 — `968a604`][d-workout] : nettoyage du service et prompt d'analyse séance.
- [#304 — `933ab88`][p304] : [`70caa06`][restore-v2] restaure le retrieve et la
  rédaction factuelle ; `3f11f5d`, `24086e1`, `6d4fc65` neutralisent les conseils
  prescriptifs et alignent les populations par métrique.
- [#305 — `8ecffed`][p305] : [`106d7ee`][restore-chat] et correctifs
  `be6f37b`/`163e10d` réintroduisent des observations et V2 dans le contexte chat.
- [#310 — `49a43b7`][grounding] : projection LLM, garde-fous et scope de mémoire.
  [#311 — `ef8773f`][voice] : directives initial/suivi/Training/général et une
  seule réserve naturelle utile, pas une suppression de la rédaction libre.
- [#325 — `c9720f9`][access] : entitlement séance et provenance de l'historique.
  #322 `963357d` : phases depuis le cache ; #340 `4c2c6d6` : observations
  factuelles structurées ; #341 `da34ea8` : Coach Language ; #349/#350 :
  comparabilité/structure ; #351 `91c7d64` : synthèse de séance.
  Présence et assemblage actuels : [C-V2] L2187–2260.
- V3/narration : #352/#355/#358 ajoutent le chemin distinct visible dans
  [C-V3S] L143–229 et [C-N] L644–695. **Modifier le prompt du chat ne
  modifierait pas à lui seul cette narration affichée sur la fiche.**

## 6. Comparaison des prompts et origine plausible de la qualité

| Dimension | Historique H → actuel C | Conclusion permise |
|---|---|---|
| Rôle système du chat | Coach expert/bienveillant ; « Training V2 decides, Coach explains » **déjà présent à H**, comme l'interdiction de nouvelle prescription. [H-L] L32–67 ; [C-L] L32–78. | L'autorité Training n'est pas une restriction nouvelle de #287/#290. |
| Modèle/transport | `gpt-4.1-mini`, fournisseur OpenAI via Emergent, timeout 15 s, nouvelle session fournisseur par requête aux deux snapshots. [H-L] L21–25, L177–236 ; [C-L] L21–25, L209–275. | Pas de preuve d'une régression par changement de modèle ; aucune mémoire serveur fournisseur durable démontrée. |
| Liberté de formulation | Prose libre aux deux versions du chat. H demandait 3–5 phrases, sans listes ; C ajoute les modes de présentation. | Ne pas confondre chat libre et catalogue de variantes V3, seul ce dernier est fermé. |
| Données de personnalisation | H : agrégats + détail très limité sans analyse ; C : observations récentes, détail enrichi et V2, permissions. [H-CTX] L21–31, L397–467 ; [C-CTX] L27–78, L321–387, L854–1021. | Le chat actuel dispose de plus de faits sélectionnés, pas de moins par principe ; aucun accès libre à Garmin/MongoDB depuis le LLM. |
| Mémoire et longueur | **H et C : 4 messages × 200 caractères ; nettoyage à 700 caractères.** [H-L] L125–131, L261–276 ; [C-L] L162–168, L291–306. | Ces limites peuvent couper une explication, mais ne sont pas une régression entre ces snapshots. Seul le scope change (§5). |
| Garde-fous scientifiques | H chat : absence/confidence/non-invention ; prompts séance/bilan autonomes demandent « Advice for next run/week ». C chat : interdictions détaillées de causalité/progression depuis FC/allure brutes, allures verbatim, distinction contexte actuel/historique. [H-L] L69–90 ; [C-L] L62–78, L178–187. | Les anciens prompts séance/bilan encourageaient une prescription concurrente. Le texte de prudence actuel est plus long ; son effet sur le naturel n'est pas mesuré. |
| Manques d'information | H : signaler champ indisponible/faible confiance ; C : signaler celui **nécessaire à la réponse**, pas toute section vide ; une réserve utile maximum dans les directives. [H-L] L141–144 ; [C-L] L95–141, L186–190. | #311 tente déjà de réduire le ton « rapport ». Recommander simplement cette même instruction serait redondant. |

**Composant identifié :** la prose conversationnelle à H provenait bien de
`llm_coach.enrich_chat_response`, pas du chat à templates ni du RAG.
La fiche personnalisée disposait, elle, du tandem
`rag_engine.generate_workout_analysis_rag` → `coach_service.analyze_workout`
→ `llm_coach.enrich_workout_analysis`, en plus des cartes locales affichées.
La suppression de ce résumé libre et des comparaisons affichées initialement
est un changement produit prouvé par les appels et l'UI (§3–5).

**Limite de causalité :** le code ne prouve pas que chaque ancien texte était
meilleur. Aucun corpus de réponses réelles, trace de fournisseur ni comparaison
à données identiques n'est évalué ici. Les instructions répétées de prudence,
le scope inter-séances et la narration fermée V3 sont des mécanismes susceptibles
d'affecter la perception, **pas des causes qualitatives établies**. Aucun gain
ne peut être promis en les modifiant.

## 7. Risques à ne pas réintroduire

1. **Physiologie sans preuve :** `has_hr_data` accepte une seule FC moyenne >50 ;
   la branche zones peut ensuite retomber sur des textes d'effort « modéré ».
   Conseils de seuil/surcharge/récupération sans provenance de zones, et type
   easy/hard construit depuis FC relative + volume : [H-A] L254–296, L412–455 ;
   [H-S] L2619–2672. Préserver les abstentions actuelles, pas ces raccourcis.
2. **Fausse progression, causalités, aléatoire :** amélioration d'allure
   dashboard tirée à pile ou face ; simple existence de deux allures assimilée
   à progression ; dérive FC attribuée à hydratation/échauffement.
   [H-R] L652–658, L710–713, L1001–1008, L1078–1084.
   Le chat dormant invente un décrochage de 5–15 % : [H-CH] L1901.
   Aucun de ces comportements ne doit revenir sous couvert de « richesse ».
3. **Prescription concurrente :** volume cible automatique `km × 1.05`,
   ajouter une séance/intensité, prochaine sortie prescrite par templates/LLM.
   [H-R] L880–893, L1165–1178 ; [H-A] L445–481 ; [H-L] L69–90.
   Training doit rester seul prescripteur.
4. **Lookahead, défauts et valeurs manquantes :** retrieve H sans antériorité ;
   moyennes/périodes approximatives et defaults ratio 1/cadence 180 ;
   clés incompatibles entre service et générateur (§3). Absence de variabilité
   convertie en 0 puis « Stable » : [H-S] L2829–2832. Préserver `None != 0`.
5. **Isolation/cache et données :** le cache bilan H est process-global, indexé
   par langue/nombre/distance/durée, sans `user_id` ni contenu complet du bilan ;
   celui de séance omet également utilisateur, historique et plusieurs mesures.
   Risque de réutilisation de prose hors contexte, notamment entre bilans de
   mêmes totaux ; ne pas recopier ces caches. [H-CS] L103–115, L148–155,
   L210–224. Aucun accès aux données réelles ni test d'exploitation effectué.
   Historique et question sont insérés textuellement dans le prompt : ne pas
   traiter une instruction utilisateur comme une autorité de faits ou de droits.
   [H-L] L125–146 ; filtres actuels : [C-CTX] L321–387.
6. **Base et dépendances legacy :** tips non sourcés sur « toxines », cadence
   optimale universelle ou sommeil avant minuit ; pas une base scientifique
   validée : [H-KB] L5–44, L167–179. Le transport dépend
   d'`emergentintegrations==0.1.0`, `openai==1.99.9`, avec roue LiteLLM externe
   épinglée ; ces lignes de dépendances sont inchangées entre H et C.
   [H-REQ] L22–23, L56–67 ; [C-REQ] mêmes lignes.
   C'est une dette d'intégration à examiner séparément, **pas une preuve de
   CVE, d'obsolescence fournisseur ou d'incompatibilité** ; aucun avis externe,
   environnement installé ou service n'a été testé. Restaurer les moteurs
   retirés n'apporterait donc pas un transport LLM nouveau ou plus fiable.

## 8. Restauration minimale, par priorité — aucune implémentation

**P0 — Ne pas restaurer un moteur déjà présent.** Le Coach conversationnel
existe toujours et reçoit déjà V2 via #305. La recherche comparable et les
faits séance sont restaurés ; `chat_engine`/`knowledge_base` ne sont pas le
chaînon manquant du chat. Garder routes, flags, calculs V2/V3 et autorité Training
inchangés. Preuves : §3–5, [C-S] L2025–2067, [C-V2] L2187–2260.

**P1 — Distinguer la surface à améliorer avant de changer une instruction.**
Pour le chat, réutiliser la projection actuelle et, si une insuffisance est
confirmée, faire privilégier les conclusions **déjà autorisées**
`workout_detail.analysis.session_synthesis/coach_language` et les différences
descriptives de `comparison.similar`, plutôt qu'ajouter des calculs ou un RAG.
Ces champs sont déjà assemblés et sérialisés ; le prompt évoque V2 et les
comparables mais ne nomme pas spécifiquement la synthèse. [C-V2] L2231–2259 ;
[C-CTX] L321–387, L1021 ; [C-L] L108–128, L178–187.
Préserver une réponse à la question, les formulations libres et les permissions ;
ne pas supprimer les garde-fous pour obtenir un ton plus affirmatif.
Pour la fiche séance, une modification du seul prompt chat serait sans effet
sur le rendu prioritaire V3 : son arbitrage de présentation est distinct (§4).

**P2 — Instructions/mémoire seulement si un manque est démontré.**
Les modes naturels et la réserve unique existent déjà (#311).
L'historique à 4 × 200 et le plafond à 700 sont anciens ; les augmenter serait
une amélioration nouvelle, pas une restauration prouvée.
Ne pas rétablir l'historique global H pour contourner l'isolation des séances
ou les droits. Évaluer une éventuelle continuité explicite et bornée
séparément, sans remettre les données d'une autre séance dans la réponse.
Preuves : §5–6, [C-S] L1888–1897, L1963–1968.

**P3 — Ne pas ressusciter les bilans/conseils autonomes par défaut.**
Ils ont bien disparu ; V2 séance ne les remplace pas. Si leur retour devient
un objectif produit, réutiliser les faits/agrégats et la prescription servie,
pas les anciens ratios, templates ou prompts prescriptifs. Aucun nouveau
moteur n'est justifié par cet audit.

### Réponses directes et verdict

1. **Le Coach conversationnel V1 existe-t-il encore ? Oui**, filiation
   route → contexte → `enrich_chat_response`, avec contexte enrichi et contrôlé.
2. **Le RAG V1 participait-il à ses réponses ? Non pour le chat ;
   oui partiellement pour les résumés LLM des endpoints RAG séance/bilan.**
   Les tips JSON n'étaient pas envoyés au LLM ; certains champs étaient mal câblés.
3. **Qu'a-t-on supprimé ?** Les anciennes routes et rendus parallèles,
   le résumé LLM dédié séance/bilan, les synthèses/adaptations autonomes et leurs caches.
4. **Qu'a-t-on déjà restauré ?** Les observations chiffrées, la recherche
   comparable bornée, les phases, conclusions/synthèse et leur accès dans le chat ;
   pas les anciens bilans autonomes ni leurs prescriptions.
5. **Modification minimale envisageable ?** Priorité de lecture/rédaction des
   faits déjà servis sur la surface concernée, puis mémoire/longueur seulement
   après preuve de besoin ; aucun retour des inférences V1.
6. **Restaurer du code ?** Pas de justification à remettre
   `analysis_engine.py`, `rag_engine.py` ou les anciens services en production.
   Le câblage chat/V2 existe déjà ; un ajustement ciblé de présentation est
   la première option, non un nouveau moteur.

**GO — audit historique statique et réutilisation des composants existants :
les sept fichiers H et les diffs clés sont effectivement consultés.**
**HOLD — restauration directe et affirmation « qualité V1 retrouvée » :
la richesse de l'ancienne fiche est prouvée, pas la supériorité de ses réponses
ni l'efficacité d'une modification future.**
**Verdict technique : adaptation ciblée nécessaire, pas restauration directe.**
Aucun appel fournisseur ou
exécution applicative n'est nécessaire pour établir cette séparation ; une
évaluation comparative de rédaction reste une étape future distincte,
non réalisée et non autorisée dans cette mission.

## Sources primaires figées

[H-S]: https://github.com/geirb56/sauvegarde260708/blob/9b7947ec2e1bcd40d520b775f6d4f14a5ef4bcff/backend/server.py
[H-A]: https://github.com/geirb56/sauvegarde260708/blob/9b7947ec2e1bcd40d520b775f6d4f14a5ef4bcff/backend/analysis_engine.py
[H-R]: https://github.com/geirb56/sauvegarde260708/blob/9b7947ec2e1bcd40d520b775f6d4f14a5ef4bcff/backend/rag_engine.py
[H-L]: https://github.com/geirb56/sauvegarde260708/blob/9b7947ec2e1bcd40d520b775f6d4f14a5ef4bcff/backend/llm_coach.py
[H-CS]: https://github.com/geirb56/sauvegarde260708/blob/9b7947ec2e1bcd40d520b775f6d4f14a5ef4bcff/backend/coach_service.py
[H-CH]: https://github.com/geirb56/sauvegarde260708/blob/9b7947ec2e1bcd40d520b775f6d4f14a5ef4bcff/backend/chat_engine.py
[H-KB]: https://github.com/geirb56/sauvegarde260708/blob/9b7947ec2e1bcd40d520b775f6d4f14a5ef4bcff/backend/knowledge_base.json
[H-CTX]: https://github.com/geirb56/sauvegarde260708/blob/9b7947ec2e1bcd40d520b775f6d4f14a5ef4bcff/backend/coach_context_v2.py
[H-LOC]: https://github.com/geirb56/sauvegarde260708/blob/9b7947ec2e1bcd40d520b775f6d4f14a5ef4bcff/backend/localization.py
[H-UI]: https://github.com/geirb56/sauvegarde260708/blob/9b7947ec2e1bcd40d520b775f6d4f14a5ef4bcff/frontend/src/pages/WorkoutDetail.jsx
[H-REQ]: https://github.com/geirb56/sauvegarde260708/blob/9b7947ec2e1bcd40d520b775f6d4f14a5ef4bcff/backend/requirements.txt
[C-S]: https://github.com/geirb56/sauvegarde260708/blob/b80bfb174a0e64150b597503e79835a11bf9079d/backend/server.py
[C-L]: https://github.com/geirb56/sauvegarde260708/blob/b80bfb174a0e64150b597503e79835a11bf9079d/backend/llm_coach.py
[C-CTX]: https://github.com/geirb56/sauvegarde260708/blob/b80bfb174a0e64150b597503e79835a11bf9079d/backend/coach_context_v2.py
[C-V2]: https://github.com/geirb56/sauvegarde260708/blob/b80bfb174a0e64150b597503e79835a11bf9079d/backend/workout_analysis_v2.py
[C-V2S]: https://github.com/geirb56/sauvegarde260708/blob/b80bfb174a0e64150b597503e79835a11bf9079d/backend/workout_analysis_v2_service.py
[C-V3S]: https://github.com/geirb56/sauvegarde260708/blob/b80bfb174a0e64150b597503e79835a11bf9079d/backend/workout_intelligence_v3_service.py
[C-N]: https://github.com/geirb56/sauvegarde260708/blob/b80bfb174a0e64150b597503e79835a11bf9079d/backend/narrative_coach_v3.py
[C-UI]: https://github.com/geirb56/sauvegarde260708/blob/b80bfb174a0e64150b597503e79835a11bf9079d/frontend/src/pages/WorkoutDetail.jsx
[C-REQ]: https://github.com/geirb56/sauvegarde260708/blob/b80bfb174a0e64150b597503e79835a11bf9079d/backend/requirements.txt
[p287]: https://github.com/geirb56/sauvegarde260708/commit/c49c6cae4a67b96df4cd8b98340ad52fa4f76480
[p290]: https://github.com/geirb56/sauvegarde260708/commit/8eb3a0879831f41016c8d92e242f6d884c15be82
[d-rag]: https://github.com/geirb56/sauvegarde260708/commit/794d77cbfa4af66963456ef10a3a0b20b8db244c
[d-analysis]: https://github.com/geirb56/sauvegarde260708/commit/5e917a97a8f1974e0d573cd75acaf84eaed5b368
[d-workout]: https://github.com/geirb56/sauvegarde260708/commit/968a604be519c39c2160ec2652818bbdbb9a9854
[p304]: https://github.com/geirb56/sauvegarde260708/commit/933ab88f7bf5d5092b13e54d2ab1bdf5103fea73
[restore-v2]: https://github.com/geirb56/sauvegarde260708/commit/70caa06f2650b5bd2387895e7113c4fb1f504872
[p305]: https://github.com/geirb56/sauvegarde260708/commit/8ecffedc020fd69d5ccb438e501ad038316c9c15
[restore-chat]: https://github.com/geirb56/sauvegarde260708/commit/106d7ee8014cf300522c7a8cb6eb655febe97ae0
[grounding]: https://github.com/geirb56/sauvegarde260708/commit/49a43b75819f2f9fe73ccff34d3cf0b157c2f653
[voice]: https://github.com/geirb56/sauvegarde260708/commit/ef8773fc6bcc48b4861c041fb6b1228704ec61df
[access]: https://github.com/geirb56/sauvegarde260708/commit/c9720f9801465e73f83ddaa362e9733a55ad5fef
