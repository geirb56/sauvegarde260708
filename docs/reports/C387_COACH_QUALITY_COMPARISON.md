# C387 — Qualité du Coach : comparaison statique, comparaison réelle non réalisée

## 1. Statut, références et limites

Audit du 29 octobre 2026, en prolongement de C386 / PR #377.

- Historique **H** effectivement lu : `9b7947ec2e1bcd40d520b775f6d4f14a5ef4bcff`.
- Base `copilot/dev` et code actuel **C** : `b80bfb174a0e64150b597503e79835a11bf9079d`,
  confirmé par `git ls-remote origin refs/heads/copilot/dev`.
- HEAD documentaire entrant : `fd50e1b8ed0f45e664e76172969c26617cb9e7cf`.
  Aucun écart applicatif avec C (`git diff C HEAD -- backend frontend` vide).
- Seul fichier créé par C387 : `docs/reports/C387_COACH_QUALITY_COMPARISON.md`.
- **Aucun appel LLM autorisé, donc aucun exécuté.** Accessibilité du fournisseur
  et présence de credentials non testées. Aucun appel Garmin, MongoDB, HTTP
  applicatif, déploiement, import ou exécution des moteurs.
- Tests applicatifs/build/lint non exécutés : documentation seule.
  Validation limitée aux blobs Git, références, plages de lignes, diff et secrets.

**La comparaison qualitative sur les trois séances identiques n'est pas réalisée.**
Les données V2/V3 validées et textes C384 nécessaires n'ont pas été retrouvés
dans les sources consultées. Ce rapport établit des différences de mécanisme,
pas un classement de réponses réelles ni une preuve que V1 était meilleur.

Les références ci-dessous sont figées sur H/C, et non sur une branche mouvante.
Le rapport C386 sert de point de départ ; les constats sont revérifiés dans
le code et les artefacts primaires. Les rapports historiques ne décrivent pas
automatiquement l'état actuel.

## 2. Données disponibles et provenance

Recherche statique dans les fichiers suivis : `C384`, dates ISO/françaises,
distances et fixtures ; inventaire des rapports et exemples JSON. Recherche
GitHub de PR contenant C384 : aucun résultat renvoyé. Cela **ne prouve pas**
l'absence de données ailleurs, dans un autre environnement ou dans une session
antérieure ; aucune recherche dans MongoDB n'a été effectuée.

| Séance demandée | Ce qui est vérifiable ici | Ce qui manque pour comparer |
|---|---|---|
| 12/10/2026, footing, 9,33 km | Date/type/distance désignent la cible fournie dans la demande. La fixture C351 reprend date/distance mais déclare explicitement ses autres données **synthétiques**. | Export Garmin complet lié à C384, payload V2 validé, V3/narration et réponses chat réelles. |
| 10/10/2026, fractionné, 14,26 km | Même identification par la demande ; C351 contient une séance et des répétitions explicitement **synthétiques**. | Mêmes exports validés ; structure réelle, mesures des efforts et couverture non établies ici. |
| 13/09/2026, sortie longue, 21,27 km | Deux exemples de laps Garmin anonymisés portent cette date ; le fichier déclare **2 laps sur 22**, pas une séance complète. Le rapport P331 documente des totaux historiques cohérents avec 21,27 km. | Les 20 autres laps, les payloads V2/V3 validés C384, la narration actuelle et les réponses chat. |

Sources :

- [Fixture C351][c351] L2–11, L34–65 : mention « NOT Mongo/Garmin runtime validation » ;
  les 68,6 min / 127 bpm du 12/10 et les quatre efforts de 240 s du 10/10 ne
  deviennent **pas** des observations Garmin réelles par ressemblance de date.
- [Laps partiels][laps] L1–58 : exemple de début et fin du 13/09, pas une série
  permettant d'établir la régularité de toute la sortie ou sa FC moyenne.
- [P331][p331] L67–83 : ancien contrôle sur 22 laps, 21 274,5 m et 7 290,5 s ;
  preuve documentaire historique, **pas** payload V2/V3 actuel validé.
- [Test V2][v2-test] L452–478 : la fixture de 21,27 km / 160 bpm date du
  **15/06/2025**, donc pas de substitution à la séance du 13/09/2026.
- [Exemple C352][c352] L1–7 : exemple V3 synthétique daté du 10/05/2026,
  impropre à remplacer une réponse C384.

**Aucun ensemble commun de faits autorisés issu de V2 ne peut donc être
constitué de façon vérifiée pour ces trois séances.** Les trois libellés de
la demande sont des identifiants de travail, pas des classifications V2 validées.
Pas de rapprochement probabiliste, pas de calcul depuis deux laps et pas
de reconstruction de valeurs absentes.

### Observations fiables, incertitudes et conclusions interdites

Pour chacune des trois séances, les faits V2, leur disponibilité, les références
historiques et leurs limites restent **non établis dans ce corpus**. Même pour
le 13/09, une valeur par lap ne représente pas la moyenne de séance.

Sont exclus : qualifier l'intensité depuis FC/allure/titre seuls, supposer
des zones/LT1/LT2, déduire fatigue, hydratation, efficacité ou progression,
inventer une régularité du fractionné, attribuer un état Training actuel à
une date passée, ou créer la prochaine séance. Les permissions correspondantes
sont explicites dans [le prompt actuel][c-llm] L62–78, L180–187.

## 3. Textes intégraux et scores : état réel

| Séance | Résumé LLM séance V1 | Synthèse V2 validée | Narrative V3 actuelle | Chat V1 | Chat actuel |
|---|---|---|---|---|---|
| 12/10/2026 | Non généré, non fourni | Non retrouvée | Non retrouvée | Non généré, non fourni | Non généré, non fourni |
| 10/10/2026 | Non généré, non fourni | Non retrouvée | Non retrouvée | Non généré, non fourni | Non généré, non fourni |
| 13/09/2026 | Non généré, non fourni | Non retrouvée | Non retrouvée | Non généré, non fourni | Non généré, non fourni |

Il n'y a **aucun texte réel à reproduire intégralement** dans cette comparaison.
Les chaînes littérales citées plus bas sont des instructions/templates du code,
pas des réponses exécutées. Aucun texte simulé ou réécrit ne les remplace.

| Critère demandé, sur 0–5 | État pour toutes les réponses des trois séances |
|---|---|
| Exactitude factuelle | Non évalué : absence de réponse et de référence V2 commune. |
| Compréhension de la séance | Non évalué : absence de réponse et de structure réelle validée. |
| Exploitation des données individuelles | Non évalué : contexte réellement transmis non capturé. |
| Pertinence des observations | Non évalué : aucun texte réel disponible. |
| Qualité des explications | Non évalué : aucun texte réel disponible. |
| Utilité du conseil | Non évalué : aucun texte ni prescription historique validée disponible. |
| Naturel et fluidité | Non évalué : aucun texte réel disponible. |
| Absence de répétitions et de banalités | Non évalué : aucun texte réel disponible. |

**Non évalué n'est pas 0/5.** Aucun score global, moyenne, classement ou écart
qualitatif significatif n'est calculé. Inventions, causalités non justifiées
et prescriptions incompatibles : non évaluables au niveau des réponses,
distinctes des risques de mécanisme exposés ci-dessous. La longueur n'est
pas utilisée comme substitut de qualité.

## 4. Fiche séance : trois mécanismes différents

### Résumé V1 libre, mais projection historique imparfaite

H : `/rag/workout/{id}` → `coach_service.analyze_workout` →
`llm_coach.enrich_workout_analysis` → prose LLM ; en cas d'échec, résumé local.
Le service projette distance, durée, FC, dénivelé, type/zones, comparaison et
points forts/faibles. **Ce n'est pas le chat.**
[H-service][h-service] L137–197 ; [H-LLM][h-llm] L81–90, L163–174.

Le prompt séance demande réaction positive, analyse simple, point marquant,
conseil pour la prochaine sortie, suivi facultatif, 4–5 phrases.
Cela autorise une rédaction libre mais pousse vers un conseil prescriptif
sans la restriction Training du prompt chat. Ne pas réintroduire ce contrat.

Le service lit `pace_str` et `splits_analysis` à la racine alors que
[la sortie RAG][h-rag] L1246–1274 les représente sous `workout.allure` et
`workout.split_analysis` : perte effective d'allure/splits dans cette projection,
malgré leur disponibilité locale. Les tips JSON ne sont pas transmis au LLM.
**Ce défaut ne doit pas être reproduit dans un futur essai à faits identiques.**
Aucun ancien calcul RAG, jugement physiologique ou conseil n'a été réexécuté.

H : [l'interface][h-ui] L705–707 n'affichait que les **quatre premières lignes**
du résumé. Il faut donc distinguer réponse fournisseur, réponse nettoyée,
payload HTTP et texte réellement visible, même pour V1.

### Synthèse V2 : sélection de faits, pas conversation

[Le sélecteur V2][synthesis] L9–40, L52–119 exige une preuve numérique finie
et des `source_paths`, sélectionne une observation principale et au plus deux
supports, sans recalcul scientifique. Il déduplique catégories/codes/textes,
applique une condition d'environnement aux conclusions historiques, puis
ajoute au plus deux limites ou une abstention (L121–175).

Ce mécanisme peut restituer une conclusion déjà autorisée mais ne possède
pas la liberté explicative d'un LLM. Ce constat porte sur son contrat,
pas sur son utilité effective pour les trois séances manquantes.

### Narrative V3 : autre sélection, puis variantes fermées

[Le service V3][v3-service] L167–216 construit V2 puis V3 ; il transmet à la
narration `intelligence`, `phase_analysis`, `coach_language`, **pas**
`session_synthesis`. Le texte libre de Coach Language n'est pas consommé par
ce rédacteur : seuls certains éléments autorisés servent de preuves.
[Narrative][narrative] L644–656.

La sélection éditoriale précède le LLM (L469–534). Hors fractionné,
elle retient une analyse principale parmi type inconnu / effort relatif /
position / FC, puis les éléments de section `interpretation`. Exemple vérifié :
`comparison.pace` est construit en section `analysis` (L360–371), mais ne
figure pas dans cette liste de priorités (L478–484). Sa construction n'implique
donc pas son inclusion dans le texte final par ce sélecteur ; l'UI peut
néanmoins afficher la comparaison ailleurs.

Le fallback choisit la variante 0 de chaque assertion retenue (L612–626).
L'option LLM est conditionnée par `C355_NARRATIVE_LLM_ENABLED` ; sa valeur
déployée **n'est pas vérifiée**. Même activé, le LLM doit sélectionner toutes
les assertions fournies exactement une fois : variantes/ordre dans une section,
**aucune prose libre ni omission** (L661–695).

[L'UI actuelle][c-ui] L190–204, L266–279 privilégie Narrative V3 lorsqu'elle
est valide ; la synthèse V2 est dans la branche alternative. Le total enregistré
est filtré des items de synthèse (L191–194).
[Le composant Narrative][n-ui] L5–10, L74–103 affiche headline/analyse/
interprétation, recommandation éventuelle, première limite ; les comparaisons
chiffrées et limites suivantes peuvent être dans un bloc de détails repliable.

**Écart établi :** davantage de faits dans V2 n'implique pas que sa synthèse
soit la prose visible en tête de fiche. Modifier le prompt du chat ne change
pas ce chemin. L'effet perceptif sur C384 reste non mesuré.

## 5. Chat : comparaison statique des prompts et paramètres

| Dimension | Chat H | Chat C | Portée du constat |
|---|---|---|---|
| Rôle et liberté | Coach bienveillant, prose libre, 3–5 phrases, pas de listes sauf demande. | Même rôle ; modes initial/suivi/Training/général, prose toujours libre. | Le chat actuel n'est pas le catalogue fermé V3. |
| Personnalisation | JSON canonique, question et historique ; demande d'utiliser les données réelles. | Détail V2 et historique borné explicitement mentionnés ; priorité au point distinctif et aux comparaisons utiles. | Les contextes de production H/C ne sont pas identiques par construction. |
| Réponse initiale/suivi | Pas de modes distincts dans cette fonction. | Initial : 3–5 phrases, environ 60–110 mots, 2–3 chiffres ; suivi : 1–3 phrases, sans récapitulatif inutile. | Différence de consigne, effet réel non testé. |
| Données manquantes | Signaler un champ indisponible/faible confiance. | Signaler celui nécessaire à la réponse ; au plus une réserve naturelle utile. | L'allègement des réserves est déjà demandé, pas une correction entièrement absente. |
| Science et prescription | Training décide déjà ; pas d'invention ni nouvelle prescription. | Restrictions détaillées sur FC/allure brutes, permissions, comparabilité et séparation historique/actuel. | Ne pas gagner artificiellement en assurance en retirant ces garanties. |
| Mémoire transmise | 4 messages au plus, chacun tronqué à 200 caractères. | Même limite dans `enrich_chat_response`. | Pas de nouvelle réduction démontrée par ces limites. |

Preuves : [H-LLM][h-llm] L32–67, L111–146 ;
[C-LLM][c-llm] L32–78, L95–141, L148–205.
Pas de question, historique ni contexte commun exécuté pendant C387.

Paramètres vérifiés dans le code H/C : `gpt-4.1-mini`, fournisseur configuré
`openai` via Emergent, timeout 15 s, nouvelle session fournisseur par requête.
Température, seed, top-p et plafond de tokens **non explicitement fixés dans
ces appels** ; les valeurs effectives du SDK/fournisseur ne sont pas établies.
La réponse textuelle est nettoyée et plafonnée à **700 caractères** aux deux
snapshots, avec recherche d'une ponctuation après 400 caractères.
[H-LLM][h-llm] L21–25, L177–217, L261–276 ;
[C-LLM][c-llm] L21–25, L209–253, L291–306.

Ce budget n'est ni une preuve de changement de modèle ni une régression
nouvelle. Pour V3, la limite de 700 vise le JSON de sélection compact
(pas la longueur du texte reconstruit localement) :
[Narrative][narrative] L564–577, L674–695.

## 6. Causes : établies, possibles, non évaluables

| Axe demandé | Établi statiquement | Ce qui reste hypothèse ou manque |
|---|---|---|
| Faits transmis | Projection V1 imparfaite ; V3 ne reçoit pas directement la synthèse V2. Certaines assertions construites sont éliminées par la sélection. | Perte effective d'un fait utile sur chacune des trois séances : payloads absents. |
| Prompt | V1 séance sollicite un prochain conseil ; chat actuel ajoute permissions et modes de concision. | Ces consignes rendent-elles une réponse moins naturelle à faits identiques ? Aucun essai. |
| Modèle | Même identifiant/configuration H/C. | Changement fournisseur effectif, variabilité, version servie : non mesurés. |
| Longueur | 700 caractères pour le chat et ancien résumé ; historique 4 × 200. | Troncature réellement responsable d'une mauvaise réponse C384 : aucune trace. |
| Interface | V3 prioritaire sur synthèse V2 ; détails de comparaison repliables ; ancien résumé limité à quatre lignes. | Perception sur les trois séances : aucune capture actuelle correspondante. |
| Narration fermée | Aucune reformulation libre, sélection préalable obligatoire, fallback variante 0. | Effet mesuré sur fluidité/répétition : non évalué. |
| Capacité manquante | Pas de preuve qu'un nouveau moteur soit nécessaire ; faits V2 et chat libre existent. | Corpus réel, réponses intégrales et protocole autorisé manquent pour conclure. |

**Aucune faiblesse de réponse précise n'est attribuée sans réponse observée.**
Les écarts ci-dessus sont architecturaux ; aucun écart de score ni supériorité
de V1 n'est démontré.

## 7. Plus petite correction envisageable et verdict

**HOLD pour une PR corrective :** ne pas modifier le produit sur ce seul rapport.
**GO pour une future comparaison contrôlée**, après obtention des exports C384
validés et autorisation explicite des appels LLM ; aucune autorisation implicite.

Conditions nécessaires : mêmes faits V2 disponibles et mêmes abstentions pour
chaque rédacteur, séparation fiche/chat, même langue/question/historique pour
les deux chats, absence de contexte Training contemporain ajouté à une ancienne
séance, paramètres et versions capturés. Conserver intégralement les réponses
brutes, nettoyées et rendues ; identifier les sélections/fallbacks V3.
Ne pas réexécuter le RAG historique pour remplir `strengths` ou `comparison`.

Un essai avec le prompt V1 séance mais des faits V2 et des restrictions Training
ajoutées sera une **adaptation contrôlée**, pas une restitution du pipeline V1
exact ; toute modification du prompt devra être divulguée. Sans garde-fous,
le conseil demandé « next run » ne constitue pas un avantage qualitatif légitime.

**Candidat minimal, uniquement si les textes réels confirment une perte en tête
de fiche :** ajuster la priorité éditoriale/le rendu des conclusions V2 déjà
autorisées plutôt que créer un moteur, recalculer la physiologie ou recopier
les conseils V1. Pour le chat, aucune correction minimale précise n'est
encore justifiée : ses consignes demandent déjà un point distinctif, peu de
chiffres et une seule réserve. Allonger systématiquement les réponses ou
affaiblir les permissions ne découle pas des preuves.

**Conclusion : comparaison statique réalisée ; comparaison qualitative réelle
non réalisée ; restauration ou correction non autorisée et non effectuée.**

## Sources primaires

[h-service]: https://github.com/geirb56/sauvegarde260708/blob/9b7947ec2e1bcd40d520b775f6d4f14a5ef4bcff/backend/coach_service.py
[h-llm]: https://github.com/geirb56/sauvegarde260708/blob/9b7947ec2e1bcd40d520b775f6d4f14a5ef4bcff/backend/llm_coach.py
[h-rag]: https://github.com/geirb56/sauvegarde260708/blob/9b7947ec2e1bcd40d520b775f6d4f14a5ef4bcff/backend/rag_engine.py
[h-ui]: https://github.com/geirb56/sauvegarde260708/blob/9b7947ec2e1bcd40d520b775f6d4f14a5ef4bcff/frontend/src/pages/WorkoutDetail.jsx
[c-llm]: https://github.com/geirb56/sauvegarde260708/blob/b80bfb174a0e64150b597503e79835a11bf9079d/backend/llm_coach.py
[synthesis]: https://github.com/geirb56/sauvegarde260708/blob/b80bfb174a0e64150b597503e79835a11bf9079d/backend/coach_session_synthesis.py
[v3-service]: https://github.com/geirb56/sauvegarde260708/blob/b80bfb174a0e64150b597503e79835a11bf9079d/backend/workout_intelligence_v3_service.py
[narrative]: https://github.com/geirb56/sauvegarde260708/blob/b80bfb174a0e64150b597503e79835a11bf9079d/backend/narrative_coach_v3.py
[c-ui]: https://github.com/geirb56/sauvegarde260708/blob/b80bfb174a0e64150b597503e79835a11bf9079d/frontend/src/pages/WorkoutDetail.jsx
[n-ui]: https://github.com/geirb56/sauvegarde260708/blob/b80bfb174a0e64150b597503e79835a11bf9079d/frontend/src/components/workout/NarrativeWorkoutAnalysis.jsx
[c351]: https://github.com/geirb56/sauvegarde260708/blob/b80bfb174a0e64150b597503e79835a11bf9079d/backend/tests/fixtures/coach_session_synthesis_c351.json
[laps]: https://github.com/geirb56/sauvegarde260708/blob/b80bfb174a0e64150b597503e79835a11bf9079d/backend/tests/fixtures/garmin_laps_fixture.json
[p331]: https://github.com/geirb56/sauvegarde260708/blob/b80bfb174a0e64150b597503e79835a11bf9079d/docs/reports/RUNINDEX_GARMIN_LAPS_PAYLOAD_VALIDATION.md
[v2-test]: https://github.com/geirb56/sauvegarde260708/blob/b80bfb174a0e64150b597503e79835a11bf9079d/backend/tests/test_workout_analysis_v2.py
[c352]: https://github.com/geirb56/sauvegarde260708/blob/b80bfb174a0e64150b597503e79835a11bf9079d/docs/reports/c352_examples/footing_relative_history_fr.json
