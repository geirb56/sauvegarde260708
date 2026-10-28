# C386 — Coach V1 : audit partiel, preuves historiques insuffisantes

## Périmètre et traçabilité

- Base de cette PR documentaire : `b80bfb174a0e64150b597503e79835a11bf9079d`.
- HEAD du code examiné : `b80bfb174a0e64150b597503e79835a11bf9079d`.
- Branche d'intégration demandée : `copilot/dev` ; ce rapport ne certifie pas
  que sa pointe distante correspond au checkout examiné.
- Référence historique demandée : `9b7947ec`, **non vérifiée**.
- Tests : aucun exécuté ; transcription documentaire sans changement applicatif.
- Aucun appel applicatif LLM, Garmin ou MongoDB effectué pour cet audit.

Ce document enregistre le rapport partiel rendu dans la conversation, à la
demande de l'utilisateur. Il ne constitue pas un audit historique achevé.
Les références de code ci-dessous décrivent uniquement le HEAD examiné ;
les rapports antérieurs restent des sources secondaires.

## 1. Pipeline V1 réel

**Non établi.** Les versions historiques de `server.py`, `analysis_engine.py`,
`rag_engine.py`, `llm_coach.py`, `coach_service.py`, `chat_engine.py` et
`knowledge_base.json` au commit demandé n'ont pas été vérifiées.

Le rapport antérieur mentionne `analysis_engine.generate_session_analysis()`
et `rag_engine.retrieve_similar_workouts()`. Cela ne démontre ni leur câblage
HTTP historique, ni une chaîne « conversation → RAG → analyse → LLM ».

Source secondaire :
[`RUNINDEX_PR303_REPORT.md:14–30`](../../RUNINDEX_PR303_REPORT.md#L14-L30).

## 2. Pipeline au HEAD examiné

### Conversation LLM

`POST /api/coach/analyze`
→ `process_coach_message`
→ droits, quota, historique scoped général/séance
→ contexte Training Today/Week et observations, analyse V2 si séance sélectionnée
→ `build_llm_coach_context`
→ `llm_coach.enrich_chat_response`
→ `_call_gpt`
→ réponse enregistrée.

La route appelle directement `llm_coach`, pas `coach_service.chat_response`.

Sources :
[`server.py:1740–1746`](../../backend/server.py#L1740-L1746),
[`server.py:1915–2096`](../../backend/server.py#L1915-L2096).

### Analyse déterministe de séance — branche distincte

`GET /api/coach/workout-analysis/{id}`
→ `load_scoped_workout_analysis_v2`
→ séance appartenant à l'utilisateur, enrichissement depuis le cache Garmin,
historique et recherche de séances similaires
→ `build_workout_analysis_v2`.

Sources :
[`server.py:2132–2154`](../../backend/server.py#L2132-L2154),
[`workout_analysis_v2_service.py:351–406`](../../backend/workout_analysis_v2_service.py#L351-L406).

### Intelligence V3 — autre branche

`GET /api/coach/workout-intelligence/{id}`
→ réutilisation V2
→ faits V3
→ narration contrôlée.

Le LLM narratif est optionnel : sans activation du drapeau
`C355_NARRATIVE_LLM_ENABLED`, le rendu est déterministe. Lorsqu'il est activé,
il sélectionne des variantes autorisées, sans rédaction libre.

Sources :
[`server.py:2157–2182`](../../backend/server.py#L2157-L2182),
[`workout_intelligence_v3_service.py:192–226`](../../backend/workout_intelligence_v3_service.py#L192-L226),
[`narrative_coach_v3.py:644–695`](../../backend/narrative_coach_v3.py#L644-L695).

### Dashboard et hebdomadaire

`GET /api/dashboard/insight` → agrégats semaine/mois.
`GET /api/stats` → statistiques et `weekly_summary`.
Ces chemins inspectés ne génèrent pas une conversation LLM.

Source : [`server.py:1638–1737`](../../backend/server.py#L1638-L1737).

## 3. Capacités conservées ou absentes

Les statuts suivants sont actuels au HEAD examiné, pas des pertes V1 prouvées.

| Capacité | Constat et preuve |
|---|---|
| Conversation LLM contextualisée | Présente et appelée : `server.py:2025–2067`. |
| Analyse déterministe de séance | Présente, servie par V2 : `workout_analysis_v2_service.py:351–406`. |
| Recherche de séances similaires | Présente dans V2, utilisée par son chargeur : `workout_analysis_v2_service.py:393–405`. |
| `analysis_engine.py`, `rag_engine.py` | Absents du backend examiné ; commits de suppression non vérifiés. |
| `chat_engine.py` et base de connaissances | Présents (`chat_engine.py:13–25`) ; aucun appel trouvé depuis les chemins HTTP inspectés. |
| `coach_service.chat_response` | Présent (`coach_service.py:66–104`), contourné par la route conversationnelle (`server.py:2062–2067`). |
| Synthèses semaine/mois | Agrégats présents (`server.py:1652–1737`) ; ancienne rédaction éventuelle non établie. |

Le nom « RAG » ne démontre ni recherche sémantique ni participation à la
conversation. Faute de lecture du code historique, les catégories « remplacée »,
« supprimée depuis V1 » et les commits responsables ne sont pas établis.

## 4. Origine de la qualité conversationnelle

**Impossible à attribuer au V1 avec les preuves recueillies.**

Au HEAD examiné, la rédaction conversationnelle relève de `llm_coach` :
modèle configuré `gpt-4.1-mini`, prompt de coach et directives de présentation.
Deux limites concrètes existent : quatre messages précédents, tronqués à
200 caractères chacun, et réponse nettoyée à 700 caractères.
Leur responsabilité dans une régression historique n'est pas démontrée.

Sources :
[`llm_coach.py:21–141`](../../backend/llm_coach.py#L21-L141),
[`llm_coach.py:148–190`](../../backend/llm_coach.py#L148-L190),
[`llm_coach.py:291–306`](../../backend/llm_coach.py#L291-L306).

## 5. Risques et plus petite modification envisageable

Ne pas réactiver les anciens templates en bloc. Le `chat_engine.py` conservé
contient des causalités automatiques — baisse d'allure et hausse de FC
assimilées à la fatigue — et des prescriptions autonomes : repos, footing Z2,
séances au seuil. La base contient aussi des règles universelles non étayées
dans le fichier. Leur présence actuelle ne prouve pas leur utilisation en V1.

Sources :
[`chat_engine.py:52–74`](../../backend/chat_engine.py#L52-L74),
[`chat_engine.py:121–131`](../../backend/chat_engine.py#L121-L131),
[`knowledge_base.json:5–25`](../../backend/knowledge_base.json#L5-L25).

Les vulnérabilités et dépendances historiques restent non vérifiées.
Aucune conclusion de sécurité rétroactive n'est justifiée.

**Piste minimale conditionnelle, non implémentée :** adapter uniquement la
présentation et la mémoire conversationnelle de `llm_coach`, sans nouveau
moteur, sans modifier les faits V2/V3 ni l'autorité Training. Cette piste
s'appuie sur les limites observées ci-dessus ; elle n'est pas une restauration
V1 démontrée ni une promesse de gain qualitatif.

## 6. Verdict

**Preuves insuffisantes.** Le pipeline du checkout est identifiable ; le
véritable câblage V1 et les commits responsables des pertes ne sont pas établis.
Une restauration directe ne peut pas être recommandée sur cette base.

Pour conclure l'audit historique, il reste à lire les fichiers au commit
`9b7947ec`, remonter leurs appels depuis les routes et comparer leur évolution
par commit. Aucune implémentation n'est autorisée par le présent rapport.
