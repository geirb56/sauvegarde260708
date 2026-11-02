# RUNINDEX C394 — Coach unifié : contexte factuel et continuité

> Rapport historique : instantané de preuves, pas la vérité courante.

## A. Provenance
- Branche canonique `copilot/dev`, SHA de départ `f78ee3f17b1d60b64664e79fe8072bf3be9e6ee3` (merge PR #380 = C393 présent). Worktree propre au départ.

## B. Diagnostic (S1 lecture du code, confirmé par tests)
| Défaut | Chemin | Attendu | Transmis | Correctif |
|---|---|---|---|---|
| H3 | C/D (`process_coach_message`) | observations V3 validées identiques à WorkoutDetail/SessionDetail | V2 seul (`workout_detail.analysis`) | `validated_workout_observations` |
| H4 | rechargement de `/coach` | séance active conservée | `activeWorkoutId` perdu (état React) | restauration depuis le dernier message d'historique |
| H5 | D | contexte de suivi suffisant | 5 messages en base / 4 × 200 car. | 8 / 6 × 400 car. |
| Prompt | C/D | raisonnement observation → hypothèse → limite ; pas de séance « précédente » inventée | absent | directives ajoutées à `SYSTEM_PROMPT_COACH` |

## C. Implémentation
- `backend/server.py` : `_load_coach_narrative` + `_coach_validated_workout_observations` réutilisent `load_scoped_workout_deterministic_narrative` (filtré par `user_id`, lecture seule, sans LLM, sans Garmin). Chargé après le contrôle d'entitlement et seulement si `workout_id` est fourni ; la recommandation V3 n'est jamais transmise. Le narratif chargé est réutilisé par le repli C393 (un seul chargement). `COACH_HISTORY_LIMIT = 8`.
- `backend/llm_coach.py` : fenêtre d'historique 6 × 400 car. ; directives de raisonnement, suivi, comparaison, limites physiologiques.
- `frontend/src/pages/Coach.jsx` : restauration de la séance active depuis le dernier message de l'historique (aucune nouvelle persistance) ; `?analyze=` reste prioritaire.
- Pas de nouvel endpoint, collection, appel LLM, ni calcul V2/V3/Training V2.

## D. Contrat factuel / E. Conversation
- Sources : V2 (`workout_detail.analysis`), V3 narratif déterministe, Training V2 inchangé (seule autorité de prescription).
- Séance active : initialisée par `?analyze=`, conservée par les suivis (`workout_id` envoyé à chaque message), restaurée au rechargement si le dernier message est lié à une séance ; fermée via le bouton de contexte.
- Comparaisons : seules `comparison.similar` (V2) et la séance active sont fournies ; le prompt interdit d'inventer une séance « précédente » et demande de ouvrir la séance depuis sa page.
- **Limites documentées** : pas de résolution de références temporelles ; le serveur ne persiste pas d'état de séance active (déduit de l'historique) ; la comparaison avec une séance désignée librement n'est pas prise en charge (aucun nouveau moteur de recherche). Le chargement V3 refait une passe V2 en lecture (coût non mesuré).

## F. Validation
- Backend (venv, dépendances `emergentintegrations`/`litellm` non installables hors ligne) : `test_coach_c393_fallback_quota`, `test_llm_coach_voice`, `test_coach_context_v2`, `test_coach_workout_access_pr325`, `test_coach_contract_unified` : 255 passed avant et après ; nouveau `test_coach_c394_active_workout_context.py` : 7 passed. Sous-ensemble large (`-k "coach or workout_analysis or intelligence or narrative"`) : 18 failed / 5 errors identiques avant/après (suites d'intégration exigeant `REACT_APP_BACKEND_URL`/dépendances absentes).
- Frontend : `coach-page` + `chat-coach-subscription-status` 34 passed ; `CI=true npm run build` compilé.
- Non exécutés : `test_coach_conversational.py` (HTTP réel), tout test LLM réel. Les tests simulés ne prouvent pas la qualité des réponses : qualification réservée à C395. Fixtures synthétiques, jamais présentées comme des activités Garmin.

## G. Sécurité / performance
- Isolation : chargeur filtré par `user_id` ; séance étrangère → 404 avant tout chargement ; sans entitlement → message de restriction, aucun chargement.
- Quotas/repli C393 inchangés (tests C393 verts).
- Risque résiduel : prompt = défense non absolue ; passe V2 supplémentaire en lecture par message de séance.
