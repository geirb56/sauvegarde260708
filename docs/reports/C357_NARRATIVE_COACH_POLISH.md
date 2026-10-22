# C357 — Narrative Coach Polish

## Périmètre et références exactes

- Base : `copilot/dev`, `6a96b4ab4f049a92070e56f5e0687978700bbaf7`.
- Prérequis vérifié sur GitHub : [C356 / PR #356](https://github.com/geirb56/sauvegarde260708/pull/356), mergée le 22/10/2026 à 05:11:18 UTC.
- Branche : `copilot/c357-narrative-coach-polish`.
- HEAD de code testé : `e2f9ad34430d07f2b70da86d93dea8c6106fc052`.
- Les commits ultérieurs de rapport ne modifient pas ce code ; le SHA de livraison est donné dans la PR et le message de livraison.
- Objectif unique : améliorer la rédaction du catalogue narratif approuvé, sans changer les faits ou les moteurs.

## Audit ciblé

Lecture du catalogue `backend/narrative_coach_v3.py`, de
`backend/narrative_coach_v3_models.py`, des tests narratifs C355 et de
`frontend/src/components/workout/NarrativeWorkoutAnalysis.jsx`,
`frontend/src/lib/analysisFormat.js` et des libellés `workoutNarrative` dans
`frontend/src/lib/i18n.js`. Le moteur V3 n'a pas fait l'objet d'un nouvel audit.

Constats :

- Le français mélangeait « Votre », « vos », « Vous pouvez » avec un ton informel.
- Le format `:g` conservait trop de décimales et le point décimal en français/espagnol.
- Le jugement approuvé des quatre répétitions était précédé d'une longue explication de cohorte déjà couverte par « répétitions comparables ».
- Sans jugement de régularité, l'interprétation et les limitations répétaient la même impossibilité de conclure.
- Pour une séance indéterminée, une FC moyenne pouvait prendre la place de l'explication de cette indétermination.
- La sélection C355 éliminait déjà les répétitions concernant LT1, le nombre de références et la prescription ; ce comportement utile est conservé.

## Fichiers modifiés

| Fichier relatif à la racine du dépôt | Modification |
|---|---|
| `backend/narrative_coach_v3.py` | Tutoiement, formatage centralisé, déduplication et priorité à l'explication du type indéterminé. |
| `backend/tests/test_narrative_coach_v3.py` | 82 cas paramétrés supplémentaires ; assertions C355 adaptées uniquement aux textes et arrondis concernés. |
| `docs/reports/C357_NARRATIVE_COACH_POLISH.md` | Présent rapport. |

Les contrats, le frontend, les calculs physiologiques, la classification,
l'historique, Training, Garmin et les abonnements ne sont pas modifiés.

## Formatage numérique et langues

`format_narrative_number` est l'unique fonction de formatage des mesures
fractionnaires intégrées au catalogue. Elle produit au plus une décimale,
supprime le zéro décimal superflu et utilise le signe moins Unicode.
Les nombres de phases, observations et références restent des comptes entiers.

| Valeur source | FR | EN | ES |
|---|---|---|---|
| `16.5621` | `16,6` | `16.6` | `16,6` |
| `6.600000` | `6,6` | `6.6` | `6,6` |
| `-3.0000` | `−3` | `−3` | `−3` |
| `6.6`, écart signé | `+6,6` | `+6.6` | `+6,6` |
| `0`, `-0.0`, `-0.04` | `0` | `0` | `0` |
| `None`, booléen, chaîne, NaN, infini | Aucun nombre fabriqué | Aucun nombre fabriqué | Aucun nombre fabriqué |

- Application aux dispersions, écarts du jugement approuvé, FC et variations d'allure.
- Les gardes de disponibilité restent en amont de l'affichage : une donnée absente n'est pas convertie en zéro.
- Aucun arrondi avant calcul ; les valeurs numériques V2/V3 demeurent identiques.
- Les tests vérifient notamment qu'une preuve `16.5621` reste exactement `16.5621`.
- Le français utilise « ta », « ton », « tes », « tu peux » ; « fréquence cardiaque » remplace « FC » dans les phrases principales concernées.
- Aucune assertion « dernières observations » n'est ajoutée.
- EN et ES conservent leurs formulations idiomatiques, avec point décimal EN et virgule FR/ES.
- Exemple stable FR : « Sur tes 5 observations comparables, la tendance reste stable (variation d'allure médiane de −3 s/km) : ta progression n'est pas encore démontrée. » Il s'agit d'un exemple de test, pas d'une tendance réelle.
- L'interface C356 affiche les phrases reçues sans les réécrire. Son formatage des preuves numériques est déjà limité à une décimale ; aucune correction frontend n'est nécessaire pour ce périmètre.

## Avant / après — exécution sur fixtures synthétiques

**Aucune validation Garmin réelle n'est revendiquée.** L'environnement ne fournit
ni configuration MongoDB/Garmin exploitable, ni export local des quatre séances
dans les répertoires de données inspectés. Aucune connexion de production ni
écriture MongoDB n'a été effectuée.

Les quatre analogues ci-dessous sont explicitement **synthétiques** :
`_polish_scenarios` dans les tests. Les dates sont des étiquettes de scénario,
pas les dates d'observations chargées depuis Garmin. Leurs nombres ne sont pas
présentés comme ceux des séances réelles.

Les textes ont été obtenus en exécutant en mémoire le catalogue de la base exacte
et celui du HEAD de code sur les mêmes entrées. Le scénario quatre répétitions
utilise le jugement V2 existant produit par la fixture, sans le recalculer dans
la narration. Le scénario six efforts ne fournit aucun jugement catégoriel.

### Analogue synthétique du 10/10/2026 — quatre répétitions

**Avant**

> Une séance fractionnée
>
> Garmin a enregistré 4 phases d'effort et 3 phases de récupération.
>
> Pour comparer ce qui est comparable, 4 des 4 efforts ont été regroupés selon une durée similaire ; des efforts de tailles différentes ne doivent pas être traités comme des répétitions équivalentes. Allures homogènes sur vos 4 répétitions comparables : un écart moyen de 0.5 s/km par rapport à l'allure centrale.
>
> La conformité à la prescription reste indéterminée.

**Après**

> Une séance fractionnée
>
> Garmin a enregistré 4 phases d'effort et 3 phases de récupération.
>
> Allures homogènes sur tes 4 répétitions comparables : un écart moyen de 0,5 s/km par rapport à l'allure centrale.
>
> La conformité à la prescription reste indéterminée.

Aucun conseil supplémentaire. Le jugement « homogènes » provient exclusivement
de la conclusion approuvée, pas de la seule dispersion.

### Analogue synthétique du 19/09/2026 — six efforts, cinq récupérations

**Avant**

> Une séance fractionnée
>
> Garmin a enregistré 6 phases d'effort et 5 phases de récupération.
>
> Pour comparer ce qui est comparable, 6 des 6 efforts ont été regroupés selon une durée similaire ; des efforts de tailles différentes ne doivent pas être traités comme des répétitions équivalentes. L'alternance effort-récupération identifie le fractionné, mais la comparaison fournie ne permet pas d'établir la régularité d'exécution des répétitions.
>
> La régularité des efforts est indisponible ; les répétitions ne peuvent pas être dites régulières.
>
> La conformité à la prescription reste indéterminée.

**Après**

> Une séance fractionnée
>
> Garmin a enregistré 6 phases d'effort et 5 phases de récupération.
>
> Pour comparer ce qui est comparable, 6 des 6 efforts ont été regroupés selon une durée similaire ; des efforts de tailles différentes ne doivent pas être traités comme des répétitions équivalentes. La comparaison disponible ne permet pas d'établir la régularité des répétitions ; cela ne signifie pas qu'elles étaient irrégulières.
>
> La conformité à la prescription reste indéterminée.

Aucun conseil supplémentaire. La réserve sur la régularité n'apparaît plus deux
fois. L'absence de jugement n'est pas transformée en irrégularité.

### Analogue synthétique du 12/10/2026 — footing probablement facile

**Avant**

> Probablement un footing facile
>
> Par rapport à vos 8 séances personnelles de référence, cet effort paraît relativement facile.
>
> Votre historique comparable est insuffisant pour conclure avec confiance à une amélioration ou à une baisse.
>
> Vous pouvez conserver un effort confortable, sans chercher systématiquement à accélérer.
>
> Sans splits ni LT1 fiable, les moyennes de séance ne permettent pas de confirmer une zone physiologique.
>
> La conformité à la prescription reste indéterminée.

**Après**

> Probablement un footing facile
>
> Par rapport à tes 8 séances de référence, cet effort paraît relativement facile.
>
> Ton historique comparable ne permet pas encore de savoir avec confiance si tu progresses ou si tes performances baissent.
>
> Tu peux garder un effort confortable, sans chercher systématiquement à accélérer.
>
> Sans splits ni LT1 fiable, les moyennes de séance ne permettent pas de confirmer une zone physiologique.
>
> La conformité à la prescription reste indéterminée.

L'effort relatif, la tendance et la zone physiologique restent des notions
distinctes. Le conseil prudent existait déjà ; aucune nouvelle prescription
n'est créée. La réserve LT1 est conservée une seule fois.

### Analogue synthétique du 19/10/2026 — tapis indéterminé

**Avant**

> Type de séance incertain
>
> Votre FC moyenne sur cette séance était de 140 bpm.
>
> Votre historique comparable est insuffisant pour conclure avec confiance à une amélioration ou à une baisse.
>
> Sans splits ni LT1 fiable, les moyennes de séance ne permettent pas de confirmer une zone physiologique.
>
> La conformité à la prescription reste indéterminée.

**Après**

> Type de séance incertain
>
> Les données disponibles ne permettent pas d'identifier le type de séance de façon fiable.
>
> Ton historique comparable ne permet pas encore de savoir avec confiance si tu progresses ou si tes performances baissent.
>
> Sans splits ni LT1 fiable, les moyennes de séance ne permettent pas de confirmer une zone physiologique.
>
> La conformité à la prescription reste indéterminée.

Aucun conseil supplémentaire. Aucun type de séance n'est inventé ; la FC
synthétique ne sert pas de substitut à une classification fiable.

## Tests exécutés

Répertoire de travail :
`/home/runner/work/sauvegarde260708/sauvegarde260708/backend`.
Python 3.12.3, pytest 9.1.1, Pydantic 2.13.4.
Configuration existante conservée : `-n 2 --dist loadscope`.
Les dépendances de test absentes au départ ont été restaurées dans
l'environnement, sans modifier les manifests du dépôt.

### Suites demandées

```text
python -m pytest tests/test_narrative_coach_v3.py tests/test_workout_intelligence_v3.py -q
320 passed, 7 warnings

python -m pytest tests/test_narrative_coach_v3.py -q
227 passed
```

Les 82 nouveaux cas couvrent les arrondis FR/EN/ES, signes et zéros, valeurs
absentes/non finies, tutoiement, régularité approuvée ou non démontrée, footing
relatif sans LT1, tendances stables/déclin/amélioration, séance indéterminée,
déduplication, preuves obligatoires, fallback, LLM désactivé et contrats API.
Les tests C355 conservés couvrent notamment l'historique insuffisant,
les attaques sur le validateur, les indisponibilités du fournisseur et le cache.

### Régression étendue V2/V3 et autorités existantes

```text
python -m pytest tests/test_narrative_coach_v3.py tests/test_workout_intelligence_v3.py tests/test_workout_analysis_v2.py tests/test_workout_analysis_v2_phases.py tests/test_workout_analysis_v2_facts.py tests/test_workout_analysis_v2_unified.py tests/test_coach_language.py tests/test_coach_session_synthesis_c351.py tests/test_coach_repetition_judgment.py -q --tb=short
1328 passed, 3 failed, 14 warnings
```

Les trois échecs concernent exclusivement
`test_workout_analysis_v2.py::test_comparable_history_stays_separate_and_metrics_are_unchanged[en/fr/es]` :
attendu `meaning.consistent_pacing`, obtenu `meaning.hr_without_intensity_with_pacing`.

**Reproduction indépendante sur la base exacte** : archive Git du backend à
`6a96b4ab4f049a92070e56f5e0687978700bbaf7`, même environnement, commande :

```text
python -m pytest tests/test_workout_analysis_v2.py::test_comparable_history_stays_separate_and_metrics_are_unchanged -q --tb=short
3 failed, 14 warnings
```

Même divergence pour les trois langues. L'archive temporaire a été supprimée.
Ces échecs préexistants n'ont pas été corrigés et aucun test sans rapport n'a
été modifié. Aucun build ou test frontend/E2E n'est revendiqué dans C357.

## Validation des preuves et sécurité

- Comparaison AST avec la base : `validate_narrative_selection`,
  `_approved_repetition_judgment` et `generate_narrative_coach_v3` **inchangés**.
- Aucun changement des fichiers de modèles narratif/V2/V3 ni des moteurs V2/V3.
- Catalogue fermé uniquement ; tous les identifiants sélectionnables restent
  liés à des chemins de preuves. Aucune rédaction libre du LLM.
- Retirer n'importe quelle affirmation obligatoire ou ajouter de la prose
  libre reste rejeté dans les tests des quatre scénarios et des trois langues.
- La réserve de régularité supprimée des limitations est toujours exprimée
  dans l'interprétation ; ses références de disponibilité accompagnent celle-ci.
- Le numéro de génération passe à `c357-controlled-1` pour invalider les textes
  mis en cache par l'ancienne version.
- LLM toujours désactivé par défaut ; aucun appel fournisseur réel.
- Contrôles de non-mutation des valeurs et enveloppes API réussis.
- `git diff --check` réussi ; scan des deux fichiers Python : aucun secret détecté.
- `parallel_validation` exécuté après commit : CodeQL Python, **0 alerte**.
  Le composant automatisé de revue de code signale que son binaire est
  indisponible ; cela ne constitue pas une revue complète réussie.
- Revue complémentaire en lecture seule par l'agent `code-review`, contre la
  même base : aucun problème significatif détecté.

## Limites et verdict

**GO conditionnel** pour une revue en PR brouillon, pas pour un déploiement.

- Les suites narratives et V3 demandées sont vertes.
- Trois échecs V2 préexistants sont explicitement reproduits sur la base.
- L'absence de données réelles interdit toute conclusion sur le rendu exact
  des quatre séances Garmin de l'utilisateur.
- Une vérification en lecture seule sur ces données reste à faire lorsqu'elles
  seront disponibles ; les exemples ci-dessus ne la remplacent pas.
- L'interface C356 n'est pas modifiée ni revalidée en navigateur dans C357.
- Aucun merge automatique, déploiement, changement d'abonnement, écriture
  MongoDB ou modification Garmin. Attendre la validation avant tout merge.
