# C408-C — Contrat de preuves sportives et historique Coach

Base : `copilot/dev` @ `829f69a` (contient C408-B, PR #393). Head : voir la PR.
Rapport = instantané de preuves ; la source de vérité reste le code et `RUNINDEX_MASTER_ROADMAP_AND_DECISIONS.md`.

## Verdict : HOLD (validation réelle NON EXÉCUTÉE)

L'environnement d'implémentation n'a ni clé LLM, ni MongoDB, ni réseau. Les 4 réponses
`gpt-4.1-mini` sur les séances réelles (10/10, 12/10, 13/09, 26/10), la vérification des écritures
MongoDB réelles, la latence/coût LLM réels et les 16 tests HTTP `test_coach_conversational`
n'ont **pas** été exécutés. Aucune grille PASS/FAIL n'est annoncée : les 4 lignes sont **NOT RUN**.
Les campagnes précédentes restent 0/4 (C408) et 0/4 (C408-B). Pas de C408-D automatique.

## 1. Défaut #393 — historique tronqué

Cause : `truncated` venait du plafond de couverture (30 séances) alors que seules 5 séances
(`HISTORY_MAX_SESSIONS`) étaient transmises.

| Champ `history_as_of_session` | Avant | Après |
|---|---|---|
| `truncated` | plafond de couverture seulement (faux avec 7–11 éligibles / 5 transmises) | vrai si éligibles > transmises **ou** couverture tronquée |
| `eligible_count` / `included_count` | absents | présents (éligibles = antérieures prouvées + exclues en amont) |
| `window`, `cutoff_precision`, `eligibility`, `selection` | absents | présents (5 plus récentes, plus récente d'abord) |
| `eligible_count_is_lower_bound` | – | si la couverture est tronquée sans effectif amont |
| `runner_profile.population` | absent | scope, `sessions_count`, `period_start`, `period_end` (population statistique ≠ 5 affichées) |

Les statistiques de profil restent désactivées si la population est tronquée en amont. La taille (5) est inchangée.

## 2. Provenance V3 (réutilise les résultats V3, aucun recalcul)

`coach_context_v2._relative_effort_provenance` / `_comparison_provenance` : type de métrique, population,
effectif, dates, critères (`distance_is_a_selection_criterion: false`, `is_the_history_block_listing: false`),
valeur observée/référence, méthode, confiance, limites. Comparaison : sous-populations allure@FC et FC@allure séparées.

Exemples (synthétiques, mêmes valeurs que les cas réels) : FC relative 12/10 → 31 séances 20/04→05/10 ;
26/10 → 16 séances 06/05→22/09 ; ces populations ne sont ni « 5 séances de même distance » ni la liste affichée.

## 3. Contrat de preuves

`frame["evidence_contract"]` : `measured_facts`, `validated_comparisons`, `allowed_interpretations`,
`not_demonstrated` (intensité physiologique, récupération, conformité, progression, FC≠intensité externe…), `usage`.
Construit uniquement depuis V2/V3 déjà présents.

## 4. Chronologie des prescriptions

`WIV3PrescriptionAssessment.served_at` (instant du premier enregistrement). Le Coach reçoit `recorded_at`,
`recording_timing` ∈ {`recorded_before_session`, `recorded_after_session`, `recording_time_unknown`} et une règle.
`indeterminate` = aucun verdict de conformité, jamais un écart. Prescription postérieure ⇒
`intent_status = prescription_recorded_after_session_not_a_known_intent`. Snapshots non modifiés, rien recalculé.
Limite : un horaire Garmin local naïf est lu comme UTC (limite connue de `_parse_exact_datetime`).

## 5. Identifiants

Retirés du contexte LLM de chat : `workout_id(s)`, `garmin_activity_id`, `activity_id`, `external_id`,
`prescription_id`, `user_id`, `id` de la séance sélectionnée (`strip_technical_ids`). Les liens
observation→source passent par `source_path`/codes. Les identifiants restent côté backend (contrôle d'accès, chargement).

## 6. Contrôle après génération (`coach_evidence_guard.py`)

Une génération, un contrôle déterministe CPU, aucun second appel LLM, aucune boucle.
**Contrôlé** : chiffres/unités/dates et jargon physiologique/sensations/conseils/objectif (garde C403 réutilisée) ;
effectifs de population non fondés ; FC relative décrite comme « même distance » ; statistique de profil attribuée aux 5
séances affichées ; non-respect de prescription (sauf verdict `deviation`) ; prescription inexistante ; prescription
postérieure présentée comme intention ; hausse de FC lue comme hausse d'intensité ; allure lue comme meilleure performance ;
besoin de récupération.
**Non contrôlé** : paraphrases, comparaisons implicites, exactitude sportive globale, utilité/ton. Un `passed` signifie
seulement « aucune affirmation *contrôlée* n'est contredite », pas « vérité ». Toute conseil de « prochaine séance »
est rejeté par la garde C403 (conservateur) ⇒ repli factuel.
**Repli** : réponse fr/en/es construite depuis le contrat (mesures, allures de répétitions, position FC avec population et
période, chronologie de prescription, une phrase de limite). Sans contrat exploitable : quota remboursé, 503.
La réponse expose `verification` (`passed`, `rejected_checks`, `response_source` = `llm_reply_checked` | `contract_fallback`, `check_ms`).
Risque de faux « validé » : réel pour les cas non couverts ; documenté ci-dessus.

## 7. Tests

Nouveau : `backend/tests/test_coach_c408c_evidence_contract.py` — 38 tests : historiques 0/1/5/6/8/11 (effectifs,
troncature, ordre, doublons, séances postérieures), population ≠ sélection, ids retirés / pas de fuite inter-utilisateur,
provenance FC/allure, prescription avant/après/inconnue/absente/`indeterminate`, garde (effectifs, population, physiologie,
récupération, performance, conformité), repli, câblage serveur (repli sans écriture hors `conversations`/`coach_quota_counters`).
Ajustés : stubs de réponse LLM trop courts (`test_coach_contract_unified`, c393, c394, pr325) et assertions d'ids retirés (context_v2, C408 ×3).

Backend complet (venv local sans emergent/litellm) : avant 238 échecs/erreurs, après 238 (aucun nouveau ; 7135 réussis).
Les échecs restants sont préexistants et d'environnement : tests HTTP live (`requests` sans URL), Mongo/réseau, etc.
- `test_coach_conversational.py` (16 tests HTTP) : **NOT RUN** (`MissingSchema`, serveur live + Mongo requis).
- `test_pr211_coach_llm_cleanup.py::test_server_coach_analyze_no_hr_speed_vma_exposure` : échec **préexistant**, indépendant de C408-C
  (assertion de source sur `predict_races(`).
- Frontend Coach : **NOT RUN** (frontend non modifié ; champ `verification` additif).
- Training V2 : suites existantes C408-B (lecture seule) passent ; instrumentation d'écritures réutilisée.

## 8. Latence / coût

Garde : ~1,2 ms CPU par réponse de ~300 caractères (mesuré), repli ~0,004 ms ; `check_ms` enregistré par réponse.
Aucun appel LLM ajouté ⇒ coût LLM inchangé hors taille de prompt (ids retirés vs contrat ajouté, **non mesuré** en tokens).

## 9. Écritures MongoDB

Test mocké : seules `conversations` et `coach_quota_counters` sont écrites. Vérification sur base réelle : **NOT RUN**.

## 10. Risques résiduels

- Qualité des 4 réponses réelles non démontrée.
- Garde heuristique (regex) : faux négatifs possibles, faux positifs (repli) possibles sur les conseils « prochaine séance ».
- Heure locale Garmin naïve interprétée en UTC pour la chronologie des prescriptions.
- Prochaine étape recommandée : exécuter la campagne de 4 appels dans un environnement avec clé/Mongo, ou comparer une autre stratégie/modèle.
