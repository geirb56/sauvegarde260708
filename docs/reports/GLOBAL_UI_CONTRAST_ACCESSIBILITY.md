# RunIndex — contraste global et lisibilité mobile

## Périmètre et références Git

- Objectif unique : **CONTRASTE + LISIBILITÉ**, pas une certification complète WCAG.
- Base : `copilot/dev`.
- HEAD initial réellement vérifié : `4214c3e0b258a49b6d18436cce81ee39158d24f9`.
- HEAD frontend vérifié : `ce905ebdf12066d04428ebb3b7f2f361567fb64e`.
- HEAD final de livraison : celui de la branche `copilot/runindex-pr-15a`, publié
  avec son SHA exact dans la description de PR et le message de livraison.
  Le SHA du commit contenant ce rapport ne peut pas être encodé dans ce même
  commit ; le HEAD frontend ci-dessus identifie les sources effectivement testées.
- Une seule PR demandée ; numéro attribué par GitHub à sa création. **NON MERGÉE**.

Frontend uniquement : aucun changement de backend, contrat API, prescription,
calcul, ingestion Garmin, abonnement, auth, prompt ou règle Coach. Les réponses
LLM, comparaisons et données restent inchangées, y compris les valeurs manquantes.

## Inventaire avant modification

Inventaire sur le HEAD initial, dans `frontend/src` (`.js`, `.jsx`, `.css`, hors
`__tests__`). Ce sont des occurrences source, pas un nombre de défauts WCAG :

| Motif | Occurrences | Fichiers |
| --- | ---: | ---: |
| `text-muted-foreground` (variantes incluses) | 370 | 49 |
| `text-secondary-*` | 2 | 2 |
| `text-gray-*` | 0 | 0 |
| `text-slate-*` | 6 | 2 |
| `opacity-*` | 48 | 24 |
| `text-[8px]` | 6 | 4 |
| `text-[9px]` | 26 | 8 |
| `text-[10px]` | 83 | 13 |
| `font-mono` | 186 | 17 |
| `placeholder` | 43 | 16 |

`index.js` importe à la fois `index.css` et `theme-modern.css`. Tailwind/shadcn
consomme les triplets HSL de `index.css` ; les classes modernes et styles inline
consomment les variables legacy de `theme-modern.css`.

### Classification et décisions

| Classe d'usage | Exemples | Décision |
| --- | --- | --- |
| Primaire | valeurs principales, contenu des messages, titres | `foreground` / `text-primary`, blanc cassé |
| Secondaire | explications, interprétation, descriptions | `secondary-foreground` / `text-secondary`, sans-serif |
| Atténué utile | dates, aides, références, navigation inactive, placeholder | `muted-foreground` / `text-tertiary`, opaque et AA |
| Métadonnée technique | km, allure, bpm, version, labels courts, graduations | Mono conservé ; labels utiles et ticks ciblés à 11 px |
| Disabled / indisponible | contrôles partagés, séance grisée, valeur absente | état conservé par fond/couleur/cursor, pas par disparition du texte |
| Décoratif | skeletons, texture, lignes/graphiques, animations d'entrée | transparence conservée ; pas de remplacement mécanique |
| Sémantique | rouge erreur, orange warning, violet Premium, vert succès | accents conservés, foregrounds lisibles distincts |

Contournements corrigés : petit texte dans les pages d'analyse, Coach, Dashboard,
Progress et badges Training/Subscription ; slate du paywall ; valeurs absentes
à 35 % blanc ; opacité sur une card contenant du texte ; blanc sur bouton vert ;
texte blanc sur barres colorées ; monospace sur paragraphes continus.

Les bordures Dashboard utilisaient `var(--border, #2a2a30)` comme couleur CSS :
`--border` est un triplet HSL, pas une couleur complète. Elles utilisent désormais
`--border-color`, et leurs surfaces utilisent `--bg-card`.

Les descriptions de dialogues, toasts Sonner et tooltips partagés suivent déjà
les tokens : correction globale plutôt que nouveaux overrides. Les contrôles
Input, Textarea, Select, Button et Label ne réduisent plus l'opacité du texte
désactivé. Le placeholder natif Input/Textarea est explicitement opaque.

`GoalSection`, `ChatCoach`, `RecoveryGauge` et plusieurs primitives UI non
montées par les routes actuelles gardent des styles legacy : pas de réécriture
massive de composants hors parcours. La seule classe slate d'Admin est le texte
clair d'un badge FREE, pas un gris sombre à remplacer arbitrairement.

## Palette et source de vérité

| Token | Avant `index.css` | Avant `theme-modern.css` | Après, valeur indicative |
| --- | --- | --- | --- |
| Background | `222 47% 5%` | `#0a0e1a` | `#0a0e1a` |
| Card / popover | `222 35% 10%` | `#141a2e` | `#141a2e` |
| Primary text | `0 0% 100%` | `#ffffff` | `#f2f5f9` |
| Secondary text | `215 20% 65%` | `#94a3b8` | `#aab4c3` |
| Muted / tertiary text | `215 16% 47%` | `#64748b` | `#8793a5` |
| Border | `222 20% 18%` | `#1e293b` | `#334155` |
| Strong border | pas de token partagé | `#334155` | `#475569` |

`index.css` est la source canonique HSL. `card-foreground`, `popover-foreground`
et `accent-foreground` aliasent `foreground`. Dans `theme-modern.css` :

- `--text-primary` → `hsl(var(--foreground))`
- `--text-secondary` → `hsl(var(--secondary-foreground))`
- `--text-tertiary` → `hsl(var(--muted-foreground))`
- `--bg-primary` / `--bg-card` → `background` / `card`
- `--border-color` / `--border-color-light` → `border` / `border-strong`

Le vert RunIndex reste un accent, pas le texte secondaire générique. Le rouge
destructive est éclairci pour les erreurs sur fond sombre, avec texte sombre
sur boutons/badges destructive. Le status danger moderne partage ce token.
Le bleu informatif est éclairci ; le violet Premium et l'orange restent présents.
Le foreground warning est `#fb923c` : le badge « Faible » de Progress conserve
son fond orange alpha mais n'utilise plus l'orange décoratif trop sombre comme
couleur du texte sur une card objectif.
Le paywall conserve son gradient violet/rose avec un texte sombre lisible,
et un fond muted lorsqu'il est désactivé.
Le badge TRIAL Settings conserve son bleu `blue-500`, avec texte background
sombre plutôt que blanc : cette paire est protégée par le test de contraste
et l'assertion de classes du test Settings.

### Ratios déterministes

Formule WCAG de luminance relative sRGB, ratios arrondis. « Avant » correspond
à la palette moderne sur ses surfaces réelles :

| Texte | Avant / background | Avant / card | Après / background | Après / card |
| --- | ---: | ---: | ---: | ---: |
| Principal | 19.26 | 17.26 | 17.61 | 15.78 |
| Secondaire | 7.51 | 6.73 | 9.19 | 8.24 |
| Atténué | **4.05** | **3.63** | **6.19** | **5.54** |

Le test lit les déclarations CSS réelles, résout les aliases et vérifie les trois
niveaux de texte sur background, card, popover, muted, secondary, accent,
bg-secondary et bg-card-hover, avec seuil **4.5:1**. Il vérifie aussi la hiérarchie,
les aliases, plusieurs paires sémantiques, les tailles de navigation et l'absence
de fading disabled dans les cinq contrôles partagés.

Ce test ne prouve pas le contraste de chaque état dynamique, graphique,
gradient, image ou combinaison arbitraire de transparences de l'application.

## Typographie et mobile

- Labels courts utiles ciblés : 11 px au minimum, sans règle globale « tout à 12 ».
- Paragraphes explicatifs : Manrope / `font-sans`, 14 px, interligne lisible.
- JetBrains Mono conservé pour données courtes, allures, distances, bpm, labels
  techniques et ticks ; pas pour les explications continues.
- WorkoutDetail : résumé, indisponibilité d'intensité, comparaison similaire,
  interprétation, notes, preuves et limites en sans-serif. Ordre, données,
  calculs et CTA Coach inchangés.
- DetailedAnalysis : résumé, interprétation, conseil et raisons d'indisponibilité
  en sans-serif ; métadonnées techniques courtes toujours Mono.
- Coach : contenu des messages et saisie sans-serif ; suggestions et aide
  lisibles ; aucun changement de conversation, prompt ou réponse.
- Dashboard, Settings et Subscription : explications longues et helpers encore
  à 12 px constatés en QA portés à 14 px ; labels et métadonnées courts conservés.
- Navigation : cinq entrées conservées, label 11 px même sous 380 px, actif
  vert. Les longs labels français peuvent se replier dans leur cellule ;
  la réserve basse du main couvre cette hauteur et la safe area.
- Deux débordements locaux constatés à 320 px corrigés sans changer la structure :
  type de séance Training et bouton de sauvegarde des paramètres de course.

## Validation exécutée

Installation des dépendances existantes : `npm ci --legacy-peer-deps --no-audit
--no-fund`. Aucune nouvelle dépendance.

Depuis `frontend/`, suites directement demandées :

```text
CI=true npm test -- --watchAll=false --runInBand --forceExit --runTestsByPath \
src/__tests__/global-ui-contrast.test.js \
src/__tests__/layout-mobile-nav.test.jsx \
src/__tests__/workout-analysis-v2-pages.test.jsx \
src/__tests__/coach-page.test.jsx \
src/__tests__/settings-page.test.jsx \
src/__tests__/training-v2-page.test.jsx \
src/__tests__/sessions-page.test.jsx \
src/__tests__/progress-mobile-ux.test.jsx \
src/__tests__/subscription-page-copy.test.jsx
```

Résultat final : **9 suites, 232 tests passés**.

Contrôle intermédiaire supplémentaire directement lié aux couleurs readiness :
`dashboard-run-readiness-v2.test.jsx` + `global-ui-contrast.test.js` :
**2 suites, 76 tests passés**. Les assertions readiness vérifient toujours
les états et les surfaces grises/rouges, plutôt que l'ancien texte sombre.
Après la dernière correction warning : `global-ui-contrast.test.js`,
`progress-mobile-ux.test.jsx`, `progress-potential-ui.test.jsx` et
`dashboard-run-readiness-v2.test.jsx` : **4 suites, 91 tests passés**.
Après correction du badge TRIAL : `settings-page.test.jsx` +
`global-ui-contrast.test.js` : **2 suites, 96 tests passés**.

Suite frontend complète exécutée :
`CI=true npm test -- --watchAll=false --runInBand --forceExit`.
Résultat au HEAD frontend vérifié : **33 suites passées, 1 échouée ;
545 tests passés, 1 échoué, 546 tests au total**.

Échec préexistant conservé :
`progress-v2-migration.test.jsx`, « predictions list rendering preserved »,
attend littéralement `predictions.predictions?.map`. Le HEAD initial et le HEAD
testé contiennent tous deux `predictions.predictions.map` dans le même code
protégé. Aucun changement de logique ni correction hors objectif n'a été fait
pour satisfaire cette assertion source historique.

- `npm run build` : **Compiled successfully**.
- `git diff --check` : **passé**.
- Scans de secrets : aucun secret détecté avant les commits.
- `parallel_validation` appelé : CodeQL ignoré pour changements de présentation
  triviaux ; reviewer automatique indisponible (modèle absent du registre).
  Ce statut ne doit pas être présenté comme une revue automatique réellement
  réussie.
- Revue indépendante read-only du diff frontend : aucun problème significatif
  trouvé ; aucun changement réalisé par cet agent.

## QA mobile

La QA utilise Chromium installé, les routes React réelles et des réponses API
mockées à partir des fixtures Jest existantes. Ce ne sont pas des données
Garmin réelles. Les valeurs manquantes restent nulles ; pas de faux sommeil,
HRV ou TSS ajoutés au produit.

Premier passage à **320, 360 et 390 px** sur Dashboard, Training, Sessions,
WorkoutDetail, Coach, Progress, Settings et Subscription :

- largeur document = largeur viewport sur les 24 combinaisons ;
- détection de labels navigation débordant de leur cellule à 320/360 px ;
- détection des deux textes locaux tronqués à 320 px, corrigés ci-dessus ;
- paragraphes WorkoutDetail vérifiés dans le disclosure ouvert ;
- captures WorkoutDetail/Coach obtenues aux trois largeurs.

Le transport de l'outil Playwright était fermé. Les mesures ont été réalisées
par le protocole standard Chrome DevTools, sans nouvelle dépendance.
Les captures ne constituent **pas une inspection visuelle humaine**.

Deuxième passage : **36 états/page/largeur stabilisés**, sur les sept pages
demandées et Subscription, Login, Register, Onboarding ; Coach testé vide et
avec historique. Attente des réponses API et stabilité du DOM, sans exception
runtime non interceptée. Ce passage a traversé les commits de présentation ;
il ne constitue pas une capture atomique de tous les états sur un seul HEAD.

| Largeur | Overflow document | Texte coupé constaté | Échecs de contraste sur fonds solides mesurés | Hauteur nav |
| --- | --- | --- | --- | --- |
| 320 px | aucun | aucun | aucun | 78.56 px |
| 360 px | aucun | aucun | aucun | 78.56 px |
| 390 px | aucun | aucun | aucun | 81.80 px |

- Labels navigation : 11 px, contenus dans les liens ; main réservé à 84 px,
  compatible avec ces hauteurs (safe area native non simulée).
- Aucun texte utile visible sous 11 px dans les états contrôlés.
- Placeholders : opacité 1, contraste mesuré 5.48–5.54:1.
- Coach désactivé / « Plan actuel » : opacité 1, contraste mesuré 5.48:1,
  fond muted distinct ; Input auth 16 px, textarea Coach 14 px.
- FREE : paywalls Training/Progress stables, previews Dashboard restreints.
  Trial : accès Training/Progress avec `has_premium_access:true`, même si
  `plan:"free"`. Premium : parcours ouverts. Aucun contrat d'accès modifié.
- Login/Register publics ; Onboarding sans token redirige vers Login.
- Quelques dépassements de conteneurs locaux, sans coupure constatée, restent :
  stats de séance de 3 px à 320 px, label statistique Progress de 7 px,
  labels Subscription dépassant leur petit sous-conteneur mais pas leur parent.
  Le document ne déborde pas et aucun nouvel override de layout n'est ajouté
  pour des dépassements qui ne cachent pas les textes.
- 13 éléments Dashboard sur gradients sont distingués des mesures sur fonds
  solides ; le résultat « aucun échec » ne doit pas leur être étendu.
- Polices distantes indisponibles dans le navigateur QA : mesures réalisées
  avec les fallbacks. Les familles Manrope/Barlow/JetBrains restent définies
  dans le produit, mais leur rendu chargé doit être vérifié sur environnement
  réseau autorisé.

Recontrôles ciblés finaux au HEAD frontend
`c20d9750f9c476030828ced5b84a37cb22853520`, après les corrections :

| Largeur | Valeur readiness grise | Valeur readiness rouge | Badge « Faible » |
| --- | ---: | ---: | ---: |
| 320 px | 5.39:1 | 6.15:1 | 5.43:1 |
| 360 px | 5.38:1 | 6.15:1 | 5.43:1 |
| 390 px | 5.44:1 | 6.21:1 | 5.43:1 |

Les fonds réels composités ont été mesurés en pixels, sans inspection humaine
des captures. Les deux défauts additionnels trouvés sur fixtures readiness et
objectif (respectivement ~3.5:1 et 4.24:1) sont corrigés ; l'opacité utile est 1.
Le test déterministe inclut désormais le fond composité `#4d3028` du badge
objectif pour empêcher une régression du warning.

Autres recontrôles :

- Navigation française : contraste 5.89:1 inactive / 10.27:1 active, aucun
  label coupé aux trois largeurs.
- Graduations Progress sur fixture historique : 11 px, contraste 5.54:1.
- Paragraphes modifiés Dashboard/Settings/Subscription : 14 px, interligne
  22.75 px pour les explications relaxed.
- Dernières explications Garmin/TRIAL et FAQ Subscription corrigées ;
  trois recontrôles navigateur du contenu visible : 14 px, aucun overflow
  document ni texte coupé.
- Hint iOS déclenché par UA Safari/iPhone : paragraphe 14 px sans-serif,
  contraste 5.58:1. À 390 px, son bord bas empiète de 1.80 px sur le bord
  haut de la navigation, sans occlusion de texte ; pas de changement de layout
  supplémentaire pour ce chevauchement décoratif.

## Fichiers modifiés

Préfixe frontend : `frontend/src/`.

- `index.css`, `styles/theme-modern.css`, `App.css`
- `components/Layout.jsx`
- `components/ui/{input,textarea,select,label,button}.jsx`
- `components/{CoachMessage,MetricCard,Paywall,RAGSummary,WorkoutCard,IOSPWAHint}.jsx`
- `pages/{Coach,Dashboard,DetailedAnalysis,Progress,Settings,Subscription,TrainingPlanV2,WorkoutDetail}.jsx`
- `__tests__/global-ui-contrast.test.js`
- `__tests__/dashboard-run-readiness-v2.test.jsx`
- `__tests__/settings-page.test.jsx`
- `docs/reports/GLOBAL_UI_CONTRAST_ACCESSIBILITY.md`

Sessions, SessionDetail, Login, Register et Onboarding bénéficient des tokens
et contrôles partagés sans overrides page-par-page.

## Limites

- Une assertion source préexistante empêche de qualifier la suite complète de verte.
- Pas de backend réel ni de revue des réponses LLM ; fixtures de présentation uniquement.
- Pas de certification WCAG complète (clavier, lecteur d'écran, zoom, daltonisme,
  graphiques complexes et contrastes de tous les états possibles restent distincts).
- Les composants legacy non montés et les primitives UI inutilisées ne font pas
  l'objet d'une migration exhaustive.
- Le frontend conserve les troncatures intentionnelles existantes des noms longs
  de séances ; elles ne sont pas transformées en nouvelle architecture de layout.
- L'absence d'inspection humaine des captures doit rester explicite.
- Les mesures sur fonds solides ne certifient pas chaque gradient ni chaque
  état de données ; la PR ne doit pas être annoncée comme une certification AA
  exhaustive de l'application ou comme validée humainement pour Cxxx.
