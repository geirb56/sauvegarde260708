# RUNINDEX — POST #308 MOBILE POLISH — PR #309

## Références

- PR existante : [#309](https://github.com/geirb56/sauvegarde260708/pull/309).
- Base exacte : `copilot/dev` @ `5e256b0b1978f7b4bb81cd2a3b61b10db5438539`.
- HEAD initial de #309 : `fd23d957c0002d2c377ae43461d23dce65e8db06`.
- HEAD final du patch frontend, testé et construit :
  `d3c8113c1c67ac1893e593df4208752473250c6e`.
- Branche de livraison : `copilot/runindex-pr-15a-1-micro-polish-mobile-post-308`.
- Le commit de livraison ajoute uniquement ce rapport au HEAD frontend ci-dessus.
  Son SHA exact est celui du commit contenant ce rapport, obtenu par
  `git log -1 --format=%H -- docs/reports/POST_308_MOBILE_POLISH.md`.
  Le HEAD final de livraison est également consigné dans le commentaire de livraison
  de #309 ; il n'est pas confondu avec le HEAD frontend testé. Un document ne peut
  incorporer littéralement le SHA de son propre commit sans changer ce SHA.
- État observé avant correction : OPEN, DRAFT, NON MERGÉE.
  Aucune nouvelle PR ni opération de merge.

## Fichiers modifiés

Micro-patch de correction C309, par rapport au HEAD initial :

1. `frontend/src/pages/WorkoutDetail.jsx`
2. `frontend/src/__tests__/workout-analysis-v2-pages.test.jsx`
3. `docs/reports/POST_308_MOBILE_POLISH.md`

La PR complète contient également les changements initiaux déjà validés dans
`frontend/src/components/Layout.jsx`, `frontend/src/lib/i18n.js` et
`frontend/src/__tests__/layout-mobile-nav.test.jsx`.
Ces trois fichiers ne sont **pas remodifiés** par cette correction.

## Cause et stratégie bottom-nav

La grille mobile possède cinq colonnes. Les libellés longs, notamment
« Entraînement » et « Progression », étaient rendus avec
`whitespace-normal break-words` : la largeur limitée autorisait un retour
à la ligne, y compris au milieu d'un mot.

La correction initiale distingue les libellés mobiles courts des noms complets.
Les noms longs restent dans `aria-label` et `title`, ainsi que dans les traductions
utilisées par les autres surfaces.

| Langue | Libellés mobiles, dans l'ordre |
| --- | --- |
| FR | Accueil · Plan · Séances · Coach · Progrès |
| EN | Home · Plan · Sessions · Coach · Progress |
| ES | Inicio · Plan · Sesiones · Coach · Progreso |

Confirmation structurale : cinq entrées, taille **>= 11 px** conservée,
`whitespace-nowrap`, suppression de `break-words`, aucune règle de coupure
intra-mot, aucune troncature ni masquage arbitraire. Les icônes et la logique
d'état actif n'ont pas été modifiées. Cette confirmation de code n'est pas
une mesure de rendu sur téléphone.

## Règles de formatage

- Comptages : singulier/pluriel naturel FR/EN/ES, sans notation « séance(s) ».
- FC : bpm entier ; écarts arrondis à l'entier.
- Durée : minute entière avant conversion en heures ; écarts en minutes entières.
- Distance : **maximum deux décimales**, sans zéros finaux inutiles, point décimal
  conforme au contrat demandé. `Intl.NumberFormat("en-US")`, sans groupement.
- `formatDistance(value)` renvoie la distance avec `km`, ou `--` pour une valeur
  absente/non finie. Le zéro négatif arrondi est normalisé en `0 km`.
- `formatSignedDistance(metric)` conserve le signe des deltas non nuls et
  n'ajoute aucun signe à un zéro arrondi : `-0.001` devient `0 km`.
- Exemples : `9.6800000004` → `9.68 km`, `2.555` → `2.56 km`,
  delta `2.5500000003` → `+2.55 km`, delta `-1.39` → `-1.39 km`.
- Application aux quatre interpolations de distance identifiées : distance de
  séance et delta dans la carte volume, delta dans la comparaison récente,
  distance moyenne dans les sorties similaires. Une moyenne absente dans une
  référence disponible est affichée comme `--`, jamais comme zéro.
- Allure **m:ss/km inchangée** ; vitesse, durée et FC non remodifiées par ce patch.
- Aucune mutation des valeurs sources, aucun recalcul scientifique.

## Périmètre protégé

- Palette/tokens #308 : **NON MODIFIÉS**, notamment `index.css` et `theme-modern.css`.
- Backend : **NON MODIFIÉ**.
- Coach voice : **NON MODIFIÉE** ; textes scientifiques/Coach opaques inchangés.
- Training V2 / Workout Analysis V2 : **NON MODIFIÉS** dans leurs calculs, contrats,
  routes et autorités. Seule la présentation des distances dans WorkoutDetail change.
- Garmin, subscription, auth et dépendances : **NON MODIFIÉS**.

## QA 320 / 360 / 390

**QA structurale/tests uniquement — validation visuelle physique restante**.

Aucune QA navigateur ni sur téléphone physique n'a été exécutée pendant cette
correction. Jest/jsdom vérifie le DOM et les classes, pas la géométrie CSS réelle.

| Largeur attendue | FR | EN | ES |
| --- | --- | --- | --- |
| 320 px | Validation visuelle restante | Validation visuelle restante | Validation visuelle restante |
| 360 px | Validation visuelle restante | Validation visuelle restante | Validation visuelle restante |
| 390 px | Validation visuelle restante | Validation visuelle restante | Validation visuelle restante |

Pour chaque couple largeur/langue, restent à confirmer en navigateur/téléphone :
cinq items visibles, une seule ligne par label, aucun overflow horizontal,
aucune coupure intra-mot, icônes intactes et état actif intact.
Les labels attendus sont ceux du tableau FR/EN/ES ci-dessus.

Les tests nav existants confirment les cinq liens, la grille cinq colonnes,
les traductions courtes, les noms complets accessibles, les classes 11 px et
`whitespace-nowrap`, et l'absence de classes de coupure/troncature.
Cela ne démontre pas l'absence d'overflow à ces trois largeurs.

## Validation exécutée pendant cette correction

Depuis `frontend/`, après `npm ci --legacy-peer-deps --no-audit --no-fund` :

- `CI=true npx craco test src/__tests__/layout-mobile-nav.test.jsx src/__tests__/workout-analysis-v2-pages.test.jsx --watchAll=false --forceExit --runInBand`
  : **2 suites réussies, 85 tests réussis, 0 échec**.
- Les nouveaux tests couvrent distances absolues/deltas, décimales parasites,
  arrondi `2.555`, suppression des zéros finaux, zéro signé, valeurs absentes,
  NaN et ±Infinity, absence de mutation et rendu réel des cartes
  récente/similaire/volume. Le DOM testé ne contient aucune distance
  numérique avec plus de deux décimales.
- `npm run build` : **compilation réussie**. Avertissement Browserslist :
  données `caniuse-lite` anciennes ; aucune mise à jour de dépendance effectuée.
- `git diff --check` : **réussi** pour le patch frontend ; vérification répétée
  à la livraison pour inclure ce rapport.
- Suite frontend complète : **non réexécutée pendant cette correction**.
  Résultat historique au HEAD initial, et non résultat du nouveau HEAD :
  **33/34 suites réussies, 560/561 tests réussis** ; l'échec
  `progress-v2-migration` (« predictions list rendering preserved ») avait été
  reproduit sur la base exacte. Il est préexistant et n'est ni corrigé ni
  présenté comme un succès. `Progress.jsx` et son test restent inchangés.

Les résultats de revue/scan et le SHA final de livraison sont consignés dans
le commentaire de livraison de #309 après les validations.

## Conclusion

Les deux P2 sont traités par le formatage des distances et la présence de ce
rapport. Le périmètre reste frontend/présentation. La QA physique restante
est explicitement documentée ; aucun PASS visuel 320/360/390 n'est revendiqué.
**NE PAS MERGER.**
