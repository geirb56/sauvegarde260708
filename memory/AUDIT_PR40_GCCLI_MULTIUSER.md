# AUDIT PR#40 — GCCLI Multi-user + Identité Garmin + Trial

> **AUDIT READ-ONLY.** Aucun code applicatif, env, MongoDB ou GCCLI modifié.
> Branche : PR34 (HEAD `0be0a45`, merge PR#40 « Phase 3A — GCCLI multi-user isolation »).
> Date : Juin 2026. Contrainte respectée : **on conserve GCCLI** (pas d'OAuth officiel).

---

## 1. VERDICT GLOBAL

### ❌ NOT READY (pour le modèle commercial FREE → Trial → Premium)

- ✅ **L'isolation multi-user GCCLI est globalement correcte et solide.** (READY WITH FIXES mineurs)
- ❌ **La règle « 1 Garmin = 1 Trial » n'existe PAS en exécution** : `activate_garmin_trial()` n'est
  appelée **nulle part** dans le code applicatif, `_GARMIN_IDENTITY_AVAILABLE = False`, et le flux
  `connect` n'écrit jamais dans `garmin_trial_registry`. **Aucun utilisateur ne reçoit de Trial.**
- ❌ **Le funnel commercial est bloqué** : `/api/garmin/*` est classé **PREMIUM** dans
  `access_control.py`. Un nouveau compte (FREE) est **bloqué en 403** par le middleware AVANT de pouvoir
  connecter Garmin. Il ne peut donc jamais déclencher son Trial. Impasse totale (chicken-and-egg).

➡️ En l'état, PR#40 livre une **infrastructure multi-user propre**, mais **le produit commercial ne
fonctionne pas** : un nouveau user reste FREE à vie, ne peut pas connecter Garmin, et n'obtient jamais de Trial.

---

## 2. ISOLATION MULTI-USER

| Élément | État | Risque | Preuve |
|---|---|---|---|
| JWT obligatoire sur `/api/garmin/*` | ✅ | — | `api/garmin.py` : chaque route a `user: dict = Depends(get_current_user)` (l.67,91,106,136,162,186,204,233,242) |
| `user_id` dérivé du JWT | ✅ | — | `user_id = user["id"]` sur toutes les routes ; jamais de query param `user_id` |
| Aucun `user_id` fourni par le frontend | ✅ | — | `GarminConnectRequest` (l.47-61) ne contient PAS de `user_id` |
| Absence de `"default"` | ✅ (nouveau code) | ⚠️ legacy | Plus aucun défaut `"default"` dans `api/garmin.py`. Restent 141 activités legacy `user_id="default"` en base (orphelines, inaccessibles via JWT) |
| Séparation `GCCLI_HOME` par user | ✅ | LOW | `factory.get_provider_for_user()` : `user_home = os.path.join(_base_home(), user_id)` (l.39) → token gccli isolé par UUID |
| Séparation données MongoDB | ✅ | — | Toutes les requêtes filtrent `{"user_id": user_id}` : `garmin_connections`, `garmin_activities`, `garmin_daily_metrics`, `workouts` (`service.py` partout) |
| Séparation fichiers/cache/session | ✅ | LOW | `GccliRunner._env()` force `HOME=self.home` + `GCCLI_ACCOUNT` par appel ; subprocess isolé |
| Données Garmin accessibles par un autre user | ❌ non trouvé (bon) | — | Aucun chemin ne lit les activités sans filtre `user_id` |
| Variables globales / singleton dangereux | ✅ corrigé | — | `@lru_cache(maxsize=1)` **supprimé** de la factory ; instances provider créées par requête |
| Concurrence entre 2 users | ✅ | LOW | HOME distinct par UUID → pas de collision de token entre users |
| Concurrence sur le **même** user (2 requêtes // ) | ⚠️ | LOW | Même `GCCLI_HOME/{user_id}` → accès concurrent au keyring gccli possible (rare, peu impactant) |
| Path traversal via `user_id` dans `os.path.join` | ⚠️ | LOW | `user_id` = UUID généré serveur (JWT `sub`), non contrôlable par l'attaquant → risque théorique nul tant que l'ID reste un UUID |

**Accès indirects vérifiés** : worker de sync (`get_provider_for_user(user_id, ...)`), backfill
(`backfill_user(db, user_id)`), SSE (`event_stream(user_id, ...)`), cache feed (`realtime_cache` par user_id).
Aucun contournement d'isolation détecté.

**Bilan isolation : ✅ correcte.** Faiblesses ⚠️ toutes LOW.

---

## 3. CREDENTIALS GARMIN — cycle de vie exact du username/password

**Chemin d'arrivée :**
`POST /api/garmin/connect` body `{garmin_username, garmin_password}` (`GarminConnectRequest`, l.47-61)
→ `connect_garmin()` → `garmin_service.connect(db, user_id, garmin_username, garmin_password)`
→ `GccliProvider.connect(...)` → `GccliRunner.login(email, password)`.

**Transit / usage :**
- `runner.login()` (`runner.py` l.157-213) : `pty.fork()`, écrit le password dans le pseudo-TTY
  (`os.write(fd, (password + "\n"))`) quand gccli affiche « …assword ». Usage **one-shot**.
- Après login, gccli persiste un **token OAuth** (keyring `file`) dans `GCCLI_HOME/{user_id}/`.
  Les syncs suivants n'utilisent plus le password (token auto-refresh).

| Question | Réponse | Preuve |
|---|---|---|
| Conservé en mémoire | Seulement le temps de la requête login | passé en argument, non stocké sur un attribut persistant |
| Stocké en BDD | **Password : NON.** Username (email) : **OUI, en clair** | `service.connect` écrit `garmin_username` dans `garmin_connections` (l.47-48) ; le password n'est jamais écrit |
| Stocké dans `GCCLI_HOME` | Password : NON. gccli y stocke un **token OAuth** (pas le password) | `runner.py` docstring l.7-12 + `_env` HOME |
| gccli conserve le password en fichier | Non (gccli stocke un token, pas le mot de passe) | Modèle d'auth gccli (token keyring) |
| Apparaît dans les logs | **NON en fonctionnement normal** ; masqué | `GarminConnectRequest.__repr__` (l.59-60) n'expose pas le password ; aucun `logger` du password (grep négatif) |
| Peut apparaître dans les erreurs | ⚠️ **RISQUE** | `runner.login` échec → `GccliError("gccli login failed: {full_output[:300]}")` (l.213). `full_output` = sortie brute du PTY ; puis loggé `logger.error("[gccli] connect failed: %s", exc)` (`gccli_provider.py` l.72). Si le TTY **écho** le password (peu probable car prompt password), il pourrait finir dans les logs |
| Retourné au frontend | **NON** | `connect` renvoie seulement `{status, message, provider}` |
| Présent dans Redis/cache | **NON** | Redis ne stocke que les jobs de sync (`user_id`) + feed d'activités |
| Récupérable par un autre user | **NON** | Aucune lecture cross-user ; HOME isolé |

### Recommandation (A vs B vs C)
- **A. Password envoyé à chaque sync** → ❌ à proscrire (surface d'exposition répétée, stockage/transit multiples).
- **B. Credentials conservés côté backend (chiffrés)** → ⚠️ possible mais stockage de secrets réutilisables = risque élevé si fuite DB ; non nécessaire avec gccli.
- **C. Session/token GCCLI conservé côté backend après un login unique** → ✅ **RECOMMANDÉ**.
  C'est **déjà le modèle actuel** : login one-shot → token OAuth gccli persistant par user dans
  `GCCLI_HOME/{user_id}/`, auto-refresh, plus jamais de password. **Approche la plus sûre et la plus réaliste
  avec GCCLI.** Il suffit de sécuriser le cas d'erreur (cf. §7/§8) et de ne jamais logger la sortie brute.

---

## 4. GCCLI_HOME — structure exacte

- Base : `GCCLI_HOME` (env, défaut `/app/backend/.gccli_home`) — `factory._base_home()`.
- Par utilisateur : **`GCCLI_HOME/{user_id}/`** où `user_id` = UUID RunIndex issu du JWT.
  Défini par `factory.get_provider_for_user()` → `GccliRunner(home=user_home)` → `_env()` force `HOME`.
- Contenu par répertoire user : le **keyring/token OAuth gccli** de ce user (créé au login, rafraîchi
  automatiquement). **Aucun mot de passe.**
- `GccliRunner.__init__` fait `os.makedirs(self.home, exist_ok=True)` → création paresseuse du dossier user.
- ⚠️ Le compte **global legacy** (`GARMIN_USERNAME` dans `.env`, session `mallegolbrieg@gmail.com`) subsiste
  dans la **base** `GCCLI_HOME` (pas sous un `{user_id}`), utilisé uniquement par `get_provider()` (bootstrap).
  Aucun user RunIndex n'y est mappé. À retirer à terme (LOW).

---

## 5. IDENTITÉ GARMIN DISPONIBLE

**La seule identité actuellement disponible = l'email Garmin (`garmin_username`) fourni par le frontend**,
vérifié indirectement par un login gccli réussi, puis stocké en clair dans `garmin_connections.garmin_username`.

- **Garmin username/email** : ✅ disponible (saisi par l'utilisateur, stocké).
- **Garmin user ID numérique** : ❌ **NON exposé par gccli** dans ce code. `auth status` (`runner.auth_status`)
  ne renvoie que `{email, expired, expires_at}` ; `get_profile()` renvoie ce même `auth status`.
- **Identifiant renvoyé par GCCLI** : uniquement l'**email**.
- **Données de profil Garmin** : non récupérées comme identité.
- **Autre identité persistante** : aucune.

### Verdict identité
⚠️ **L'email N'EST PAS un identifiant Garmin persistant robuste**, et de surcroît il est **fourni par le
frontend** (contraire à la règle anti-abus). Problèmes :
1. **Fourni par le client** : `garmin_username` vient du body. L'identité anti-abus doit être **dérivée serveur**.
   Ici, on pourrait au minimum la re-dériver via `runner.auth_status()['email']` **après** login réussi
   (valeur confirmée par Garmin) plutôt que de faire confiance au body.
2. **Non normalisé** : variations de casse/espaces (`John@x` vs `john@x`) = identités différentes →
   contournement trivial du « 1 Garmin = 1 Trial ». `activate_garmin_trial` fait `.strip()` mais **pas** de
   `lower()`.
3. **Mutabilité** : un email de compte Garmin peut changer ; deux comptes distincts ne partagent pas d'email
   (donc pas de faux positif), mais un même compte peut théoriquement changer d'email (faux négatif rare).

➡️ **GCCLI ne fournit pas, en l'état, d'identité Garmin numérique persistante.** L'email, **s'il est
dérivé server-side du login gccli et normalisé (lowercase+trim)**, est un compromis **acceptable mais
imparfait** pour la phase < 1 000 users. À signaler clairement au produit : ce n'est pas aussi robuste
qu'un user ID Garmin.

---

## 6. TRIAL 30 JOURS / ANTI-ABUS — est-ce garanti backend ?

### ❌ NON. La règle n'est ni appliquée ni même déclenchée.

**Preuves :**
- `subscription_manager._GARMIN_IDENTITY_AVAILABLE = False` (l.62) → `activate_garmin_trial()` **lève
  `NotImplementedError`** (l.304-312).
- `activate_garmin_trial()` **n'est appelée nulle part** dans le code applicatif (grep : seulement docstrings
  + tests `skipif`). En particulier, `service.connect` (le flux de connexion Garmin) **ne l'appelle pas**.
- `auth/router.register` crée toujours une souscription **FREE** (`status:"free"`, `garmin_identity:None`).
- `garmin_connections` **ne stocke pas** `garmin_identity` ; `subscriptions.garmin_identity` reste `None`.
- `garmin_trial_registry` : collection **vide** (0 document), même si l'**index unique existe** bien
  (`server.py` l.6053-6055, vérifié en base : `garmin_identity_1 {unique:true}`).

**Ce qui EST prêt (infra dormante) :**
- Durée 30 j (`TRIAL_DURATION_DAYS`), calcul `trial_start`/`trial_end` serveur, transitions
  TRIAL→FREE (`check_trial_expiration`) et PREMIUM→FREE, claim atomique `find_one_and_update $setOnInsert`
  + index unique. Le squelette anti-race est correct — **mais débranché**.

### Scénario demandé (analyse conceptuelle)
> 1) User A crée un compte → 2) connecte Garmin X → 3) obtient un Trial → 4) déconnecte → 5) supprime son
> compte → 6) User B crée un compte → 7) connecte Garmin X. **User B a-t-il un nouveau Trial ?**

- **Aujourd'hui (PR#40 telle quelle)** : personne n'obtient de Trial (étape 3 impossible : funnel bloqué +
  trial débranché). Scénario **non applicable**.
- **Si on branchait naïvement l'email comme identité** (ce qu'il faudra faire) :
  - Étape 4 **déconnexion** : `service.disconnect` supprime `garmin_connections`/activités **mais NE touche
    PAS `garmin_trial_registry`** → ✅ bon (l'entrée anti-abus survit).
  - Étape 5 **suppression de compte** : **aucune route de suppression de compte n'existe** (grep négatif).
    Donc pas de purge du registry aujourd'hui → ✅ bon *par accident*. ⚠️ **Si** une route de delete-account
    est ajoutée plus tard, elle **NE doit PAS** supprimer l'entrée `garmin_trial_registry` (sinon faille).
  - Étape 7 : `activate_garmin_trial(B, garmin_X)` verrait l'entrée existante → **B reste FREE** ✅.
  - **MAIS faille casse (§5.2)** : si B saisit l'email avec une casse/espace différents, l'identité diffère →
    **B obtiendrait un 2ᵉ Trial**. → normalisation obligatoire.
- **Plusieurs comptes RunIndex, même Garmin, simultanés** : l'index unique + `$setOnInsert` garantissent
  qu'**un seul** gagne le Trial → ✅ (une fois branché).

**Conclusion §6 : « 1 Garmin = 1 Trial » n'est PAS garanti aujourd'hui (feature débranchée).**
L'infra atomique est prête ; il manque le câblage + une identité serveur normalisée.

---

## 7. VULNÉRABILITÉS / FAIBLESSES

### 🔴 CRITICAL
1. **Funnel commercial bloqué** — `/api/garmin/*` = PREMIUM (`access_control.py` l.507) ⇒ un user FREE est
   refusé (403) sur `/api/garmin/connect` par le middleware (`server.py` l.442-462). Impossible de connecter
   Garmin → impossible d'obtenir le Trial. **Le produit ne fonctionne pas pour les nouveaux comptes.**
2. **Trial anti-abus totalement débranché** — `_GARMIN_IDENTITY_AVAILABLE=False` + aucun appel à
   `activate_garmin_trial()`. « 1 Garmin = 1 Trial » **non appliqué**.

### 🟠 HIGH
3. **Identité anti-abus fournie par le frontend** — `garmin_username` (body) sert de future clé d'identité ;
   doit être **dérivée serveur** (`runner.auth_status()['email']` post-login) et **jamais** du body.
4. **Identité non normalisée** — pas de `lower()` → contournement du Trial par variation de casse/espaces.

### 🟡 MEDIUM
5. **Fuite possible du password dans les logs d'erreur** — `runner.login` met la sortie brute PTY
   (`full_output[:300]`) dans `GccliError`, ensuite `logger.error(... exc)`. Si le TTY écho le mot de passe,
   il peut apparaître dans les logs. À neutraliser (ne jamais inclure la sortie brute contenant le password).
6. **`garmin_username` (email) stocké en clair** dans `garmin_connections`. PII exploitable en cas de fuite DB.

### 🟢 LOW
7. **Méthodes dupliquées** dans `gccli_provider.py` : `sync_activities`, `fetch_all_activities`,
   `get_daily_metrics`, `get_profile`, `_normalize` sont **définies deux fois** (l.75-196 puis l.198-320,
   identiques). Python garde la 2ᵉ ; code mort / artefact de merge à nettoyer.
8. **Concurrence même-user** sur `GCCLI_HOME/{user_id}` (2 syncs //) → accès keyring concurrent (rare).
9. **Compte gccli global legacy** (`GARMIN_USERNAME`) + session dans la base `GCCLI_HOME` : résidu inutile
   en multi-user (utilisé seulement par bootstrap).
10. **141 activités legacy `user_id="default"`** orphelines en base (inaccessibles via JWT ; pas une fuite).
11. **`os.path.join(base, user_id)`** : sûr tant que `user_id` reste un UUID serveur (pas de traversal).

---

## 8. CORRECTIONS MINIMALES RECOMMANDÉES (avant production, sans refonte)

Objectif : rendre le funnel fonctionnel + l'anti-abus réel, en gardant GCCLI. **Strictement le nécessaire.**

1. **Débloquer le funnel (CRITICAL 1).** Reclasser les routes de **connexion** en accès FREE :
   au minimum `/api/garmin/connect`, `/api/garmin/status`, `/api/garmin/disconnect` doivent être
   accessibles à un user FREE (les routes de **données** — `sync`, `activities`, `daily-metrics`, `backfill`,
   `feed/stream` — peuvent rester PREMIUM, le Trial les débloque).
2. **Câbler le Trial (CRITICAL 2).** Dans `service.connect`, après `STATUS_CONNECTED` :
   - dériver l'identité **server-side** : `identity = runner.auth_status()['email']` (valeur confirmée par
     Garmin), **normalisée** `identity.strip().lower()` (corrige HIGH 3 & 4) ;
   - passer `_GARMIN_IDENTITY_AVAILABLE = True` ;
   - appeler `activate_garmin_trial(db, user_id, identity)` ;
   - stocker `garmin_identity` dans `garmin_connections` (utile au support).
3. **Ne jamais logger la sortie brute du login (MEDIUM 5).** Remplacer le message d'erreur par un texte
   générique (« gccli login failed ») sans `full_output`, ou expurger le password avant log.
4. **Garantir la persistance de l'anti-abus.** Confirmer (et documenter) que `disconnect` ne purge pas
   `garmin_trial_registry` (déjà OK) et que toute future route de suppression de compte **ne la purge pas**.
5. **Nettoyer les méthodes dupliquées (LOW 7)** de `gccli_provider.py` (hygiène, évite les divergences).

> Optionnel/à confirmer produit : chiffrer/hasher `garmin_username` stocké (MEDIUM 6) ; retirer le compte
> gccli global legacy (LOW 9). Non bloquant pour la mise en production.

---

## 9. VERDICT PRODUCTION

**« Peut-on mettre RunIndex en production avec PR#40 telle quelle ? »**

### ❌ NON.

Raisons bloquantes :
- Un **nouveau compte (FREE) ne peut pas connecter Garmin** (routes Garmin gated PREMIUM) → funnel mort.
- **Aucun Trial n'est jamais accordé** (feature débranchée) → le modèle « FREE → Trial 30 j → Premium »
  ne fonctionne pas.
- La règle **« 1 Garmin = 1 Trial » n'est pas appliquée**.

L'**isolation multi-user GCCLI**, elle, est **prête** (aux points LOW près) et **peut** aller en production.

### Corrections minimales EXACTES avant production
1. Reclasser `/api/garmin/connect|status|disconnect` en **FREE** (garder les routes de données en PREMIUM).
2. Dans `service.connect` : dériver l'identité **server-side** via `auth_status().email`, **normaliser**
   (`strip().lower()`), passer `_GARMIN_IDENTITY_AVAILABLE=True`, appeler `activate_garmin_trial(...)`,
   persister `garmin_identity`.
3. Supprimer la sortie brute du login des messages d'erreur/logs.
4. Vérifier/garantir que `garmin_trial_registry` n'est jamais purgé (disconnect + future suppression compte).
5. Nettoyer les méthodes dupliquées de `gccli_provider.py`.

Après ces 5 correctifs (aucune refonte), le modèle commercial et l'anti-abus seront fonctionnels avec GCCLI.

---

### Annexe — Preuves factuelles collectées
- `garmin_connections` : 1 doc legacy `user_id="default"`, `activity_count=141`.
- `garmin_activities` : 141 docs, `distinct user_id = ["default"]`.
- `garmin_trial_registry` : 0 doc ; index `garmin_identity_1 {unique:true, sparse:false}` présent.
- `subscriptions` : 31 docs (mix legacy IP-based free/trial) ; nouveaux comptes JWT = `free`.
- `_GARMIN_IDENTITY_AVAILABLE = False` ; `activate_garmin_trial` jamais appelée (hors tests skippés).
- `ROUTE_ACCESS_MAP["/api/garmin/"] = PREMIUM` (l.507) ; middleware bloque FREE (l.442-462).
- Aucune route de suppression de compte RunIndex.
