# RUNINDEX P392 — Audit profond du Coach IA (avant bêta)

> Rapport historique : instantané de preuves, pas la vérité courante. La vérité courante vient du code et de `docs/RUNINDEX_MASTER_ROADMAP_AND_DECISIONS.md`.
> Mode : lecture seule. Niveaux de preuve : S1 statique, S2 test isolé, S3 runtime réel. Aucun S3 n'a été obtenu.

## A. Environnement et provenance

- Dépôt : `geirb56/sauvegarde260708`, branche `copilot/dev`.
- SHA audité : `907f5ccf3c0eb781eb6509e1c4a4c032165eba26` (merge de la PR #378), récupéré dans `/tmp/runindex-c392/repo`.
- Runtime : aucun, NON VÉRIFIÉ. Pas d'instance autorisée, pas de version déployée identifiée, pas de compte de test. Le code audité n'est pas prouvé déployé.
- Limites : dépendances non installables hors ligne (`emergentintegrations`, `cryptography`). Les tests important `server.py` n'ont pas pu être exécutés (`test_coach_context_v2`, `test_workout_analysis_v2`, `test_workout_intelligence_v3`, `test_coach_workout_access_pr325`, `test_coach_conversational`).
- S2 exécuté : `test_llm_coach_voice`, `test_narrative_coach_v3`, `test_narrative_c388` → 303 passed.
- Aucun appel LLM, aucune écriture Mongo/Redis. Corpus, notes de qualité et mesures de latence/coût : NON MESURÉ.

## B. Matrice des effets de bord

| Endpoint | Effets de bord possibles (S1) | Exécution runtime |
|---|---|---|
| `POST /coach/analyze` (`server.py:1740`, `process_coach_message`) | Incrémente `coach_quota_counters` (upsert) ; 2 écritures dans `conversations` ; appelle `get_training_v2_week` et `get_today_adaptive_session` (invalidation et persistance de snapshots) ; appel LLM payant | NON |
| `GET /coach/workout-analysis/{id}` (`server.py:2132`) | Aucune écriture trouvée dans le code lu ; contrôle d'accès `_coach_access` | Possible en théorie, aucune instance autorisée |
| `GET /coach/workout-intelligence/{id}` (`server.py:2157`) | Lecture seule ; LLM seulement si `C355_NARRATIVE_LLM_ENABLED` ; cache mémoire | Idem, sous réserve du flag déployé |
| `GET /coach/history` | Lecture seule | Possible en théorie |
| `DELETE /coach/history` (`server.py:2118`) | `delete_many` sur `conversations` | NON |

## C. Cartographie fonctionnelle

- **A. WorkoutDetail / B. SessionDetail** : `GET /coach/workout-analysis` (V2) et `GET /coach/workout-intelligence` (V3, hook `useWorkoutIntelligence`), affichés via `NarrativeWorkoutAnalysis`. Texte déterministe (`deterministic_fallback`) ; le LLM n'intervient que si le flag est actif. Si une `session_synthesis` V2 existe, `narrative_coach_v3.py` retourne le texte local sans LLM.
- **C. `/coach?analyze=<id>`** : `Coach.jsx` envoie `POST /coach/analyze` avec `workout_id` et un prompt générique. Contexte V2 + Training V2 + `recent_workouts`, puis `llm_coach.enrich_chat_response`. Ce chemin ne passe pas par V3 ni par la narration (`coach_context_v2.py` n'importe ni V3 ni `narrative_coach_v3`).
- **D. Suivi** : `workout_id` renvoyé depuis l'état React `activeWorkoutId`. Historique serveur filtré par `workout_id`, `limit(5)` ; `llm_coach` garde 4 messages tronqués à 200 caractères.
- **E. Chat sans séance** : `workout_id=None`, contexte général (`recent_workouts` 30 j / 30 max, Training V2).
- Commun : `gpt-4.1-mini`, timeout 15 s, réponse limitée à 700 caractères (`llm_coach.py`).

## D. Corpus de référence

Non constitué : aucun accès légal à des données Garmin réelles. Aucune réponse comparée.

## E. Résultats comparatifs

Exactitude, pertinence, explication, conversation, utilité : NON MESURÉ (aucune sortie observée ; les mocks ne mesurent pas la qualité du modèle).

## F. Audit des capacités (S1)

- Existantes : phases et récupérations (V2), `session_synthesis`, `coach_language`, V3 `effort_pace_observations`, comparaison `similar`, `selected_workout_permissions`, cutoff historique strict.
- Utilisées par le chat : V2 (`workout_detail.analysis`) uniquement ; `km_splits` tronqués à 5.
- Visibles à l'utilisateur : V2 et V3 sur les pages de détail.
- Manquantes dans le chat : faits V3 ; désignation de séance en langage naturel (« la précédente », « hier »).

## G. Sécurité et performance

- Isolation utilisateur (S1, CONFIRMÉ) : `db.workouts.find_one({"id", "user_id"})` ; `recent_workouts` re-filtre `user_id`.
- Entitlements (S1) : `workout_id` sans droit → message de restriction, `workout_detail` purgé, directive de prompt.
- Injection de prompt : message utilisateur injecté tel quel ; défense par prompt, sans validation de sortie côté chat. Impact réel NON VÉRIFIÉ.
- Latence/coût : pas d'échantillon, pas de p50/p95. Un appel LLM par message de chat ; V3 : 0 par défaut.
- Jusqu'à 2000 `garmin_activities` chargées à chaque message (S1).

## H. Anomalies

| ID | Gravité | Symptôme | Preuve | Cause | Correctif minimal |
|---|---|---|---|---|---|
| H1 | P1 | Chat sans repli déterministe : échec LLM → HTTP 503 | S1, CONFIRMÉ | Fallback V3 non réutilisé | Retourner le narratif V3 déterministe pour une séance sélectionnée |
| H2 | P1 | Quota gratuit consommé quand le LLM échoue | S1, CONFIRMÉ (`user_message_persisted=True` avant l'appel → pas de `_release_free_coach_quota_slot`) | Ordre d'écriture | Libérer le slot sur échec LLM ou persister après succès |
| H3 | P1 | Chat et analyse V3 affichée potentiellement divergents | S1, PROBABLE | Contextes distincts | Injecter les faits V3 validés dans le chat |
| H4 | P1 | Séance active perdue au rechargement ; « la précédente » ne change pas de séance | S1, CONFIRMÉ (état) ; effet utilisateur NON VÉRIFIÉ | Pas d'état serveur | Restaurer la séance active depuis l'historique |
| H5 | P1 | Contexte de suivi court : 4 messages × 200 caractères | S1, CONFIRMÉ | Constantes `llm_coach.py` | Ajuster sans toucher aux garde-fous |
| H6 | P2 | Réponse tronquée à 700 caractères | S1 | `_clean_response` | À ajuster après mesure |
| H7 | P2 | Prompt initial générique | S1 | `i18n.js` `coachExtended.analysisPrompt` | Secondaire |

Aucune anomalie P0 démontrée. L'absence de preuve runtime n'est pas une preuve d'absence.

## I. Architecture recommandée

Conserver : séparation Training V2 (prescription) / Coach (explication), permissions explicites, cutoff historique, narration V3 déterministe, `session_synthesis`. Ajouter au minimum : repli déterministe dans le chat, libération du quota sur échec LLM, restauration de la séance active. Pas de nouveau service ni de fusion de moteurs.

## J. Décision R5

- **C393** : nécessaire, réduit à H1 + H2, avec tests de non-régression (quota, 503, repli).
- **C394** : H3 + H4 + H5 ; réutiliser les faits V3 validés, restaurer la séance active (`Coach.jsx`, `process_coach_message`). Tests : parcours C→D, retour à une séance antérieure, rechargement de page.
- **C395 (GO/NO-GO)** : bloquants = H1, H2 et un test runtime S3 sur corpus. Reportables : H5–H7 après mesure. Manuels : les 12 questions de conversation sur le corpus figé, avec appels LLM autorisés.

## K. Conclusion

- Bloquants : H1, H2.
- Risques : divergence chat/V3 (H3), continuité (H4).
- Incertitudes : qualité réelle du LLM, version déployée, performance, comportement runtime.
- Prochaine action : autoriser une instance de test, un compte et un budget LLM pour constituer le corpus (S3), puis valider H3/H4.
