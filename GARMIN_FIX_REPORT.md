# Garmin Fix Report

Branche : PR34 (HEAD PR#61) · Date : 1er août 2026 · Périmètre : connexion Garmin par utilisateur.
Contraintes respectées : aucun changement Paddle / abonnements / JWT / PR59 / PR61 / PR62 / Google OAuth ;
aucun refactor massif ; autres providers (Terra, Apple, Fitbit, Whoop) laissés désactivés et intacts.

## 1. Cause exacte

Deux défauts distincts empêchaient une connexion Garmin correcte et multi-utilisateur :

1. **Frontend (symptôme 422).** `frontend/src/pages/Onboarding.jsx` appelait
   `POST /api/garmin/connect` avec un corps vide `{}`. Or `GarminConnectRequest`
   exige `garmin_username` + `garmin_password` → **422 Unprocessable Entity**.

2. **Backend (fallback global silencieux — faille multi-user).** Dans
   `garmin/providers/gccli_provider.py`, la connexion retombait sur les
   identifiants globaux du `.env` :
   - `_account()` → `self._garmin_account or get_secret("GARMIN_USERNAME")`
   - `connect()` → `account = garmin_username or self._account()` et
     `password = garmin_password or get_secret("GARMIN_PASSWORD")`.

   Conséquence : un utilisateur sans identifiants aurait été **connecté au compte
   Garmin global partagé** sous son propre `GCCLI_HOME/{user_id}`, récupérant les
   141 activités globales → fuite de données / identité utilisateur invalide.

## 2. Correction effectuée

**Backend — suppression totale du fallback global pour les connexions utilisateur :**
- `garmin/providers/gccli_provider.py`
  - `GccliProvider.__init__` : ajout du flag `allow_global_account: bool = False`.
  - `_account()` : ne retourne les identifiants `.env` **que** si `allow_global_account=True`
    (réservé au bootstrap). Sinon retourne l'account par-utilisateur ou `None`.
  - `connect()` : l'account et le mot de passe proviennent **exclusivement** des
    identifiants fournis par l'utilisateur authentifié (ou du token per-user déjà
    présent en cas de reconnexion). Plus aucun `get_secret("GARMIN_*")` pour un user.
    Si les identifiants manquent → `STATUS_ERROR` clair (« Garmin credentials required »).
- `garmin/factory.py`
  - `get_provider_for_user(...)` → `allow_global_account=False` (jamais de `.env`).
  - `get_provider()` (bootstrap uniquement) → `allow_global_account=True`.

**Frontend — chaque utilisateur connecte SON propre compte Garmin :**
- `frontend/src/pages/Onboarding.jsx` : ajout de deux champs (`garmin-email-input`,
  `garmin-password-input`), envoi de `{garmin_username, garmin_password}` à
  `/garmin/connect`, validation côté client, et **effacement du mot de passe** de
  l'état dès que la connexion réussit.
- `frontend/src/lib/i18n.js` : nouvelles clés FR/EN (hint + placeholders + message).

**Non modifié** : `api/garmin.py` (déjà JWT + `user_id = user["id"]`), `service.py`
(déjà scoping par `user_id`, identité trial dérivée server-side), Paddle, abonnements.

## 3. Architecture Garmin actuelle

```
Frontend (Onboarding) --{garmin_username, garmin_password}--> POST /api/garmin/connect
   → JWT obligatoire (get_current_user)  →  user_id = current_user["id"]
   → service.connect(db, user_id, garmin_username, garmin_password)
   → get_provider_for_user(user_id, account)  [allow_global_account=False]
       HOME = GCCLI_HOME/{user_id}/   (token gccli isolé par utilisateur)
   → GccliProvider.connect() → GccliRunner.login(email, password)  (one-shot, PTY)
       gccli persiste un token OAuth par-utilisateur ; mot de passe jamais stocké
   → succès : upsert garmin_connections{user_id}, identité trial dérivée server-side
   → sync (worker) → garmin_activities{user_id} → workouts{user_id}
```
gccli reste le connecteur (décision produit : conservé jusqu'à ~1 000 utilisateurs).

## 4. Isolation utilisateur

- ✅ Identité **uniquement** via JWT (`current_user["id"]`) sur toutes les routes `/api/garmin/*`.
  Plus de `user_id=default`, plus de `X-User-Id`, plus de `user_id` fourni par le frontend.
- ✅ `GCCLI_HOME/{user_id}/` → token/session gccli isolé par utilisateur (aucun partage).
- ✅ Toutes les écritures/lectures MongoDB scoping strict `{"user_id": user_id}`
  (`garmin_connections`, `garmin_activities`, `garmin_daily_metrics`, `workouts`).
- ✅ Un utilisateur sans identifiants n'est **jamais** connecté au compte global.
- ✅ Aucun identifiant Garmin retourné à l'API frontend (réponse = `{status, message, provider}`).
- ✅ Aucun identifiant écrit dans les logs (message d'erreur générique, pas de sortie brute PTY).

## 5. Autres providers

Terra / Apple Health / Fitbit / Whoop : **non réactivés, non modifiés, non supprimés**.
Aucune modification apportée à leur code.

## 6. Tests exécutés

Nouveau fichier `backend/tests/test_garmin_user_connection.py` :
- per-user connect sans identifiants → erreur, **aucun appel `login`**, **aucun accès `.env`** ;
- `_account()` per-user = `None` (pas de fallback), bootstrap = compte `.env` ;
- connect utilise les identifiants fournis (jamais l'`.env`) ;
- username sans mot de passe → rejet, sans fallback `.env` ;
- identifiants absents du `ConnectResult` ;
- `service.connect` persiste sous le `user_id` authentifié ;
- `list_activities` toujours filtré par `user_id`.

Vérifications E2E (URL externe) :
- `POST /api/garmin/connect` sans JWT → **401** ;
- avec JWT + corps vide → **422** (identifiants requis, pas de fallback global) ;
- avec JWT + faux identifiants → `status:error` (**jamais** connecté au compte global) ;
- nouvel utilisateur → aucune activité globale visible.

Suites : `pytest` (tests Garmin) + `yarn build` (build production).

## 7. Résultats

- Tests unitaires Garmin ciblés : **58 passed** (dont les nouveaux du fix).
- E2E connexion : 401 / 422 / erreur-sur-faux-compte / isolation → **tous conformes**.
- `yarn build` : **Compiled successfully** (build production OK).
- Dev server : **Compiled successfully** après les modifications.
- Backend : démarre normalement, endpoints sains.

> Note : la suite `pytest` complète comporte de nombreux échecs **préexistants et
> environnementaux** (tests d'intégration nécessitant un serveur live + `REACT_APP_BACKEND_URL`
> non exporté dans le shell backend, et une fixture Redis `r` absente). Ils sont **sans lien**
> avec ce correctif (fichiers `test_queue_health`, `test_sync_scheduler`, `test_new_features`, etc.).

## 8. Limitations restantes

- **gccli est un connecteur non officiel** (scraping Garmin Connect). Une connexion
  utilisateur réelle dépend du compte Garmin de l'utilisateur : Garmin peut exiger une
  **MFA** ou bloquer les logins automatisés (le code renvoie alors proprement `mfa_required`
  ou `error`, sans simulation).
- **Aucune connexion réussie sur un second compte Garmin réel n'a pu être validée E2E**
  dans l'environnement preview (aucun identifiant Garmin de test disponible). La sécurité,
  l'isolation et l'absence de fallback global sont, elles, entièrement validées.
- **Identité anti-abus trial** = e-mail Garmin dérivé server-side (normalisé), pas un ID
  Garmin numérique persistant (limite intrinsèque de gccli).
- **Saisie du mot de passe Garmin** dans RunIndex (modèle gccli) : acceptable pour cette
  phase mais moins idéal qu'un flux délégué.

## 9. Verdict

**GARMIN READY** — pour l'objectif de ce ticket : connexion Garmin **par utilisateur**,
identité **JWT uniquement**, **isolation stricte** des données, **suppression totale** du
fallback vers les identifiants globaux `.env`, aucun identifiant retourné à l'API ni écrit
dans les logs. Correctif réel (non simulé) : chaque utilisateur se connecte à son propre
compte Garmin via un token gccli isolé.

Réserve documentée (§8) : la réussite d'un login réel dépend du compte Garmin de l'utilisateur
(MFA / anti-bot) et de la fiabilité de gccli ; une architecture OAuth Garmin officielle ou un
agrégateur (Terra) serait nécessaire pour une identité persistante robuste et une fiabilité
à grande échelle — hors périmètre de cette phase (décision produit : gccli conservé).
