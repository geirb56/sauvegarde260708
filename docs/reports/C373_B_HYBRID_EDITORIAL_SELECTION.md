# C373-B — Hiérarchisation éditoriale du Coach hybride

## 1. Base et périmètre

- Dépôt : `geirb56/sauvegarde260708` ; cible unique : `copilot/dev`.
- Base de travail vérifiée : `7c3bb1d1c1eb943bb65bed350608ad33a59fb76f`,
  HEAD après fusion de C373-A (#369) dans `copilot/dev`.
- Les PR #367 (C371), #368 (C372) et #369 (C373-A) existent et sont fusionnées.
- C373-B sélectionne et compose les faits C359–C373-A déjà admissibles.
  Les calculs, admissions, modèles scientifiques, langues sources et routes ne
  changent pas. Aucune connexion du Coach à l’application n’est ajoutée.

## 2. Diagnostic éditorial initial

### Faits, catégories et priorités existants

Le catalogue fermé contient les faits suivants. Les priorités sont des
métadonnées de catalogue, non un score utilisé par les règles C373-B.

| Fait(s) | Catégorie | Priorité | Portée |
| --- | --- | ---: | --- |
| `interval.pace_direction` | conclusion | 120 | Direction V2 explicite, efforts comparables uniquement |
| `interval.regularity` | conclusion | 110 | Bande V2 descriptive, allures uniquement |
| `effort.first`, `effort.last` | observation | 110 / 105 | Mesures Garmin individuelles, ordre enregistré |
| `interval.count` | observation | 100 | Phases enregistrées, sans durée ni verdict de régularité |
| `session.long` | comparaison | 95 | Durée comparée à la durée habituelle V3 |
| `trend.*` | conclusion | 90 | Tendance V3 corroborée par l’historique autorisé |
| `prescription.review` | conclusion | 85 | Concordance/écart de type, pas conformité complète |
| `comparison.pace`, `comparison.hr` | comparaison | 80 | Comparaison historique V3 admissible |
| `effort.coverage` | observation | 75 | Couverture des métriques d’effort admises |
| `intensity.position` | observation | 70 | FC moyenne par rapport à des seuils personnels fiables |
| `intensity.hr` | observation | 60 | FC moyenne descriptive, sans zone physiologique |
| `session.unknown` | observation | 55 | Type non établi ; aucune requalification en footing facile |
| `session.kind` | classification | 45 | Type probable, avec limites de confiance |

Les faits d’historique et de prescription sont filtrés avant transmission selon
les permissions strictes. Les mesures individuelles sont admises par identité,
provenance et unité ; une couverture partielle ne devient pas une conclusion de
régularité. Régularité et direction proviennent exclusivement des jugements V2
validés, sans recalcul. Les faits indiquent leurs preuves, conditions et limites.

### Sélection et réalisation avant C373-B

- Le fallback choisissait toujours `interval.pace_direction` avant toute autre
  nature de fait, puis pouvait ajouter prescription/FC. En l’absence de direction,
  il choisissait la régularité, puis pouvait ajouter une borne d’effort.
- Hors intervalles, un fait `effort.first`/`effort.last` passait avant
  l’historique ; il pouvait être suivi d’une comparaison ou tendance et d’une
  observation de FC.
- Le validateur imposait lui aussi la direction en première affirmation dès
  qu’elle était admise. Les autres règles interdisaient plusieurs doubles
  comptes, mais ne traitaient pas `session.long` comme une comparaison historique
  redondante.
- `direct` et `explain` sont les formes communes ; seuils, portée, arrondi
  explicite et nombres de comptage ont des formes conditionnelles. La réalisation
  backend fournit toutes les valeurs en FR/EN/ES.
- Le fournisseur ne reçoit qu’un catalogue borné et choisit des identifiants,
  formes, ordre et intention. Le backend valide ce choix puis réalise le texte ;
  aucune prose fournisseur n’est affichée. Le fallback reste déterministe.
- Le Coach s’abstient si l’accès est refusé, si le flag est OFF ou si aucun fait
  n’est admissible. Des données partielles n’autorisent pas une direction, une
  régularité, une cause ou un conseil.

**Diagnostic :** les calculs étaient déjà bornés, mais la hiérarchie était trop
globale. Elle survalorisait les faits d’effort, la FC moyenne ou des faits
disponibles, et laissait le validateur empêcher une information distincte,
mieux étayée, de mener le commentaire. Les limites de longueur et l’absence de
prose libre ne résolvaient pas le choix de l’idée principale.

## 3. Règles C373-B

La sélection est une suite de règles contextuelles explicites, pas un score :

1. Un écart de type à la prescription, réellement admis et autorisé, peut mener.
   Il reste explicitement limité à la classification V3.
2. Une comparaison de durée distinctive d’une sortie longue mène lorsqu’elle
   est admise.
3. Une tendance corroborée ou une comparaison historique admissible précède
   une borne d’effort générique.
4. Une FC moyenne au-dessus de LT2, établie par des seuils personnels fiables,
   peut mener comme observation distincte, sans prétendre décrire chaque moment.
5. Parmi les faits sur les répétitions : direction V2, régularité V2, mesure
   individuelle, puis structure enregistrée. Si aucune de ces conclusions
   n’est admise, aucune direction/régularité n’est fabriquée.
6. Sans ces faits, une observation directe est préférée à une étiquette probable.
   Les types inconnus restent inconnus ; sans fait utile, le Coach s’abstient.

Le LLM peut choisir un fait principal parmi les candidats de premier rang
autorisés par le contexte. Le fallback choisit toujours le premier candidat
déterministe. Un à deux compléments ne sont ajoutés que s’ils apportent une
dimension indépendante ; plusieurs scénarios n’en produisent aucun.

Le validateur interdit désormais aussi plusieurs faits historiques dans une
même synthèse (y compris `session.long` et `trend.*`/`comparison.*`), le cumul
direction/régularité avec une énumération de répétitions, ainsi que les bornes
avec un verdict de régularité. Les limites antérieures, le maximum de trois
affirmations et la réalisation fermée sont conservés.

## 4. Matrice comparative représentative

Les sélections « avant » décrivent le fallback C373-A/C372 à partir des mêmes
faits admissibles. Les textes finaux sont les réalisations backend C373-B ;
les valeurs ci-dessous sont des scénarios synthétiques de tests.

| Scénario et faits admis | Sélection avant → après | Texte final après | Redondance retirée / perte et limites |
| --- | --- | --- | --- |
| Fractionné homogène : `interval.regularity`, bornes et couverture | `[regularity, effort.first]` → `[regularity]` | « Les allures des répétitions comparables sont homogènes. » | Retire une borne non nécessaire. Verdict V2 conservé ; pas de conclusion physiologique. |
| Série significativement ralentissante : `interval.pace_direction`, `interval.regularity`, bornes, couverture | `[pace_direction]` → `[pace_direction]` | « Les 2 dernières répétitions comparables sont 15 s/km plus lentes que les 2 premières (répétition centrale exclue). » | La sélection distinctive reste inchangée. Pas de fatigue, causalité ni progrès inféré. |
| Série irrégulière sans direction admise : `interval.regularity` et observations partielles/comparables | `[regularity, effort.first]` → `[regularity]` | « Les répétitions comparables présentent des variations d'allure importantes. » | Retire une borne répétitive ; aucune direction n’est imposée. |
| Deux efforts : `interval.count`, `intensity.hr`, premières/dernières mesures | `[effort.first, intensity.hr, effort.last]` → `[effort.first]` | « Dans l'ordre enregistré par Garmin, le premier effort (n° 1) a duré 4 min, à 5'00/km. » | Retire comptage, moyenne de FC et deuxième borne ; aucun verdict de série ni direction. |
| Données partielles : `interval.count`, `intensity.position`, `effort.first/last`, couverture recalculée | `[effort.first, intensity.position, effort.last]` → `[effort.first]` | « Dans l'ordre enregistré par Garmin, le premier effort (n° 1) a duré 4 min (seule mesure disponible). » | La borne manquante n’est pas remplacée par une mesure intérieure ; ni couverture ni constat de série ne deviennent des conclusions. |
| Historique riche et effort enregistré : `trend.probable_improvement`, `comparison.*`, `effort.first/last`, `intensity.position` | `[effort.first, trend, intensity.position]` → `[trend]` | « Ton historique suggère une amélioration probable : 6 observations sur 92 jours, variation d'allure médiane de −24 s/km (récente moins ancienne) ; ce n'est pas une preuve de changement de forme. » | L’historique corroboré remplace la borne générique ; la borne et la FC ne sont pas restituées. Aucun fait de tendance perdu ni preuve de forme revendiquée. |
| Sortie longue : `session.long`, `intensity.position` | `[session.long, intensity.position]` → `[session.long]` | « Ta sortie est probablement longue : 100 min, contre 50 min habituellement. » | Retire une observation moyenne non nécessaire ; conserve l’incertitude et la limite durée ≠ effort. |
| Footing facile sans historique autorisé : `session.kind`, `intensity.position` | `[intensity.position]` → `[intensity.position]` | « Ta FC moyenne est de 140 bpm, sous LT1 ; elle ne décrit pas tout l'effort. » | Pas d’étiquette ou comparaison inventée ; la moyenne ne devient ni temps passé en zone ni intensité de chaque effort. |
| Type inconnu sans FC : `session.unknown` | `[session.unknown]` → `[session.unknown]` | « Le type de ta séance reste incertain ; aucune FC moyenne n'est disponible. » | Abstention sur l’intensité et l’objectif ; aucune transformation en séance facile. |
| Écart de prescription documenté au niveau du type : `prescription.review`, `interval.count`, `intensity.position` | `[interval.count, intensity.position, prescription.review]` → `[prescription.review]` | « Le type observé diffère du type prescrit selon la classification V3 ; cette lecture ne modifie pas la prescription. » | L’écart documenté prime sur l’énumération. Ce n’est ni une conformité complète, ni une cause, ni une nouvelle prescription. |
| FC moyenne au-dessus de LT2 et direction V2 : `intensity.position`, `interval.pace_direction`, `interval.regularity`, bornes | `[pace_direction, intensity.position]` → `[intensity.position, pace_direction]` | « Ta FC moyenne est de 180 bpm, au-dessus de LT2 ; elle ne décrit pas tout l'effort. Les 2 dernières répétitions comparables sont 15 s/km plus lentes que les 2 premières (répétition centrale exclue). » | L’information d’une autre nature, fondée sur seuils fiables, peut mener ; la direction demeure devant les autres faits de répétitions. La moyenne ne représente pas toute la séance. |
| Historique absent et FC moyenne seule : `intensity.hr`, `session.unknown` | `[intensity.hr]` → `[intensity.hr]` | « Ta FC moyenne enregistrée est de 140 bpm ; elle ne suffit pas à établir une zone physiologique. » | Aucun historique insuffisant n’est présenté comme une tendance ; l’incertitude du type et la limite physiologique restent intactes. |

La sélection avant/après change réellement lorsque plusieurs dimensions
concurrentes étaient disponibles ; l’amélioration n’est pas seulement une
reformulation. Les mesures omises restent disponibles dans le catalogue mais
ne sont pas obligatoirement récitées.

## 5. Commentaires finaux FR / EN / ES

Même scénario synthétique : direction V2 « 2 dernières répétitions comparables,
15 s/km plus lentes », accompagnée d’une observation indépendante de FC moyenne
au-dessus de LT2. Les deux phrases sont réalisées en backend :

- **FR** — « Ta FC moyenne est de 180 bpm, au-dessus de LT2 ; elle ne décrit pas
  tout l'effort. Les 2 dernières répétitions comparables sont 15 s/km plus
  lentes que les 2 premières (répétition centrale exclue). »
- **EN** — “Your average HR is 180 bpm, above LT2; it does not describe the
  entire effort. The final 2 comparable repetitions are 15 s/km slower than
  the opening 2 (middle repetition excluded).”
- **ES** — « Tu FC media es de 180 lpm, por encima de LT2; no describe todo el
  esfuerzo. Las 2 últimas repeticiones comparables son 15 s/km más lentas que
  las 2 primeras (se excluye la repetición central). »

La réalisation est déterministe et conserve l’unité, la portée V2 et
l’exclusion du milieu pour cinq efforts. Les autres exemples localisés sont
assertés par les tests.

## 6. LLM, flag et limites

Aucun appel LLM réel n’a été effectué : les tests utilisent des sélections
synthétiques/injectées, sans données personnelles ni fournisseur de production.
Le coût réel et la qualité d’un appel réel ne sont donc pas évalués.

Le LLM ne peut fournir ni texte, nombre, preuve, calcul, cause ou conseil.
Une sélection inconnue, contradictoire, redondante ou hors priorité est rejetée
et revient au fallback déterministe. Le flag `C359_HYBRID_COACH_ENABLED` reste
**OFF par défaut** ; aucun code de route ou d’interface ne le modifie.

## 7. Fichiers et validation

Fichiers modifiés :

- `backend/hybrid_coach_editorial_c365.py` — candidats principaux contextuels,
  priorités de sélection et anti-redondance historique/répétitions.
- `backend/hybrid_coach_c359.py` — fallback explicable et prompt éditorial
  aligné sur les règles.
- `backend/tests/test_hybrid_coach_c365.py`,
  `backend/tests/test_hybrid_coach_c371.py`,
  `backend/tests/test_hybrid_coach_c372.py` — scénarios, sélections, fallback,
  données V2, limites et traductions.
- `docs/reports/C373_B_HYBRID_EDITORIAL_SELECTION.md` — audit et matrice.

Commande exécutée depuis `backend/` :

```sh
python -m pytest -q \
  tests/test_hybrid_coach_c359.py \
  tests/test_hybrid_coach_c362.py \
  tests/test_hybrid_coach_c364_audit.py \
  tests/test_hybrid_coach_c365.py \
  tests/test_hybrid_coach_c371.py \
  tests/test_hybrid_coach_c372.py
```

Résultat final : **594 tests réussis**. Inclut les scénarios de série homogène,
accélérante/ralentissante/irrégulière, deux efforts, seuils, historique,
prescription de type, données partielles, abstention, fallback, sélection LLM
valide/invalide, FR/EN/ES et flag OFF. Aucun test ne fait d’appel LLM réel.

## 8. Risques et verdict

- Les règles éditoriales restent des choix déterministes, non une mesure
  scientifique d’importance.
- Les textes de plusieurs catégories sont testés, mais aucune évaluation de
  qualité sur un vrai appel LLM n’est disponible.
- Le coach reste isolé de l’application et inactif par défaut.

**Verdict : GO pour revue de la PR ; HOLD pour activation, intégration ou
production.** Aucun merge, déploiement ou activation n’est demandé.
