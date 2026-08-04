# RunIndex — Project Setup Record

## Problem Statement
Pull https://github.com/geirb56/sauvegarde260629 and set it up so it runs. Replace /app contents.

## Changelog — Reprise après arrêt / comeback (PR77, June 2026)
- Durées de reprise profonde calées sur le niveau antérieur (fenêtre 6 sem, jours 28-42) via reprise_deep_durations: plancher 30/35/40 min (débutant/inconnu) -> 35/45/55 min (ex-coureur ~40km/sem). 3 séances, facile-only, AFFICHÉ EN MINUTES (weekly_minutes), plus en km. prior_weekly_km calculé dans coach_service.
- Frontend TrainingPlan.jsx: bandeau "Mode reprise" (deep/partial), carte semaine courante en minutes ("~105 min • 3 séances"). i18n FR/EN/ES.
- HEAD pulled to sauvegarde/main d0612d4 (PR#76 resume guard). Then reprise work (not pushed; use Save to Github).
- REAL-PATH bug found & fixed in PR76 cache bypass: coach_service.generate_dynamic_training_plan read cached_plan.get("weekly_km") (top-level, always None) → stale plan served. Now reads cached_plan["plan"]["weekly_km"].
- Reprise logic centralized in training_engine.py (single source): resolve_chronic_base (active-weeks avg, no /4 dilution), classify_training_state (deep_reprise/partial_reprise/reprise_exit/normal), resolve_reprise_plan, build_reprise_week_structure, cap_long_run_for_low_volume (≤40% target below goal floor), REPRISE_BASE_KM=12, REPRISE_STABLE_WEEKS=3, REPRISE_DEEP_SESSION_MINUTES=[20,25,30].
- deep_reprise (0km/28d): duration-based easy sessions (run/walk), no imposed km. partial_reprise: easy-only, volume progresses, intensity frozen. reprise_exit: intensity reintroduced + volume HELD (never both at once). normal: unchanged.
- Adaptive exit driven by completed active weeks (not fixed calendar). recovery_red_flag hook present (default False) for a future alert-signals PR. compute_current_weekly_km (ACWR/readiness contract) UNTOUCHED.
- Wired into 3 paths: coach_service.generate_dynamic_training_plan, server.py /training/full-cycle, /training/week-plan. Long run consolidated through compute_long_run_km.
- Tests: backend/tests/test_reprise_pr77.py (7 mandatory scenarios) + test_real_cache_bypass_pr76.py. 150 passed across plan suites. e2e HTTP: new user → /training/plan state=deep_reprise, 20/25/30min. Report: /app/REPRISE_PR77_REPORT.md. Nothing deployed.


## Changelog — gccli session sharing via MongoDB (August 2, 2026)
- New backend/garmin/session_store.py: save/restore/ensure/delete per-user gccli session, encrypted (Fernet; key = GCCLI_SESSION_KEY or derived from JWT_SECRET_KEY). Collection garmin_sessions, keyed by user_id (strict isolation).
- garmin/service.py hooks: save_session after /connect; ensure_session before sync/incremental_sync (graceful "session_unavailable" if missing); re-save after successful sync/deep_sync/incremental; delete_session on disconnect.
- Enables workers on a separate host (Railway) to hydrate the gccli session created by the Emergent backend. Worker must share the same encryption key (GCCLI_SESSION_KEY or JWT_SECRET_KEY).
- Tests: test_garmin_session_store.py (5) + adapted deep_sync dispatch tests. Auth/Paddle/Stripe untouched. Nothing deployed.


## Changelog — Paddle sandbox configured & validated (August 2, 2026)
- Configured all 5 Paddle env vars in backend/.env (sandbox): PADDLE_API_KEY, PADDLE_CLIENT_TOKEN, PADDLE_PRICE_ID (pri_01kz18h08y4yq9pyh05axvaczj = RunIndex PREMIUM 4,99€/mo), PADDLE_WEBHOOK_SECRET (notif dest "PREMIUM", 4 events), PADDLE_ENVIRONMENT=sandbox.
- Paddle default payment link / domain approved in dashboard.
- Validated: /api/subscription/paddle/config → configured:true; /paddle/checkout creates real transaction (200); browser test → Paddle overlay opens with no error (fr-FR locale). The "en-US@posix" error was a headless-locale artifact only.
- Added data-testid="premium-subscribe-btn" to Subscription.jsx premium button.
- REMAINING: real test-card payment (webhook → Premium) to be done manually; for PRODUCTION, replicate the 5 PADDLE_* vars + webhook destination/domain on the prod URL.


## Changelog — Free trial button fix (August 1, 2026)
- Bug: "Démarrer mon essai gratuit" (Subscription.jsx) called handleSubscribe → Paddle checkout (card required) instead of activating a free trial.
- Backend: new `POST /api/subscription/start-trial` (auth JWT, user["id"] only) — activates 30-day trial, no card, no Paddle; refuses a 2nd trial (409 via `trial_used`).
- Frontend: hero button now calls start-trial for Free users (handleSubscribe/Paddle kept for premium subscribe). i18n keys `trialStarted`/`trialAlreadyUsed` (FR/EN).
- Tests: `backend/tests/test_start_trial.py` (3 passed): 401 no-JWT, Free→trial no-card, 2nd trial→409. E2E confirmed (free→trial, is_premium True).


## Changelog — Garmin per-user connection fix (August 1, 2026)
- Removed global .env credential fallback (`GARMIN_USERNAME`/`GARMIN_PASSWORD`) for user connections in `garmin/providers/gccli_provider.py` (new `allow_global_account` flag; only bootstrap may use env).
- `garmin/factory.py`: `get_provider_for_user` → `allow_global_account=False`; `get_provider` (bootstrap) → `True`.
- Frontend `Onboarding.jsx`: each user now enters their own Garmin email+password (fixes 422 empty-body call); password cleared after success. i18n keys added.
- Isolation: JWT-only identity (`current_user["id"]`), per-user `GCCLI_HOME/{user_id}`, all Mongo scoped by `user_id`; no creds in API responses/logs.
- Tests: `backend/tests/test_garmin_user_connection.py` (58 Garmin tests pass). E2E: 401 no-JWT, 422 no-creds, error on fake creds (never global data). `yarn build` OK.
- Report: `/app/GARMIN_FIX_REPORT.md`. Verdict: GARMIN READY (gccli unofficial; real login depends on user's Garmin/MFA — documented limitation).


## App Overview
RunIndex — running/cardio training coach. Garmin (gccli) integration, AI coach (LLM), RunIndex/readiness engines, training plans, Stripe subscriptions, Terra integration.

## Tech Stack
- Backend: FastAPI + Motor (MongoDB), emergentintegrations (Emergent LLM key), Stripe, Redis (jobs/queue/SSE/workers)
- Frontend: React 19 + CRACO + Tailwind + Radix UI + recharts
- Services (supervisor): backend:8001, frontend:3000, mongodb, redis:6379 (added)

## Setup Done (2026-07-07)
- Cloned repo into /app (preserved platform .git/.emergent, kept protected .env vars)
- Installed backend requirements + frontend yarn deps
- backend/.env: added EMERGENT_LLM_KEY, STRIPE_API_KEY=sk_test_emergent, FRONTEND_URL, REDIS_URL
- Added redis supervisor service using vendored /app/bin/redis-server (LD_LIBRARY_PATH=/app/lib)
- Fixed bug in frontend/plugins/visual-edits/babel-metadata-plugin.js (null parentPath.parentPath crash) that blocked webpack build (Coach.jsx)
- Verified: dashboard + Coach pages render, /api/stats /api/dashboard/insight return data, gccli auto-installed at startup

## Notes
- gccli Garmin login only triggers if GARMIN_PROVIDER=gccli (not set) — no Garmin creds required to boot
- Celery/worker processes (sync/monitor/scheduler) are separate; not started by API

## Backlog / Next
- Configure Garmin credentials (GARMIN_USERNAME/PASSWORD/GARMIN_PROVIDER) for real sync if desired
- Start worker processes if background sync/SSE features are needed

## Garmin Connected (2026-07-07)
- backend/.env: GARMIN_PROVIDER=gccli, GARMIN_USERNAME, GARMIN_PASSWORD set (account: mallegolbrieg@gmail.com)
- gccli one-time headless login succeeded; OAuth token persisted at /app/backend/.gccli_home (auto-refreshes)
- Added 4 worker supervisor services: garmin-sync-worker, garmin-event-worker, garmin-scheduler-worker, garmin-monitor-worker
- Verified end-to-end: 30 activities + 30 derived workouts + 7 daily metrics synced; RunIndex 390/1000, Run Readiness 77, RHR 47, Sleep 7.7h
- Scheduler auto-enqueues incremental syncs (~60s scan); event worker builds workouts layer + SSE feed

## Pull sauvegarde260708 — newer version (2026-07-08)
- Pulled commit 9fe9e8c (Merge PR #2). ~60 code files updated vs previous; deps unchanged; babel fix already included upstream.
- rsynced into /app preserving .git/.emergent/.env/.gccli_home/bin. Garmin creds + workers intact.
- API root now "RunIndex API" (rebrand); queue renamed runindex:garmin:queue.
- All services healthy; gccli session reused; Garmin still connected (30 activities). Dashboard renders (RunIndex 390, Readiness 77).

## Branding RunIndex (2026-07-08)
- New logo integrated: header (Layout.jsx) now uses /runindex-logo.png (background keyed out from original navy JPG -> transparent PNG via PIL)
- Full logo added to Onboarding welcome screen + new BrandSplash loading screen (LoadingSpinner.jsx) used on Dashboard initial load (pulse animation)
- Regenerated favicon/PWA icons (72-512px) with the green "R" mark on navy
- Created light-background logo variant /runindex-logo-light.png (dark navy "Run" text) for light surfaces / print / emails

## Pull sauvegarde260708 — Sessions tab (2026-07-09)
- Pulled commit 9909760 (Merge PR #3 "sessions tab"). New: pages/Sessions.jsx, pages/SessionDetail.jsx; modified App.js (routes /sessions, /sessions/:id), Layout.jsx (nav item), i18n.js (sessions translations en/fr/es).
- BUG in pulled code: `sessions` i18n block was nested under `workout` -> pages call t("sessions.*") -> raw keys shown. FIXED in lib/i18n.js by promoting workout.sessions to a top-level `sessions` alias per language (post-object normalization loop).
- Verified: Sessions list (30 Garmin activities, filters/sort/search translated) + SessionDetail (metrics + AI analysis sections) render correctly. Branding (logo) preserved.

## Pull sauvegarde260708 — PR #12 Garmin deep history sync (2026-07-10)
- Pulled commit d5fac75. runner.fetch_activities now supports --start pagination; gccli_provider.fetch_all_activities() paginates; garmin/service.deep_sync() imports full history once (gated by deep_sync_done, GARMIN_DEEP_SYNC_ENABLED default true), then RunIndex backfill. New test_garmin_deep_sync.py.
- 21/21 tests pass. Triggered one-time deep_sync for existing user default: imported ALL 141 activities (111 new), back to 2024-11-23 (was 30, oldest 2026-01-21). workouts=141.
- Re-ran RunIndex backfill: now 50 snapshots, oldest 2025-07-09 (365-day window); /run-index/history 12m returns 13 monthly pts, has_full_period_data=True. Progress graph richly populated across 6/12m.
- Note: history graph capped at 365 days by design (HISTORY_WINDOW_DAYS); activities stored back to Nov 2024 but curve shows max 12 months.

## Feature: race countdown in Training tab active state (2026-07-12)
- Found upcoming/completed cycle states already wired (banners + weeksToStart + daysToRace + plan start date). Only missing piece: countdown for ACTIVE cycles.
- Added i18n key trainingPlanExtended.raceCountdown (en "D-{days} to race" / fr "J-{days} avant la course" / es "F-{days} para la carrera").
- TrainingPlan.jsx: added amber J-X/D-X badge (data-testid="active-race-countdown") next to "Week X/Y • goal" when status active and days_to_race>=0.
- Verified live: active cycle (event +70d) shows "D-70 to race"; no compile errors. Default user goal restored to none.

## Bug fix: free trial not working (2026-07-12)
Reported: "activate free trial ... cela ne fonctionne pas". Two-layer root cause (found via testing_agent):
1. Backend /api/subscription/status only recognized Stripe status=='active' -> trial users showed tier='free' on Subscriptions page. FIX: added elif branch recognizing trial/early_adopter/premium (is_premium, unlimited, tier_name). Also reset-to-trial now uses TRIAL_DURATION_DAYS (30).
2. Backend subscription_middleware get_user_id_from_request (server.py:244) ignored the X-User-Id header the frontend sends -> attributed requests to IP user (free) -> 403 on /workouts, /training/* -> Training/Sessions paywalled. FIX: read X-User-Id header before IP fallback.
3. Frontend Sessions.jsx fetched /workouts without X-User-Id header -> empty list. FIX: pass headers {X-User-Id: USER_ID}.
Added trial banner on /subscription (data-testid=trial-active-banner) + i18n subscription.trialActive.
Verified: testing_agent iteration_26 (Training paywall gone, backend 8/8 pytest); self-test screenshot Sessions list populated with Garmin activities. default user on active 30-day trial.

## Bug fix: session AI analysis not displaying (2026-07-12)
Reported: "l'analyse IA de séance ne s'affiche pas". Root cause: WorkoutDetail.jsx 4 axios calls (/workouts/:id, /coach/workout-analysis, /coach/detailed-analysis, /rag/workout) sent NO X-User-Id header -> protected analysis endpoints returned 403 for the IP/free user -> analysis empty.
FIX: global axios request interceptor in src/index.js injecting X-User-Id=USER_ID('default') on all /api requests (also prevents recurrence app-wide, per testing_agent recommendation).
Verified by testing_agent iteration_27: 100% backend+frontend, analysis renders end-to-end, no regressions on sessions/training/progress/subscription. retest_needed=false.

## Pull sauvegarde260708 — PR #16 (subscription architecture) + latent chat bug fix (2026-07-12)
- Pulled commit 29fce67. Modified server.py, Subscription.jsx, i18n.js + test_subscription_chat.py. All my prior fixes (X-User-Id middleware, trial recognition in /subscription/status, global axios interceptor, trial banner, i18n aliases) were present in the backup (pushed via Save to GitHub) -> no regression.
- LATENT BUG found & fixed: POST /api/chat/send quota only recognized Stripe status=='active' -> trial users blocked after 10 messages ("reached your limit (Free)"). FIX (server.py ~4976): added elif for trial/early_adopter/premium -> unlimited chat (messages_limit=999, unlimited=True). Also relaxed a test assertion for unlimited plans.
- Verified: testing_agent iteration_28 -> 100% backend+frontend, 25/25 pytest, chat unlimited on trial, no paywall, no regressions. retest_needed=false.
- Backlog notes (non-blocking): extract a shared tier->is_unlimited resolver to avoid drift between /subscription/status and chat quota; don't increment messages_used for unlimited tiers; Settings Event Date could use shadcn Calendar instead of native picker.

## 2026-07-27 — Retour à la PR #16 (revert PR #17 Supabase)
- La PR #17 (auth Supabase obligatoire) a été retirée : insertion automatique corrompue de `user_id = user["id"]` (44 occurrences, dont une dans un corps de classe) faisait planter le backend au démarrage (NameError), + config Supabase manquante + risque de perte des données "default".
- Décision utilisateur : revenir à la PR #16.
- Action : re-sync du commit `29fce67` (PR #16) depuis GitHub dans /app, en préservant .env, .git, .emergent, session Garmin (.gccli_home), binaire gccli (bin/), node_modules et /app/memory. Fichiers Supabase supprimés (backend/auth, frontend supabase.js/AuthContext/Login/Signup). package.json sans @supabase.
- Vérifié : backend démarre proprement, session Garmin retrouvée, 141 workouts, run-index history 12m (12 points, current 352), abonnement trial 29 j, Dashboard s'affiche correctement (screenshot).
- auth_user (PR16) = auth flexible avec fallback "default" (non-bloquant).

## 2026-07-27 — Pull branche PR16Bis
- Synchronisé la branche PR16Bis (head 4d96cc3, PR #19) : retire le gate Supabase cassé, ajoute durcissement (demo_mode fail-fast en prod, vérif signature webhook Stripe via services/stripe_webhook_security.py, CORS strict en prod). yarn.lock régénéré.
- Vérifié : backend démarre, session Garmin OK, 141 workouts, run-index history OK, sub trial 29j, Dashboard rend correctement, aucun gate de login.
- ⚠️ 2 bugs détectés dans la branche (non corrigés, en attente décision user):
  1. /api/chat/send (server.py:5014) ne reconnaît que status=="active" → ignore trial/early_adopter/premium → limite Free imposée aux users en essai (régression vs PR16).
  2. /api/training/today (server.py:3549) crash 500 quand aucun plan (generate_dynamic_training_plan renvoie None, `plan.get` sur None).

## 2026-07-27 — Pull PR16Bis (PR #22, head 25835ec)
- Chat IA : trial → tier "pro" (illimité). VÉRIFIÉ OK (réponse coach retournée).
- ⚠️ training/today (server.py:3556) TOUJOURS cassé (500) : garde-fou incomplet, `plan["plan"]` peut être None. Fix restant: `sessions = (plan.get("plan") or {}).get("sessions", [])`. Non corrigé upstream.

## 2026-07-27 — Correctif local training/today (patch ciblé)
- server.py:3556 : `plan.get("plan", {})` -> `(plan.get("plan") or {})`. Corrige le crash 500 quand `plan["plan"]` est None (cycle upcoming/sans plan actif).
- VÉRIFIÉ via curl (URL externe) :
  - CASE 1 (aucun plan actif / upcoming) -> HTTP 200, réponse gracieuse, aucun traceback.
  - CASE 2 (plan actif, 7 séances) -> HTTP 200, status "success" avec planned_session + adaptive_session. (testé via objectif temporaire puis état restauré à l'identique).
- À COMMITTER côté GitHub via "Save to Github" (message: "Fix training today null plan guard") sinon écrasé au prochain pull.

## 2026-07-28 — Pull PR22 (auth JWT multi-utilisateurs, head 8155aa1)
- Ajoute module backend auth/ (JWT custom: register/login/me/forgot/reset), frontend Login/Register/ForgotPassword/ResetPassword + AuthContext, App.js gated (login obligatoire). Interceptor axios envoie Bearer JWT (plus de X-User-Id).
- backend auth_user: valide JWT (sub=UUID), garde fallback X-User-Id/query param (legacy Step2), sinon "unauthenticated".
- JWT_SECRET_KEY généré et ajouté à backend/.env. yarn.lock régénéré. Fix training/today présent upstream aussi.
- VÉRIFIÉ: register/login/me OK, login screen rendu.
- ⚠️ MIGRATION INCOMPLÈTE (Step 2 pending par design):
  - /subscription/info et d'autres endpoints gardent user_id="default" en dur -> ignorent le JWT.
  - /workouts utilise l'UUID JWT -> nouvel user bloqué "free" (pas de trial auto-créé).
  - 141 activités restent sous "default"; nouvel user voit une app vide.
  - Frontend n'envoie plus X-User-Id -> le propriétaire ne voit plus ses données via l'UI sans migration.
- Compte test: testrunner@runindex.app / Test1234! (voir test_credentials.md).

## 2026-07-28 — Pull PR22 mis à jour (PR #25 "ÉTAPE 2/3", head 72a77bb)
- auth_user exige désormais un JWT (fallbacks X-User-Id/query supprimés -> 401/403). Trial 30j auto-créé à l'inscription (auth/router.py). /subscription/info et handlers migrés vers JWT.
- VÉRIFIÉ: register->trial(29j, UUID), /subscription/info JWT OK, no-auth=403, X-User-Id=default=401.
- ⚠️ BUG RESTANT (dernier blocage): le middleware d'abonnement (server.py:397) utilise get_user_id_from_request (server.py:284) qui lit query param -> header X-User-Id -> IP, PAS le JWT. Donc /workouts, /training/*, /coach/* (routes protégées) sont bloquées 403 pour un user JWT-only (middleware résout l'IP au lieu de l'UUID).
  - Preuve: /workouts JWT seul=403 ; /workouts?user_id=<UUID> JWT=200 [].
  - FIX upstream: dans get_user_id_from_request, décoder le Bearer JWT en premier (comme auth_user) et retourner payload['sub'] avant les fallbacks query/header/IP.
- Comptes test créés: isotest_*@runindex.app / Test1234! (jetables).

## 2026-07-28 — Pull PR22 (PR #26, head 987dc26)
- PR #26 corrige le middleware: get_user_id_from_request décode le JWT en premier (fix recommandé appliqué upstream). Backend multi-user JWT VÉRIFIÉ 100%: workouts JWT=200[], training/today=200, subscription/info=trial+UUID, no-auth=403, chat trial illimité=reply.
- CORRIGÉ EN LOCAL: Subscription.jsx chaînes non terminées lignes 186 ET 198 (guillemets manquants) -> build frontend réparé. Scan de tous les .jsx/.js: aucun autre fichier affecté. VÉRIFIÉ: register via UI -> dashboard (compte isolé vide, "Connect Garmin", séance du jour), routes protégées OK. À COMMITTER sur GitHub (Save to Github).

## 2026-07-29 — Pull PR22 (PR #32, head 74ed67c)
- Nouveau backend/access_control.py: source unique de vérité pour les décisions d'accès (tiers FREE/TRIAL/PREMIUM, fail-closed sur erreur DB, identité toujours via JWT, guard DEMO_MODE+production à l'import). Intégré dans server.py (middleware, /subscription/status) + nouvel endpoint /api/user/features. subscription_manager.py modifié.
- La branche a intégré mon correctif Subscription.jsx (lignes 186/198 OK). Frontend inchangé vs état précédent.
- VÉRIFIÉ: register->trial, workouts JWT=200[], subscription/status=trial/premium(msg 999), /api/user/features renvoie plan+feature_access, no-auth=401, login screen rendu.
- AST syntax check OK sur access_control.py, server.py, subscription_manager.py.

## 2026-07-29 — Pull PR22 (PR #34, head a6034ba) — Migration Stripe→Paddle
- Backend: paddle_webhook_security.py + endpoints /subscription/paddle/checkout, /subscription/paddle/config, /webhook/paddle. Env vars (os.environ.get, défauts vides): PADDLE_API_KEY, PADDLE_WEBHOOK_SECRET, PADDLE_ENVIRONMENT(sandbox), PADDLE_PRICE_ID, PADDLE_CLIENT_TOKEN. Backend démarre sans clés; checkout->503 "Paddle not configured", config->configured:false, webhook->rejeté.
- Frontend: @paddle/paddle-js installé; Paywall/Subscription/Settings/SubscriptionContext MAJ. Backend AST OK.
- VÉRIFIÉ: register->trial, workouts/user/features JWT OK, subscription page rend, dashboard rend.
- BLOCAGE CORRIGÉ (local): Paywall.jsx:180 `PREMIUM_OFFER.features.map()` provoquait récursion infinie dans frontend/plugins/visual-edits/babel-metadata-plugin.js -> build cassé. Fix: propager garde skipArrayContext dans analyzeMemberExpression (appel getArrayIterationContext + appel analyzeIdentifier). Cache node_modules/.cache purgé, frontend recompile OK.
  - ⚠️ Plugin versionné dans la branche -> fix écrasé au prochain pull. Options: committer le fix plugin OU modifier Paywall.jsx (destructurer features avant .map).
- Paddle NON FONCTIONNEL tant que les clés sandbox ne sont pas fournies par l'utilisateur.

## 2026-07-30 — Paddle Sandbox E2E + Fix Paywall (périmètre Paddle uniquement)
- Paywall FIX PÉRENNE: Paywall.jsx refactorisé (destructuration `const {offer_name, features, cta_button} = PREMIUM_OFFER;` -> `features.map`), plugin visual-edits/babel-metadata-plugin.js RESTAURÉ à l'original (patch temporaire retiré). Build "Compiled successfully!" sans patch. Page rend.
- Backend Paddle audité: checkout (user_id via JWT, jamais frontend), config (aucun secret exposé, configured=bool(client_token&&price_id)), webhook (raw body -> vérif signature HMAC-SHA256 ts:body -> idempotence paddle_events sur event_id -> activate_premium via subscription_manager -> access_control). Frontend: client_token public only, env forcé sandbox sauf backend=production, onPaymentSuccess -> refreshSubscription() (aucun octroi local). SubscriptionContext FAIL-CLOSED (status:free + features false sur erreur).
- Tests: 48 PASS (tests/test_paddle_subscription.py) couvrant signature/tamper/malformed/idempotence/isolation/activation/renew/cancel/expiration/free-quota/fail-closed/legacy tiers.
- Live: trial=premium access+999msg, free=10msg+premium bloqué, unsigned webhook rejeté (500 car PADDLE_WEBHOOK_SECRET absent).
- ⚠️ BLOQUÉ: aucune clé PADDLE_ dans l'env -> config live=false, checkout overlay/paiement sandbox réel/webhook live depuis Paddle NON testables. Nécessite: PADDLE_CLIENT_TOKEN, PADDLE_API_KEY, PADDLE_WEBHOOK_SECRET, PADDLE_PRICE_ID (sandbox).
- NON déclaré "Sandbox Ready" ni "Production Ready".

## 2026-07-30 — Pull PR22 (PR #38 trial freemium + Garmin trial, head 44dc1c4) — BACKEND DOWN
- Paywall.jsx re-refactorisé en local (fix pérenne non committé upstream) -> frontend compile OK.
- ⚠️ BACKEND 502 (crash import): backend/api/garmin.py CORROMPU par PR#38:
  1. En-tête DUPLIQUÉ (2x docstring + 2x `from __future__ import annotations`); le 2e (ligne 44) est illégal -> SyntaxError.
  2. Ligne 61: `from auth.supabase_jwt import extract_user_id` -> module inexistant (auth/ = JWT jwt_utils.py). ModuleNotFoundError.
  - server.py:6014 `from api.garmin import garmin_router` non protégé -> toute l'API tombe.
- Fix upstream requis (dans api/garmin.py): (a) supprimer le bloc d'en-tête dupliqué (garder 1 seul, `from __future__` en tout début), (b) remplacer l'import supabase par: `from auth.jwt_utils import decode_access_token` et dans _resolve_user_id utiliser `decode_access_token(creds.credentials).get("sub")`.
- Toujours aucune clé PADDLE_ dans l'env.
- STOP + report (code Garmin protégé + décision requise). Fix local non appliqué sans accord.

## 2026-08-04 — Dashboard: encart Run Readiness aligné sur RunIndex
- Suppression du bloc comparatif "RunIndex vs état du jour" (Dashboard.jsx + i18n).
- Run Readiness transformé en encart identique à RunIndex (même dégradé/bordure/ombre): label vert "RUN READINESS", sous-titre blanc, grand chiffre `text-6xl font-black` coloré selon l'état de forme (vert/orange/rouge) suivi de "/ 100" vert, pastille de recommandation + refresh en haut à droite.
- Composantes VFC/FC/Sommeil/Charge/Ratio affichées en style piliers RunIndex (choix user: option b): barre pleine colorée selon le statut (vert/orange/rouge) + vraie valeur à droite (ex: +6 ms, 52 bpm, 7.2 h, 1.42, 1.18), SANS pourcentage inventé.
- Nouveau composant `ReadinessPillar` dans Dashboard.jsx; nouvelles clés i18n `dashboard.readinessPillars.{hrv,rhr,sleep,load,ratio}` FR/EN/ES. Anciens `MetricWidget`/decision-card retirés du rendu.
- data-testid: run-readiness-card, run-readiness-title, run-readiness-score, run-readiness-recommendation, run-readiness-refresh, run-readiness-pillars, readiness-pillar-{hrv,rhr,sleep,load,ratio}.
- Vérifié: frontend "Compiled successfully"; screenshot (données interceptées) confirme carte jumelle RunIndex, score 68/100 orange, 5 barres de statut + valeurs. Backend inchangé.

## 2026-08-04 — Run Readiness: TSB building, mini-historique 7j, tap-info
- **TSB « base en construction »**: backend `/api/training/metrics` renvoie `tsb_reliable` (= acwr_reliable) et `tsb_status="building"` en reprise (deep/partial). TrainingPlan.jsx affiche « — / Base en construction » (gris) comme l'ACWR. i18n `dashboard.tsb_status.building` FR/EN/ES. Vérifié: curl (tsb_reliable=false, tsb_status=building) + screenshot /training (— / Baseline building).
- **Mini-historique 7 jours**: backend insights.py ajoute `run_readiness` par jour dans `history` (100 - physio_penalty_jour - acwr_penalty). Dashboard.jsx affiche une courbe `MiniLineChart` sous les tuiles ("7-DAY READINESS" + score du jour + labels jours). data-testid `readiness-trend`.
- **Détail au tap**: chaque `ReadinessTile` est un bouton (icône ⓘ + point d'état) qui ouvre un `Dialog` (shadcn) avec explication courte de la composante. i18n `dashboard.readinessInfo.{hrv,rhr,sleep,load,ratio}` FR/EN/ES. data-testid `readiness-info-dialog`.
- ⚠️ LEÇON: NE PAS faire plusieurs `search_replace` en parallèle sur le MÊME fichier — une course a fait perdre l'import `Dialog` et créé un bloc dupliqué en fin de Dashboard.jsx (corrigé). Éditer un même fichier séquentiellement.
- Vérifié: frontend "Compiled successfully"; screenshots Dashboard (tuiles+courbe+dialog) et /training (TSB building). Backend inchangé sur ACWR/compute_current_weekly_km.

## 2026-08-04 — Run Readiness: 4 tuiles + courbe ACWR par jour
- Tuile "Ratio fatigue" retirée du front (Dashboard.jsx). Grille passée à `grid-cols-2 sm:grid-cols-4` → 4 tuiles (VFC, FC, Sommeil, Charge) sur une ligne.
- Courbe 7 jours plate corrigée: insights.py calcule désormais un **ACWR glissant par jour** (`_compute_acwr(activities, jour)`) au lieu de réutiliser l'ACWR global pour chaque jour. `run_readiness` par jour = 100 - physio_penalty_jour - acwr_penalty_jour. `history.training_load` = ACWR du jour.
- Données réelles confirmées: `garmin_daily_metrics` a ~8 jours/user (RHR+sommeil réels; HRV non enregistrée par l'appareil → affiche "—"). Après fix, readiness historique varie: ex default `[48,65,40,76,75,77,77]`, user reprise `[70,70,70,70,100,38,25]`.
- Note: platitude résiduelle possible = réelle (athlète frais ACWR~1 → ~100 ; surcharge continue → plancher). HRV manquante réduit la variation physiologique.
- Vérifié: compute_run_index (python), frontend "Compiled successfully" + screenshot (4 tuiles + courbe variée). ACWR "today" et compute_current_weekly_km inchangés.
