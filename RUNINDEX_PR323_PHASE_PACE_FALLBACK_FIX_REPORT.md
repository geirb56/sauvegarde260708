# RUNINDEX — PR323 — Correction du fallback allure

## 1. Références exactes

- Dépôt : `geirb56/sauvegarde260708`.
- Base cible : `copilot/dev`, vérifiée par `git fetch origin copilot/dev`.
- HEAD de départ et base vérifiée : `8ac2034fb1b26096601eb5e2e87d820276360170`.
- Ce commit est le merge de #322 ; son parent de contribution est
  `74acae3376631d1907fb1eff26373758ee81389b`.
- Branche de travail nouvelle : `copilot/fix-phase-pace-calculation`.
- HEAD du code et des tests validés : `c9eaab4a0c36c560ea790dac3509613f6c7c95db`.
- Le commit de ce rapport est documentaire ; le HEAD de livraison est indiqué
  dans la description de PR, pour éviter une référence circulaire dans ce fichier.
- Le numéro PR323 est celui demandé ; GitHub attribue le numéro réel.

## 2. Défaut confirmé dans le code réel

Dans `backend/workout_analysis_v2.py`, `_phase_pace()` exige des mesures
strictement positives pour utiliser la branche durée/distance, mais la branche
suivante acceptait toute vitesse finie positive, même avec une durée ou une
distance explicitement nulle.

Avant correction, les nouveaux tests reproduisent notamment `(0, 800, 4)` et
`(240, 0, 4)` donnant à tort `250 s/km`. Les tests de régularité et de cache
reproduisent également l'inclusion indue de ces allures :
**11 échecs, 63 réussites** sur la suite phases enrichie avant le correctif.

## 3. Correction exacte

Deux lignes de production ajoutent un retour anticipé `(None, False)` lorsque
`duration == 0 or distance == 0`, avant tout calcul ou fallback.

- Une mesure `None` ne déclenche pas ce retour.
- Le contrôle de cohérence reste strictement `relative_difference > 0.2`.
- Avec durée/distance positives et vitesse cohérente, la vitesse reste
  l'autorité utilisée par le calcul existant.
- Sans vitesse fiable, les mesures positives conservent leur calcul propre.
- Aucun nouvel indicateur ni contrat public n'est ajouté.
- L'absence d'allure utilise les mécanismes existants : `missing_data`,
  exclusion des statistiques d'allure et décompte des échantillons de régularité.
- Un zéro ne devient ni une mesure absente ni une contradiction de vitesse :
  aucune limitation `incoherent_pace` n'est ajoutée pour ce seul motif.

## 4. Matrice des cas testés

| Cas | Résultat vérifié |
| --- | --- |
| Durée 0, distance 800, vitesse 4 | Allure `None` |
| Durée 240, distance 0, vitesse 4 | Allure `None` |
| Durée et distance 0, vitesse 4 | Allure `None` |
| Durée 0/distance `None`, ou inversement | Allure `None` ; le zéro interdit le fallback |
| Durée `None`, distance 800, vitesse 4 | Fallback `250 s/km` |
| Distance `None`, durée 240, vitesse 4 | Fallback `250 s/km` |
| Durée et distance `None`, vitesse 4 | Fallback `250 s/km` |
| Vitesse 0, -1, NaN, +Inf, -Inf ; mesures absentes en totalité ou partiellement | Aucune allure issue de la vitesse |
| Durée 240, distance 800 ; vitesse absente ou invalide | Calcul durée/distance conservé : `300 s/km` |
| Durée 240, vitesse 4, distance 960 ou 800 | Vitesse cohérente ; `250 s/km`, comportement existant |
| Durée 240, vitesse 4, distance 768 | Écart exactement 20 % accepté |
| Durée 240, vitesse 4, distance 767 | Allure `None`, limitation `incoherent_pace` |
| Fixture #322 : quatre efforts de 240 s | Allures arrondies inchangées : 288, 282, 271, 291 s/km |
| Deux efforts comparables dont une allure invalidée par zéro | `pace_sample_count=1`, `available=False`, `partial_comparison=True`, dispersion `None` |
| Trois efforts comparables dont une allure invalidée par zéro | `pace_sample_count=2`, `available=True`, `partial_comparison=True`, dispersion sur les deux seules allures valides |
| Comparaison sur durée et sur distance | Les deux bases sont testées, avec zéro sur l'autre mesure |
| Cache : mesure zéro puis mesure `None`, vitesse 4 | Zéro préservé, allures `[None, 250]`, comparaison partielle indisponible |
| Cache : vitesse négative ou non finie | Cache rejeté comme auparavant ; analyse standard |

Les assertions couvrent aussi `average_pace_sec_per_km`, le changement
premier/dernier effort, les statistiques de durée/distance/FC et les limitations
`effort_paces_incomplete` et `insufficient_comparable_effort_paces`.
Les limitations de non-comparabilité ne sont pas ajoutées à tort.
Aucun test précédent n'est supprimé.

## 5. Résultats réels et commandes

Répertoire des suites :
`/home/runner/work/sauvegarde260708/sauvegarde260708/backend`.
Interpréteur : `/tmp/runindex-pr323-venv/bin/python` (Python 3.12.3).
Configuration pytest inchangée : `-n 2 --dist loadscope`.

| Exécution | Résultat |
| --- | --- |
| `python -m pytest tests/test_workout_analysis_v2_phases.py -q` avant correction | 11 échecs, 63 réussites |
| Même commande après correction | **74 réussites** |
| `python -m pytest tests/test_workout_analysis_v2.py tests/test_mobile_workout_analysis.py tests/test_activity_details_pr321.py tests/test_activity_details_delayed_redis_c321.py -q` avant installation de Redis serveur | 254 réussites, 34 ignorés |
| `python -m pytest tests/test_workout_analysis_v2_phases.py tests/test_workout_analysis_v2.py tests/test_mobile_workout_analysis.py tests/test_activity_details_pr321.py tests/test_activity_details_delayed_redis_c321.py -q -rs` après installation de Redis serveur | **362 réussites, aucun ignoré, 14 avertissements** |
| `python -m flake8 --select=E9,F63,F7,F82` sur les deux fichiers Python modifiés, avec leurs chemins absolus | Réussite |
| `git diff --check` et `git diff 8ac2034fb1b26096601eb5e2e87d820276360170 HEAD --check` depuis la racine du dépôt | Réussite |

Les premiers lancements ont été bloqués par l'absence de pytest puis de httpx
et redis. Les outils existants ont été restaurés dans un environnement isolé.
L'installation globale des requirements a échoué sur le téléchargement du wheel
interne litellm (résolution DNS) ; les dépendances existantes nécessaires aux
suites ont ensuite été installées avec leurs versions du dépôt.
Redis serveur local a été installé pour exécuter les 34 tests auparavant ignorés.
Aucun fichier de dépendances du dépôt n'a changé.

Validation complémentaire effectuée après commit :

- Scan de secrets sur les trois fichiers : aucun secret détecté.
- CodeQL Python : **0 alerte**.
- La revue de `parallel_validation` est indisponible : modèle de revue absent
  du registre malgré le libellé « Success » renvoyé par l'outil.
- Une revue read-only distincte par l'agent `code-review` a donc été exécutée :
  aucun problème significatif trouvé.

Les avertissements proviennent de dépréciations existantes
(Starlette, passlib, Pydantic et hooks FastAPI).

## 6. Fichiers modifiés et périmètre de non-régression

Chemins relatifs à
`/home/runner/work/sauvegarde260708/sauvegarde260708` :

1. `backend/workout_analysis_v2.py` : garde zéro uniquement.
2. `backend/tests/test_workout_analysis_v2_phases.py` : matrice et interactions.
3. `RUNINDEX_PR323_PHASE_PACE_FALLBACK_FIX_REPORT.md` : ce rapport.

Le service cache, les modèles, l'isolation utilisateur, l'ordre/types natifs,
les splits kilométriques et le contrat API ne sont pas modifiés.
Les suites existantes couvrent ces chemins et les activités sans phases.
Une assertion compare intégralement le payload hors `phase_analysis` avec
l'analyse standard ; les statistiques de durée, distance et FC gardent les zéros.

Aucun changement Garmin/GCCLI, Training V2, Readiness, Coach IA, frontend,
architecture ou collecte. Aucun nouveau déclenchement d'enrichissement, de
requête fournisseur ou de job ; les tests de collecte utilisent leurs mocks
existants. Le chargement cache conserve son enrichissement local existant.

## 7. Risques résiduels

- Risque limité au retrait voulu d'allures auparavant calculées malgré un zéro :
  la régularité peut devenir partielle ou indisponible.
- Les données directes invalides continuent à suivre les règles existantes ;
  la validation des caches reste inchangée.
- Tests synthétiques et caches reconstruits : ils ne prouvent pas le contenu
  d'une activité réelle Garmin et ne remplacent pas une revue technique.
- Aucun déploiement, aucun merge automatique.
- L'indisponibilité de la revue intégrée est compensée par une revue distincte ;
  celle-ci et CodeQL ne remplacent pas les points Emergent ci-dessous.

## 8. Points de validation Emergent

À réaliser en revue, sans déploiement ni accès fournisseur déclenché par ce travail :

1. Vérifier les deux lignes de garde et la distinction `None != 0`.
2. Vérifier le payload sur cache existant : zéro préservé, allure JSON `null`,
   limitation d'allures incomplètes, seuil de disponibilité à deux allures valides.
3. Confirmer le fallback fiable pour `None` et le seuil de cohérence inchangé.
4. Recontrôler la fixture #322, les statistiques non-allure, l'isolation utilisateur
   et le comportement standard sans phases.
5. Examiner les résultats de revue automatisée et de sécurité avant toute décision.
6. Attendre la revue technique ; ne pas merger ni déployer automatiquement.
