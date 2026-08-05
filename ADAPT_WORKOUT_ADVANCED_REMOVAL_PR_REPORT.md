# RunIndex — PR N3 : Retrait de l'adaptateur mort `adapt_workout_advanced`

Objectif unique : supprimer le chemin d'adaptation mort `adapt_workout_advanced` (aucun appelant) et laisser `adapt_session_to_readiness` comme unique adaptateur de la séance du jour. Aucun changement de comportement de `/training/today` ni des règles readiness → HARD / EASY / REST.

---

## A. Table d'audit AVANT modification (toutes occurrences)

Recherche globale repo (`.py`, `.md`, `.js`, `.jsx`, hors `node_modules`/`__pycache__`/`build`).

### `adapt_workout_advanced`
| Fichier | Ligne / contexte | Type | Statut |
|---------|------------------|------|--------|
| `backend/server.py` | 1 : `from services.adaptation_engine import adapt_workout_advanced` | import | **MORT** (jamais appelé) |
| `backend/services/adaptation_engine.py` | 1 : `def adapt_workout_advanced(planned_workout, fatigue_ratio, user_goal)` | définition | **MORT** (seule fonction du module) |

→ **Aucun appel** `adapt_workout_advanced(...)` dans tout le repo. Aucun test, aucune doc.

### `adaptation_engine`
| Fichier | Ligne / contexte | Type | Statut |
|---------|------------------|------|--------|
| `backend/server.py` | 1 : import (ci-dessus) | import | MORT |
| `backend/demo_mode.py` | 85 & 106 : commentaires/docstring citant `adaptation_engine.py` comme exemple d'usage du helper demo | doc (commentaire) | OBSOLÈTE (pas du code) |

→ Aucun import dynamique / `importlib` / string-import de `adaptation_engine`.

### `adapt_session_to_readiness` (source de vérité — À CONSERVER)
| Fichier | Ligne / contexte | Type | Statut |
|---------|------------------|------|--------|
| `backend/training_engine.py` | 425 : `def adapt_session_to_readiness(...)` | définition | **ACTIF** |
| `backend/training_engine.py` | 1053 : entrée `__all__` | export | ACTIF |
| `backend/server.py` | 77 : import | import | ACTIF |
| `backend/server.py` | 3633 : `adaptive_session, adaptation_applied, adaptation_reason = adapt_session_to_readiness(...)` | **appel réel** (chemin `/api/training/today`) | ACTIF |

---

## B. Conclusion

**Conclusion A — Aucun appel de `adapt_workout_advanced` → suppression sûre** (import dans `server.py` + module `adaptation_engine.py` orphelin). Le module ne contenait QUE cette fonction morte.

---

## C. Fichiers modifiés / supprimés

| Fichier | Action |
|---------|--------|
| `backend/server.py` | Retrait de la ligne 1 (`from services.adaptation_engine import adapt_workout_advanced`) |
| `backend/services/adaptation_engine.py` | **Supprimé** (module entièrement orphelin, 72 lignes, une seule fonction morte) |
| `backend/demo_mode.py` | Correction doc : retrait des 2 mentions obsolètes de `adaptation_engine.py` dans des commentaires/exemples (aucun impact comportemental) |
| `ADAPT_WORKOUT_ADVANCED_REMOVAL_PR_REPORT.md` | Ce rapport |

Aucun test supprimé/modifié (aucun ne ciblait `adapt_workout_advanced`). `adapt_session_to_readiness` non touché. Frontend non touché.

---

## D. Tableau de vérifications

| Vérif | Résultat |
|-------|----------|
| table audit ACTIF/MORT complète | **PASS** |
| `grep adapt_workout_advanced` post-modif (code vivant) | **PASS** (0 occurrence) |
| `grep adaptation_engine` post-modif | **PASS** (0 occurrence) |
| `grep adapt_session_to_readiness` encore présent et utilisé | **PASS** (def 425, import 76, appel 3632) |
| import `server.py` propre (backend démarre) | **PASS** (`Application startup complete`, aucune ImportError) |
| tests adaptation / today concernés | **PASS** (aucun test ne dépendait de la fonction retirée) |
| pas de changement fonctionnel `today` (smoke) | **PASS** (`GET /api/training/today` → HTTP 200, clés `adaptive_session` / `adaptation_applied` / `adaptation_reason` présentes) |
| frontend non modifié | **PASS** (0 fichier frontend touché) |

---

## E. Risques résiduels

- **Très faible.** La fonction n'avait aucun appelant (statique). Aucun import dynamique/string détecté.
- `demo_mode.py` : édits purement en commentaires (docstring), zéro effet runtime.
- PR petite, un seul objectif, facilement revertible (`git revert`).

---

## F. Verdict

**READY TO MERGE**
