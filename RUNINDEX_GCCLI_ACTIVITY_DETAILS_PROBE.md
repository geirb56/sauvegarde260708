# RUNINDEX — Test GCCLI : détails d'une activité Garmin (probe)

> Test **lecture seule**, autorisé par l'utilisateur pour **une seule activité** et **une seule tentative** de récupération.
> Aucune écriture MongoDB, aucune synchronisation, aucun import, aucun changement de code, aucune PR, aucun téléchargement FIT.
> Aucun secret d'authentification n'est affiché ni conservé. Les coordonnées GPS retournées par Garmin ont été volontairement exclues.

---

## 1. Environnement utilisé

| Élément | Valeur |
|---|---|
| Binaire GCCLI | `/app/backend/bin/gccli` (présent dans l'environnement réel du worker, **absent du `PATH` global** — `GCCLI_PATH` non défini, défaut `"gccli"`) |
| Workers Garmin | `garmin-sync/event/monitor/scheduler-worker` tous `RUNNING` (supervisor) |
| `GCCLI_HOME` (base) | `/app/backend/.gccli_home` |
| HOME par utilisateur | `/app/backend/.gccli_home/<user_id>` (isolation stricte par utilisateur, session restaurée depuis Mongo `garmin_sessions`, chiffrée Fernet) |
| Keyring backend | `file` (`GCCLI_KEYRING_BACKEND=file`, comme le runner) |
| Provider configuré | `GARMIN_PROVIDER="gccli"` (provider réel, mock supprimé) |

**Remarque sécurité** : le fichier `.env` contient des identifiants Garmin globaux en clair (`GARMIN_USERNAME` / `GARMIN_PASSWORD`). Ils ne sont **pas** reproduits ici. Recommandation hors périmètre : les traiter comme secrets gérés et non comme variables `.env` versionnables.

## 2. Version GCCLI

```
gccli 1.9.0 (0893b24) built 2026-06-15T09:38:05Z
```

Commandes de lecture détaillée **disponibles** (extrait de `--help`) :
`activity summary`, `activity details`, `activity splits`, `activity typed-splits`, `activity split-summaries`, `activity hr-zones`, `activity power-zones`, `activity weather`, `activity gear`.

## 3. Commande de lecture testée (unique)

```
gccli activity typed-splits 24671804067 -j
```
Environnement exact : `HOME=<.gccli_home/da8505ef…>`, `GCCLI_KEYRING_BACKEND=file`, `-j` (JSON).
- Session préalablement vérifiée : `auth status` → **authentifié**, non expiré (`expires_at = 2026-10-11T08:49:02Z`), compte `mal***@gmail.com`.
- Résultat : **succès en une seule tentative** (exit 0, aucun retry), 29 809 octets JSON.

Le choix de `typed-splits` (plutôt que `details`/`splits`) est délibéré : c'est la commande qui répond directement à l'objectif (identifier les fractions d'une séance structurée).

## 4. Identifiant d'activité (anonymisé)

| Attribut | Valeur |
|---|---|
| Nom | `Vannes - 4x4min @allure Z5` |
| Garmin `activityId` | `24671804067` |
| Utilisateur RunIndex | `da8505ef…` (anonymisé) |

## 5. Résultat réel de la récupération

Structure JSON : `{ activityId, activityUUID, splits: [29 éléments] }`.
Chaque split expose : `type`, `duration`, `movingDuration`, `elapsedDuration`, `distance`, `averageSpeed`, `maxSpeed`, `averageHR`, `maxHR`, `averageRunCadence`, `maxRunCadence`, `strideLength`, `elevationGain/Loss`, `calories`, `messageIndex`, `lapIndexes`.

**Répartition des types** : `INTERVAL_WARMUP ×1`, `INTERVAL_ACTIVE ×4`, `INTERVAL_RECOVERY ×4`, `INTERVAL_COOLDOWN ×1`, `RWD_RUN ×10`, `RWD_WALK ×9`
(les `RWD_*` = segments auto « Run/Walk Detection » de Garmin, superposés aux laps structurés).

### Les 4 efforts structurés (type `INTERVAL_ACTIVE`)

| Rép. | Durée | Distance | Allure moy. (dérivée) | FC moy | FC max |
|---|---|---|---|---|---|
| 1 | **240,0 s** (4:00) | 832 m | ~4:48/km | 151 | 160 |
| 2 | **240,0 s** (4:00) | 851 m | ~4:42/km | 157 | 165 |
| 3 | **240,0 s** (4:00) | 886 m | ~4:31/km | 159 | 175 |
| 4 | **240,0 s** (4:00) | 825 m | ~4:51/km | 159 | 166 |

Récupérations (`INTERVAL_RECOVERY`) : 4 × 180 s (3:00), FC moy 133–141.

## 6. Inventaire des données disponibles

| Donnée | Disponible | Format | Nombre d'éléments |
|---|---|---|---|
| Laps | **Oui** | segments typés (lap-level) | 29 |
| Splits | **Oui** (ce sont des typed-splits) | liste JSON | 29 |
| FC temporelle (séries) | Non via cette commande | — (FC moy/max **par split** présentes) | — |
| Vitesse/allure temporelle (séries) | Non via cette commande | — (vitesse moy/max **par split** présentes) | — |
| Intervalles (effort/récup) | **Oui, explicites** | `INTERVAL_ACTIVE` / `INTERVAL_RECOVERY` | 4 + 4 |
| Zones FC | Non testé (règle « une seule tentative ») — commande dédiée `activity hr-zones` existe | — | — |
| Structure d'entraînement | **Oui** | warmup / active / recovery / cooldown étiquetés | 1/4/4/1 |

### Identification des 4 répétitions

**FAIT DÉMONTRÉ** : les quatre efforts de quatre minutes sont **explicitement fournis par Garmin** (4 laps `INTERVAL_ACTIVE` de 240 s exactement), accompagnés de leurs 4 récupérations `INTERVAL_RECOVERY`, d'un warmup et d'un cooldown.

Distinction demandée :
- **Intervalles explicitement fournis par Garmin** : ✅ oui (type de lap `INTERVAL_*`). Aucune reconstruction nécessaire.
- **Reconstructibles depuis séries temporelles** : non requis ici (les séries ne sont même pas nécessaires pour identifier la structure).
- **Données insuffisantes** : ❌ non — les données sont suffisantes et non ambiguës.

> Les 4 répétitions ne sont **pas** déduites du titre : elles proviennent des laps typés enregistrés par la montre.

## 7. Capacité à identifier les répétitions

Totale, et de manière fiable : durée (240 s), distance, allure dérivée, FC moyenne et maximale **par répétition** sont disponibles. Cela suffit à Workout Analysis V2 pour produire une vraie analyse de séance structurée (nombre d'efforts, durée/allure/FC par effort, qualité d'exécution, récupérations).

## 8. Limites et erreurs éventuelles

- Aucune erreur lors du test (exit 0, pas de retry).
- La commande `typed-splits` ne fournit **pas** les séries temporelles continues (FC/allure échantillonnées) ni les zones FC — ce sont des commandes séparées (`activity details`, `activity hr-zones`) non exécutées ici par respect de la règle « une seule tentative ».
- La session utilisateur expire le `2026-10-11T08:49Z` → un rafraîchissement d'auth sera nécessaire au-delà.
- Les coordonnées GPS par split sont retournées (données personnelles) : à ne pas stocker inutilement.

## 9. Faisabilité d'une PR #321

**Faisable et à faible risque.** Le binaire, la version et la session sont opérationnels dans l'environnement worker ; la donnée nécessaire existe et est directement exploitable.

- **Commande exacte** : `gccli activity typed-splits <activityId> -j` (réutilise `GccliRunner._run_json` existant — même pattern que `activities list`).
- **Format** : JSON `{activityId, activityUUID, splits[]}` ; champs utiles par split : `type`, `duration`, `distance`, `averageSpeed`, `averageHR`, `maxHR`, `averageRunCadence`, `messageIndex`, `lapIndexes`.
- **Données utiles à conserver** : uniquement les laps structurés (`INTERVAL_*`) + leurs métriques ; éventuellement `activity hr-zones` pour l'intensité physiologique (provenance fiable → lèverait le verrou `_has_trusted_zone_provenance`). Exclure GPS si non nécessaire.
- **Compatibilité import actuel** : le modèle `GarminActivity` (`data_layer.py`) doit recevoir de nouveaux champs (`typed_splits`/`laps`, `lap_count`, `has_splits`) ; l'enrichissement V2 (`workout_analysis_v2_service.py`) sait déjà consommer `km_splits`/`splits` s'ils existent.
- **Coût** : 1 appel gccli supplémentaire **par activité**, uniquement pour les activités à analyser en détail (≈30 KB JSON par activité).
- **Récupération ciblée post-résumé** : ✅ possible — fetch du détail à la demande (lazy) sur une activité déjà importée en résumé, via son `activityId`.
- **Risques Garmin** : rate-limit si on récupère les détails de **toutes** les activités à chaque sync → à éviter.

## 10. Recommandation technique

1. **Ne pas** récupérer les détails de toutes les activités à chaque synchronisation. Garder la sync résumé actuelle inchangée.
2. Ajouter une **récupération ciblée à la demande** (lazy) des `typed-splits` au moment où une analyse détaillée est requise (ouverture Workout Analysis), avec cache/persistance idempotente par `activityId`.
3. Persister uniquement les laps structurés + métriques par lap ; conditionner la détection d'intervalles à la présence réelle de laps `INTERVAL_*` (jamais au titre).
4. Séparer l'intensité physiologique : n'activer `_has_trusted_zone_provenance` qu'avec `activity hr-zones` fiables (PR distincte), pour respecter l'invariant « pas d'intensité sans preuve ».
5. Gérer explicitement les 3 états : laps présents / laps absents / détail non encore récupéré (≠ vide).

> Conclusion : **GCCLI fournit bien les données nécessaires à l'analyse des séances fractionnées.** Le blocage identifié lors de l'audit précédent est confirmé comme étant purement côté ingestion RunIndex (détails jamais demandés), et il est levable via une PR #321 ciblée et bornée.

*(Test non répété. Aucune autre activité interrogée. `activity hr-zones` / `activity details` non exécutés par respect de la règle d'une seule tentative — disponibles pour un prochain probe autorisé si besoin.)*
