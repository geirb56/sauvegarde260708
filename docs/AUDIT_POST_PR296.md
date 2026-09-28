# RUNINDEX — Audit final backend après PR296

## 1. IDENTIFICATION

- **Dépôt**: `geirb56/sauvegarde260708`
- **Branche**: `copilot/dev`
- **HEAD audité**: `5dc87f0bf16470b7b83dc475e0eb5c5b770c102e`
- **Date audit**: 2026-09-28 (UTC)
- **Périmètre**: backend FastAPI, auth/access, subscription, workers, tests, consommateurs frontend
- **Mode**: lecture seule stricte (aucune modification runtime/DB/infra)
- **Limites**:
  - audit statique (pas de validation Railway/Upstash/Garmin/Paddle en prod),
  - registre `LEGACY_AUDIT` L01–L22 introuvable dans ce HEAD,
  - exécution locale de tests indisponible dans l’environnement d’audit (`python -m pytest` absent).

## 2. SYNTHÈSE

- **P0**: 2
- **P1**: 6
- **P2**: 4
- **Points non vérifiables**: 2 majeurs (registre L01–L22 absent ; validation runtime infra non faite)
- **État des autorités canoniques**:
  - Training V2: globalement canonique sur `/training/today`, `/training/v2/week`, `/training/v2/cycle`, `/training/v2/paces`
  - Coach: contrat unifié `/coach/analyze` + `/coach/history`, suppression `deep_analysis` confirmée
  - Workout Analysis V2: endpoint canonique unique présent
  - Subscription: autorité backend présente mais écarts de contrat commercial/exposition subsistent
- **Blocages pré-bêta principaux**:
  1. Dualité d’autorité d’authentification (`auth_user` vs `get_current_user`) sur routes runtime
  2. Endpoints d’observabilité internes exposés sans auth forte
  3. Contrat commercial encore incohérent (annuel exposé, quota affiché vs anti-abus réel)
  4. Validation CI backend insuffisante/opaque à ce HEAD

## 3. CONSTATS DÉTAILLÉS

### RI-AUD-001
- **Sévérité**: P0
- **Fichier/lignes**:
  - `backend/server.py:382-423` (`auth_user`)
  - `backend/auth/dependencies.py:48-107` (`get_current_user`)
  - Exemples routes runtime utilisant `auth_user`: `backend/server.py:762-787, 1719-1725, 2692-2694, 3405-3407`
- **Composant**: authentification backend runtime
- **Comportement observé**: majorité des routes API via `auth_user` (JWT seule), sans contrôle user actif/existant
- **Preuve**: `auth_user` ne lit pas `db.users` et ne vérifie pas `is_active`; `get_current_user` le fait
- **Consommateurs identifiés**: pages frontend principales (Dashboard/Coach/Training/Progress/Settings)
- **Risque concret**: token valide d’un compte désactivé/supprimé potentiellement accepté
- **Correction recommandée**: unifier sur la dépendance canonique `get_current_user`
- **Tests de non-régression nécessaires**: désactivation/suppression utilisateur + expiration JWT sur routes runtime
- **Confiance**: élevée

### RI-AUD-002
- **Sévérité**: P1
- **Fichier/lignes**:
  - `backend/server.py:4129-4133` (`GET /cache/stats`, sans Depends auth)
  - `backend/server.py:4143-4149` (`GET /metrics`, sans Depends auth)
  - `backend/server.py:320` (`RATE_LIMIT_EXEMPT={"/api/cache/stats"}`)
  - `backend/access_control.py:410-411` (`/api/cache/`, `/api/metrics` classés FREE)
  - `backend/server.py:475-476` (middleware subscription filtre PREMIUM uniquement)
- **Composant**: observabilité/cache
- **Comportement observé**: endpoints internes lisibles sans auth forte; `/api/cache/stats` exempté rate-limit
- **Preuve**: absence dépendance auth + classification FREE + middleware premium-only
- **Consommateurs identifiés**: aucun consommateur frontend runtime explicite
- **Risque concret**: fuite d’indicateurs internes
- **Correction recommandée**: restreindre admin/interne
- **Tests de non-régression nécessaires**: 401 anonyme / 403 non-admin / 200 admin
- **Confiance**: élevée

### RI-AUD-003
- **Sévérité**: P1
- **Fichier/lignes**:
  - `backend/api/garmin.py:319-338` (`GET /garmin/queue/health`, sans Depends auth)
  - `backend/access_control.py:438` (`/api/garmin/` = PREMIUM)
  - `backend/server.py:496-513` (contrôle par tier, pas rôle admin)
- **Composant**: santé file workers
- **Comportement observé**: métriques infra globales accessibles à tout user premium/trial
- **Preuve**: payload global endpoint + absence contrôle admin
- **Consommateurs identifiés**: aucun frontend runtime; usage tests (`backend/tests/test_realtime_sync_pipeline.py`)
- **Risque concret**: exposition opérationnelle interne
- **Correction recommandée**: réserver admin/ops
- **Tests de non-régression nécessaires**: matrice rôle/tier
- **Confiance**: élevée

### RI-AUD-004
- **Sévérité**: P1
- **Fichier/lignes**:
  - `backend/server.py:183-207` (`SUBSCRIPTION_TIERS` avec `premium.price_annual=49.99`)
  - `backend/server.py:4004-4018` (`GET /subscription/tiers` retourne `price_annual`)
- **Composant**: contrat abonnement exposé
- **Comportement observé**: exposition tarif annuel malgré contrat cible mensuel unique
- **Preuve**: `price_annual` servi par API
- **Consommateurs identifiés**: pas de consommateur runtime explicite
- **Risque concret**: divergence produit/commerciale
- **Correction recommandée**: retirer l’annuel de l’API
- **Tests de non-régression nécessaires**: test contrat `/subscription/tiers`
- **Confiance**: élevée

### RI-AUD-005
- **Sévérité**: P1
- **Fichier/lignes**:
  - `backend/access_control.py:115` (`CHAT_ANTIABUSE_CAP=500`)
  - `backend/server.py:1870-1881` (anti-abus effectif)
  - `backend/server.py:4055, 4071-4073` (`/subscription/status` expose `messages_limit=999`)
- **Composant**: contrat quota coach
- **Comportement observé**: droit affiché “999/unlimited” différent de la limite anti-abus réelle (500/mois)
- **Preuve**: logique d’exécution coach vs payload status
- **Consommateurs identifiés**: `frontend/src/components/ChatCoach.jsx:48` (historique), `frontend/src/hooks/useSettings.js:42` (non consommé)
- **Risque concret**: incohérence UX/commerciale
- **Correction recommandée**: exposer explicitement la borne anti-abus
- **Tests de non-régression nécessaires**: cohérence `/subscription/status` vs enforcement `/coach/analyze`
- **Confiance**: élevée

### RI-AUD-006
- **Sévérité**: P1
- **Fichier/lignes**:
  - `docker-compose.yml:18` (healthcheck sur `/health`)
  - `backend/access_control.py:398` (map mentionne `/api/health`)
  - aucune route `/health` ni `/api/health` détectée dans `backend/server.py` + routers
- **Composant**: santé runtime/infra
- **Comportement observé**: mismatch healthcheck/route réelle
- **Preuve**: route absente dans les déclarations FastAPI
- **Consommateurs identifiés**: orchestration docker locale
- **Risque concret**: faux négatifs de santé
- **Correction recommandée**: ajouter endpoint health canonique ou corriger healthcheck/map
- **Tests de non-régression nécessaires**: smoke healthcheck
- **Confiance**: élevée

### RI-AUD-007
- **Sévérité**: P1
- **Fichier/lignes**:
  - `backend/tests/conftest.py:9` (`REACT_APP_BACKEND_URL` externe)
  - `backend/tests/test_subscription_trial.py:33,50,63` (params `user_id`)
  - `backend/tests/test_realtime_sync_pipeline.py:24,115,130...` (URL externe + `user_id`)
- **Composant**: tests backend
- **Comportement observé**: sous-ensemble legacy dépend d’un backend externe et de contrats query-param non alignés JWT
- **Preuve**: appels `requests` directs vers `BASE_URL`
- **Consommateurs identifiés**: exécution manuelle/historique
- **Risque concret**: faux sentiment de couverture, possible mutation d’environnement réel
- **Correction recommandée**: isoler/marker ces tests hors gate principal
- **Tests de non-régression nécessaires**: suite locale hermétique
- **Confiance**: élevée

### RI-AUD-008
- **Sévérité**: P0
- **Fichier/lignes**:
  - Workflows visibles: `Claude`, `Copilot`, `Copilot cloud agent` (chemins `dynamic/...`)
  - run HEAD audité `5dc87f0...`: run `36408662675` en cours
- **Composant**: gate CI backend
- **Comportement observé**: aucun workflow explicite visible pour tests backend métier/sécurité
- **Preuve**: inventaire workflows GitHub Actions du repo
- **Consommateurs identifiés**: pipeline merge `copilot/dev`
- **Risque concret**: régressions backend non bloquées
- **Correction recommandée**: workflow CI backend explicite (pytest ciblé + sécurité route auth + contrat subscription)
- **Tests de non-régression nécessaires**: validation du workflow sur PR
- **Confiance**: moyenne/élevée (CI externe possible mais non visible)

### RI-AUD-009
- **Sévérité**: P2
- **Fichier/lignes**:
  - `frontend/src/components/ChatCoach.jsx:60,90,149` (appels `/chat/*`)
  - `frontend/src/App.js:64-100` (composant non routé/importé)
  - aucune route `/api/chat/*` backend
- **Composant**: frontend legacy non consommé
- **Comportement observé**: composant legacy vers contrat API inexistant
- **Preuve**: appels frontend vs inventaire routes backend
- **Consommateurs identifiés**: aucun runtime
- **Risque concret**: dette/confusion
- **Correction recommandée**: archiver/supprimer ou réaligner vers `/coach/*`
- **Tests de non-régression nécessaires**: test de non-import
- **Confiance**: élevée

### RI-AUD-010
- **Sévérité**: P2
- **Fichier/lignes**:
  - `backend_test_hidden_insight.py:8` (URL preview externe)
  - `backend_test_hidden_insight.py:90,208` (`user_id` injecté côté payload)
  - pas de référence CI détectée (`.github/workflows` absent dans ce clone)
- **Composant**: script historique
- **Comportement observé**: script manuel legacy non aligné auth actuelle, non branché CI
- **Preuve**: code script + absence wiring workflow
- **Consommateurs identifiés**: manuel/historique
- **Risque concret**: exécution trompeuse
- **Correction recommandée**: archiver ou migrer vers tests JWT in-process
- **Tests de non-régression nécessaires**: N/A si archivage
- **Confiance**: élevée

### RI-AUD-011
- **Sévérité**: P2
- **Fichier/lignes**:
  - `backend/chat_engine.py` (RAG historique)
  - `backend/coach_service.py:66-105` (`chat_response`)
  - pas de référence runtime vers `chat_engine`; `chat_response` non appelé hors module
- **Composant**: legacy backend non branché
- **Comportement observé**: artefacts historiques conservés sans usage runtime
- **Preuve**: recherche de références croisées
- **Consommateurs identifiés**: aucun runtime
- **Risque concret**: bruit architectural
- **Correction recommandée**: archiver/documenter ou supprimer en PR dédiée
- **Tests de non-régression nécessaires**: smoke import + contrat coach
- **Confiance**: moyenne/élevée

### RI-AUD-012
- **Sévérité**: P2
- **Fichier/lignes**:
  - `backend/server.py:4021-4073` (`/subscription/status`)
  - `backend/server.py:4077-4092` (`/premium/status` alias)
  - `backend/server.py:4172-4202` (`/subscription/info`)
  - `frontend/src/context/SubscriptionContext.jsx:36-40,81-90`
- **Composant**: contrats abonnement concurrents/dupliqués
- **Comportement observé**: endpoints statut multiples avec recouvrement partiel
- **Preuve**: 3 endpoints de statut + alias legacy
- **Consommateurs identifiés**: frontend runtime principal via `/user/features` + `/subscription/info`
- **Risque concret**: drift de contrat
- **Correction recommandée**: figer endpoint canonique + déprécation explicite alias
- **Tests de non-régression nécessaires**: test contrat unique + backward-compat documentée
- **Confiance**: élevée

## 4. INVENTAIRE LEGACY

### Composants réellement morts
- `frontend/src/components/ChatCoach.jsx` (non routé, endpoints `/chat/*` inexistants)
- `frontend/src/hooks/useSettings.js` (exports non consommés détectés)
- `backend/chat_engine.py` (RAG historique non branché runtime)
- `backend/coach_service.chat_response` (non appelé runtime)

### Composants encore actifs
- `backend/server.py` (routes cœur)
- `backend/api/garmin.py`, `backend/auth/*`, `backend/admin/router.py`
- workers `sync_worker`, `event_worker`, `scheduler_worker`, `monitor_worker`
- `subscription_manager.py` (trial/Paddle/cancel)

### Compatibilité nécessaire
- `/premium/status` alias legacy (encore présent)
- endpoints DEV subscription (`simulate-trial-end`, `reset-to-trial`) gardés hors prod
- structures snapshot/planned-memory Training V2

### Références historiques sans impact runtime immédiat
- `backend_test_hidden_insight.py`
- tests externes dépendants `REACT_APP_BACKEND_URL` + query `user_id`
- rapports markdown historiques

## 5. RÉCONCILIATION L01–L22

Registre source `LEGACY_AUDIT` (mapping L01..L22) non présent dans le HEAD audité.

| Constat | État vérifié |
|---|---|
| L01 | Non vérifiable (registre absent du dépôt audité) |
| L02 | Non vérifiable |
| L03 | Non vérifiable |
| L04 | Non vérifiable |
| L05 | Non vérifiable |
| L06 | Non vérifiable |
| L07 | Non vérifiable |
| L08 | Non vérifiable |
| L09 | Non vérifiable |
| L10 | Non vérifiable |
| L11 | Non vérifiable |
| L12 | Non vérifiable |
| L13 | Non vérifiable |
| L14 | Non vérifiable |
| L15 | Non vérifiable |
| L16 | Non vérifiable |
| L17 | Non vérifiable |
| L18 | Non vérifiable |
| L19 | Non vérifiable |
| L20 | Non vérifiable |
| L21 | Non vérifiable |
| L22 | Non vérifiable |

## 6. AUDIT DES TESTS

- **Couverture existante**: suite backend large (auth, training_v2, garmin queue/workers, subscription, sécurité)
- **Trous de couverture**:
  - GET observabilité (`/api/cache/stats`, `/api/metrics`) non verrouillés en auth/rôle
  - cohérence commerciale “quota affiché vs anti-abus réel” non verrouillée
  - endpoint health infra manquant/non cohérent
- **Suites exécutées**: tentative `python -m pytest` échouée (`No module named pytest`)
- **Suites non exécutées**: ensemble des suites backend (limite environnement)
- **État CI GitHub**:
  - workflows visibles: `Claude`, `Copilot`, `Copilot cloud agent` (dynamiques)
  - pas de workflow backend test explicite visible dans ce clone
  - run courant HEAD audité: `36408662675` (in_progress)

## 7. ROADMAP DES CORRECTIONS

### A. Sécurité

**PR-A1 — Unifier l’auth runtime**
- Objectif: remplacer `auth_user` par la dépendance canonique
- Fichiers: `backend/server.py`, tests auth/idor
- Prérequis: aucun
- Risque: moyen
- Critères d’acceptation: compte inactif/supprimé refusé partout
- Tests: auth JWT valide/invalide + user inactif sur routes clés

**PR-A2 — Durcir endpoints observabilité**
- Objectif: protéger `/api/cache/stats`, `/api/metrics`, `/api/garmin/queue/health`
- Fichiers: `backend/server.py`, `backend/api/garmin.py`, `backend/access_control.py`, tests sécurité
- Prérequis: PR-A1 recommandé
- Risque: faible/moyen
- Critères d’acceptation: 401/403 anonyme/non-admin
- Tests: matrice rôle/tier

### B. Contrat commercial

**PR-B1 — Aligner API abonnement au contrat produit**
- Objectif: retirer annuel exposé, aligner messaging quota/anti-abus
- Fichiers: `backend/server.py`, `subscription_manager.py` (si nécessaire), tests contrat
- Prérequis: validation produit
- Risque: moyen
- Critères d’acceptation: `/subscription/tiers` et `/subscription/status` conformes FREE/TRIAL/PREMIUM
- Tests: contrats API + tests frontend subscription

### C. Legacy dangereux

**PR-C1 — Isoler/retirer tests/scripts externes legacy**
- Objectif: éviter l’usage accidentel de tests externes/query legacy
- Fichiers: `backend/tests/*` ciblés, `backend_test_hidden_insight.py` (archivage/marquage)
- Prérequis: décision politique tests externes
- Risque: faible
- Critères d’acceptation: suite locale hermétique par défaut
- Tests: exécution locale sans dépendance `REACT_APP_BACKEND_URL`

### D. Nettoyage sans risque fonctionnel

**PR-D1 — Rationaliser aliases et code mort**
- Objectif: documenter/déprécier `/premium/status`, retirer composants non branchés
- Fichiers: `frontend/src/components/ChatCoach.jsx`, `frontend/src/hooks/useSettings.js`, `backend/chat_engine.py`, docs
- Prérequis: PR-B1
- Risque: faible
- Critères d’acceptation: aucun consumer runtime cassé
- Tests: build frontend + smoke API contracts

### E. Validation infrastructure

**PR-E1 — Corriger healthcheck + CI backend explicite**
- Objectif: endpoint health canonique et workflow CI backend visible
- Fichiers: `backend/server.py` (ou config), `docker-compose.yml`, workflows GitHub
- Prérequis: aucun
- Risque: moyen
- Critères d’acceptation: healthchecks stables + tests backend exécutés en CI sur PR
- Tests: job CI vert + preuve run sur SHA PR

## 8. GATE BÊTA

### Blocages sécurité
- Dualité auth runtime (`auth_user` vs canonique) — **P0**
- Endpoints observabilité exposés sans auth forte — **P1**

### Blocages fonctionnels
- Mismatch healthcheck/endpoint santé — **P1**

### Blocages commerciaux
- Contrat tarifaire annuel exposé + incohérence quota affiché vs anti-abus réel — **P1**

### Validations runtime manquantes
- Pas de validation suffisante pour conclure Railway/Upstash/Garmin/Paddle runtime
- CI backend métier/sécurité non explicitement visible sur ce repo

### Dettes reportables post-bêta
- Nettoyage composants/scripts legacy non branchés (P2) après sécurisation des blocages

## Conclusion

Le backend est proche d’un socle canonique côté Training/Coach V2, mais des écarts pré-bêta critiques restent ouverts sur l’auth runtime, l’exposition d’endpoints internes, et le contrat commercial exposé.
