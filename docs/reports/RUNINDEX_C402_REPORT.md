# RUNINDEX C402 — Correction ciblée du commentaire automatique C400

Base : `copilot/dev` @ `6dce0902c112694cb29c5af845af15e24979724a`. Flag `C400_SESSION_COMMENT_ENABLED` : **OFF (inchangé)**. Non mergé, non déployé.

## Verdict : PARTIEL (code et tests déterministes OK ; validation réelle non faite)

Ce rapport est un instantané de preuve, pas la vérité courante.

| Critère de sortie | État |
|---|---|
| Pas de régression C396 / Training V2 / C388 | Aucun fichier Training V2, C388 ni `SYSTEM_PROMPT_COACH` modifié ; tests Coach/C388 verts |
| Défaut factuel connu accepté dans les tests | Aucun parmi les cas listés ci-dessous (cas synthétiques) |
| Faux positifs C401 expliqués/corrigés | **Non démontrable** : le corpus C401 (`/tmp/c401`) n'existe plus. Faux positifs reproduits sur cas synthétiques et corrigés |
| Commentaires naturels et contextualisés | **Non vérifié** : aucune génération réelle (pas de clé LLM ni de données réelles) |
| Permissions physiologiques respectées | Oui (tests) |
| Fallback fonctionnel | Oui (tests C400 inchangés verts) |
| Flag OFF | Oui |

## Données C401

`/tmp/c401` est absent : 20 commentaires, 22 erreurs isolées, 5 générations LLM, faits C388, contextes et motifs de rejet sont **perdus**. Rien n'a été reconstitué de mémoire. Les cas de `tests/test_coach_c402_session_comment.py` sont **synthétiques**, issus de l'audit du code, et ne remplacent pas C401. Aucun appel LLM n'a été fait.

## Changements

- `backend/coach_session_comment.py`
  - `build_comment_context()` : contexte sélectionné en cinq catégories (séance analysée ; `history_as_of_session` ; `runner_profile` ; `declared_goal` ; `reliable_physiology`). Retire Training V2, phase, readiness, charge, performance, allures actuelles, titres libres et ids.
  - Objectif : `training_cycles.goal` déclaré, étiqueté `current_declared_goal`, `known_at_session_date: false` (aucun historique d'objectif n'existe). `race_date`/`target_time` ne sont pas transmis (ils étaient toujours `null` sur ce chemin). Absent si non déclaré.
  - Profil : `experience: not_provided`; habitudes (nombre de séances, km) seulement avec ≥3 séances antérieures et historique non tronqué. Aucune tendance (`trend: not_established`).
  - Validateur : chiffres exacts des écarts en s/km acceptés ; mots-nombres vérifiés au lieu d'être rejetés en bloc (« une fois » = expression) ; chiffres d'historique citables uniquement avec formulation d'historique ; « récupération » (phase) et « le plus dur » (idiome) ne sont plus des étiquettes d'intensité ; « cette semaine » / « mañana » (matin) ne sont plus des prescriptions ; formulations d'abstention étendues.
  - Nouveaux contrôles : progression/forme paraphrasée, gain d'endurance, efficacité de l'entraînement, réussite/échec, intensité paraphrasée (zone de confort), minimisation d'un écart ≥10 s/km ou ≥10 %, objectif cité comme cause/conception de la séance ou d'un type différent du déclaré.
  - `COACH_COMMENT_VERSION` → `c402-session-comment-v3` (invalide le cache).
- `backend/server.py` : `_build_coach_comment_context` applique la sélection ; `_assemble_coach_llm_context(goal_optional=True)` pour le commentaire seulement (un utilisateur sans objectif déclaré n'entraîne plus un `context_error`). Le chat est inchangé.
- `backend/llm_coach.py` : uniquement `_SESSION_COMMENT_DIRECTIVE` (structure, usage de l'historique/objectif, interdits). `SYSTEM_PROMPT_COACH` inchangé.
- Tests : `tests/test_coach_c402_session_comment.py` (35 cas) ; 3 tests C400 adaptés car l'ancien contrat a volontairement changé (contexte identique au chat → mêmes faits mais sélection ; invalidation du cache sur un fait de séance ; « one kilometre » est maintenant rejeté pour valeur non fondée au lieu de mot-nombre).

## Tests exécutés (venv local sans `litellm`/`emergentintegrations`, réseau indisponible)

- C402 + C400 + Coach Context V2 + C392B + C394 + C388 : **296 passed**.
- Couvre FR/EN/ES, isolation utilisateur, fallback, timeout/cache, chat C396 (via tests existants), **tous mockés**.
- Suite backend complète (hors `test_pr153_…`, erreur de collecte déjà présente sur la base) : avant/après comparés ; les écarts observés (idor, pr204, trial, cycle start-date) passent 43/43 en isolation avec et sans mes changements : instabilité d'ordre préexistante, non liée.
- Génération réelle sur les 5 séances de référence : **non exécutée** (aucune clé LLM, aucune donnée réelle). La fiabilité sur données réelles n'est pas démontrée.

## Limites

- Le validateur reste `heuristic_guard` : il ne prouve pas la véracité. Les conclusions paraphrasées hors listes FR/EN/ES lui échappent ; la directive de génération est le premier garde-fou.
- Le seuil de matérialité d'un écart (10 s/km, 10 %) est un choix de conception.
- Le contrôle sur l'historique valide les valeurs, pas leur attribution à la bonne séance.
- Avant toute activation : exécuter les 5 générations réelles avec contexte, texte, affirmations, faits sources, verdict du validateur et verdict manuel, puis décision explicite. Si la bêta est prioritaire, garder le fallback C388.
