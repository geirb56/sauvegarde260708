# Multi-user Auth Migration Audit (Preparation)

Ce rapport inventorie les points bloquants pour la migration vers une authentification multi-utilisateur (future Supabase Auth), sans casser le comportement actuel.

## 1) `user_id="default"` / fallback utilisateur backend

| Fichier | Lignes | Impact | Correction future recommandée |
|---|---:|---|---|
| `backend/server.py` | 336 | `auth_user()` fallback vers `"default"` si aucun header/query | Remplacer par un principal authentifié obligatoire en production (401 si absent) |
| `backend/server.py` | 666, 677, 690, 893, 1181, 1188, 1222, 1313, 1770, 1780, 1896, 2033, 2117, 2128, 2147, 2179, 2219, 2380, 2465, 2608, 2635, 2665, 2699, 2730, 2738, 2765, 2794, 2839, 3407, 3461, 4366, 4553, 4658, 4675, 4747, 4759, 4844, 5168, 5183, 5245, 5295, 5310, 5331, 5425, 5548 | Paramètres d’API par défaut sur un utilisateur global | Rendre `user_id` implicite via token, supprimer valeur par défaut |
| `backend/server.py` | 1479, 1798 | Requêtes chat utilisent `request.user_id or "default"` | Exiger `request.user_id` authentifié et retirer fallback |
| `backend/server.py` | 4872, 5512 | Webhooks utilisent fallback metadata `"default"` | Exiger metadata `user_id` valide + rejet explicite si absent |

## 2) USER_ID hardcodé frontend

| Fichier | Ligne | Impact | Correction future recommandée |
|---|---:|---|---|
| `frontend/src/utils/constants.js` | 4 | Source globale `USER_ID = "default"` | Remplacer par ID issu du provider Auth |
| `frontend/src/context/SubscriptionContext.jsx` | 7 | Abonnement forcé sur user unique | Injecter user courant depuis session auth |
| `frontend/src/components/TerraConnection.jsx` | 11 | Sync Terra mono-utilisateur côté UI | Utiliser user_id dérivé du token |
| `frontend/src/pages/Subscription.jsx` | 30 | Checkout/status mono-utilisateur | Retirer `USER_ID` hardcodé |
| `frontend/src/pages/Progress.jsx` | 37 | Lecture métriques mono-utilisateur | Mapper sur user authentifié |
| `frontend/src/pages/Digest.jsx` | 29 | Digest mono-utilisateur | Mapper sur user authentifié |
| `frontend/src/pages/Onboarding.jsx` | 11 | Onboarding Garmin mono-utilisateur | Mapper sur user authentifié |
| `frontend/src/pages/TrainingPlan.jsx` | 20 | Plan mono-utilisateur | Mapper sur user authentifié |
| `frontend/src/pages/Coach.jsx` | 14 | Coach mono-utilisateur | Mapper sur user authentifié |
| `frontend/src/pages/Guidance.jsx` | 20 | Guidance mono-utilisateur | Mapper sur user authentifié |
| `frontend/src/pages/Settings.jsx` | 17 | Paramètres/abonnement mono-utilisateur | Mapper sur user authentifié |

## 3) Requêtes Mongo permissives (`user_id` null/absent)

| Fichier | Lignes | Impact | Correction future recommandée |
|---|---:|---|---|
| `backend/server.py` | 670, 681 | Workouts lisibles via `$or` incluant `None`/absent | Migration de données: backfill `user_id`, puis filtre strict `{"user_id": auth_user_id}` |
| `backend/server.py` | 1330-1331, 1496, 1501, 1585, 3646-3647, 4303-4304 | Agrégations/analyses peuvent mélanger des données non scopées | Supprimer fallback null/absent après migration |
| `backend/coach_service.py` | 360-361, 369-370, 379-380 | Calculs coach incluent documents non attribués | Filtrer strictement sur user auth |
| `backend/terra_integration.py` | 501 | Lookup Terra permissif `None`/absent | Filtre strict user + migration historique |

## 4) Plan de migration recommandé (sans implémentation immédiate)

1. Introduire un `auth_user_id` obligatoire (token) et conserver temporairement une compatibilité soft flaggée.  
2. Backfill Mongo sur collections historisées (`workouts`, `digests`, `guidance`, etc.) pour éliminer `user_id` null/absent.  
3. Basculer backend en mode strict (401 si identity absente, filtres stricts user).  
4. Retirer `USER_ID="default"` du frontend et brancher toutes les requêtes sur le provider d’auth.  
5. Ajouter tests de non-régression multi-user (isolation stricte des données entre deux user_id).  
