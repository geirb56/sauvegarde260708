# RUNINDEX — Netlify SPA redirections

## Audit initial

- Branche de travail : `copilot/runindex-fix-react-routes`.
- Base demandée : `copilot/dev` (`7dd262de4aa4d3355cf0659a5a3d4ad092e42d5f` au début de la tâche).
- Le frontend est une application React utilisant `BrowserRouter` de `react-router-dom`; les routes incluent notamment `/login`, `/sessions/:id`, `/workout/:id` et `/training`.
- Aucun `netlify.toml`, `_redirects`, proxy `/api/*` ou dossier de fonctions Netlify n'existait dans le dépôt.
- Les appels API du frontend sont construits depuis `REACT_APP_BACKEND_URL` et suffixés par `/api`; aucun proxy Netlify vers Railway n'était présent.
- Le frontend est dans `frontend/`, utilise `npm run build` (`craco build`) et produit le répertoire CRA `frontend/build`. Les ressources statiques sont dans `frontend/public/`.

## Correction retenue

Ajout de `/netlify.toml` à la racine : le build utilise `frontend/`, publie son répertoire `build` et réécrit les routes non résolues vers `/index.html` en HTTP 200. La règle n'est pas forcée, afin de laisser les fichiers publiés existants être servis. Aucun proxy, fonction, endpoint API, variable d'environnement ou code applicatif n'est ajouté ni modifié. Les appels Railway restent déterminés par `REACT_APP_BACKEND_URL`; aucune valeur secrète backend n'est introduite dans le bundle.

## Fichiers modifiés

- `netlify.toml` — base, commande, dossier de publication et fallback SPA.
- `RUNINDEX_NETLIFY_SPA_REDIRECTS_REPORT.md` — ce rapport d'audit et de validation.

## Validation

- `npm ci --legacy-peer-deps` (depuis `frontend/`) : réussi.
- `npm run build` (depuis `frontend/`) : réussi; le build CRA produit `frontend/build`.
- Vérification TOML et sorties : réussie; `netlify.toml` se parse, cible `frontend/build`, et le bundle contient `index.html` ainsi que les ressources statiques.
- `npx craco test --watchAll=false --forceExit` : 33 suites réussies, 1 échouée; 837 tests réussis, 1 échoué. L'échec préexistant et hors périmètre est `src/__tests__/progress-v2-migration.test.jsx`, qui attend le texte `predictions.predictions?.map` absent de `src/pages/Progress.jsx`.
- Analyse de secrets des deux fichiers modifiés : aucun secret détecté.
- Vérification en hébergement Netlify ou test de rafraîchissement sur une URL déployée : non effectuée; aucun déploiement n'est autorisé dans cette tâche.
- Base exacte : `7dd262de4aa4d3355cf0659a5a3d4ad092e42d5f`.
- Head exact du code validé : `dd63dba91cda29a224247d003552900d1e5668de`.

## Risques et points bloquants

- Le test local ne peut pas prouver le comportement du CDN Netlify lors d'un accès direct ou d'un rafraîchissement; la validation réelle est réservée à une autorisation ultérieure de déploiement.
- Le site doit continuer à fournir `REACT_APP_BACKEND_URL` pour cibler Railway en production. Aucune configuration manuelle Netlify/Railway n'a été faite.
- Aucun changement au backend, Garmin, Redis, au moteur physiologique ou au drift local `activity_day`.

## Livraison

- PR à préparer contre `copilot/dev`; son lien sera fourni lors de la livraison.
- Aucun merge ni déploiement effectué.
