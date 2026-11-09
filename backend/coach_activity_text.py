"""C409 — FR / EN / ES wording of the deterministic activity answers.

Plain format strings only: every number is injected by the caller from the comparison or history
contract. A language other than French or Spanish falls back to English.
"""
from __future__ import annotations

LANGS = ("fr", "en", "es")


def lang_of(language: str) -> str:
    value = (language or "").lower()
    if value.startswith("fr"):
        return "fr"
    if value.startswith("es"):
        return "es"
    return "en"


MONTHS = {
    "fr": ["janvier", "février", "mars", "avril", "mai", "juin", "juillet", "août", "septembre",
           "octobre", "novembre", "décembre"],
    "en": ["January", "February", "March", "April", "May", "June", "July", "August", "September",
           "October", "November", "December"],
    "es": ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto", "septiembre",
           "octubre", "noviembre", "diciembre"],
}

# key -> (fr, en, es)
_T = {
    "and": ("et", "and", "y"),
    "date_on": ("le {d} {month}{year}", "on {d} {month}{year}", "el {d} de {month}{year}"),
    "date_bare": ("{d} {month}{year}", "{d} {month}{year}", "{d} de {month}{year}"),
    "date_year": (" {y}", " {y}", " de {y}"),
    "date_ref_prep": ("au {bare}", "{bare}", "al {bare}"),
    # session sentence
    "verb_a": ("tu as parcouru", "you covered", "recorriste"),
    "verb_b": ("tu as couru", "you ran", "corriste"),
    "dist_dur": ("{dist} km en {dur}", "{dist} km in {dur}", "{dist} km en {dur}"),
    "dist": ("{dist} km", "{dist} km", "{dist} km"),
    "dur_only": ("durée {dur}", "duration {dur}", "duración {dur}"),
    "pace_at": ("à {pace}/km", "at {pace}/km", "a {pace}/km"),
    "avg_hr_at": ("avec une FC moyenne de {hr} bpm", "with an average HR of {hr} bpm",
                  "con una FC media de {hr} bpm"),
    "max_hr_at": ("FC max {hr} bpm", "max HR {hr} bpm", "FC máx. {hr} bpm"),
    "elev_at": ("{m} m de dénivelé positif", "{m} m of climbing", "{m} m de desnivel positivo"),
    "no_distance_head": ("séance enregistrée", "recorded session", "sesión registrada"),
    # metric names
    "n_distance_km": ("distance", "distance", "distancia"),
    "n_duration_min": ("durée", "duration", "duración"),
    "n_pace_s_per_km": ("allure", "pace", "ritmo"),
    "n_avg_hr": ("FC moyenne", "average HR", "FC media"),
    "n_max_hr": ("FC max", "max HR", "FC máx."),
    "n_elevation_gain_m": ("dénivelé", "climbing", "desnivel"),
    # gap phrases: lead (higher / faster) then trail
    "g_distance_km_up": ("distance supérieure de {v}", "distance {v} longer", "distancia superior en {v}"),
    "g_distance_km_down": ("distance inférieure de {v}", "distance {v} shorter", "distancia inferior en {v}"),
    "g_duration_min_up": ("durée supérieure de {v}", "duration {v} longer", "duración superior en {v}"),
    "g_duration_min_down": ("durée inférieure de {v}", "duration {v} shorter", "duración inferior en {v}"),
    "g_pace_s_per_km_up": ("allure plus rapide de {v}", "pace {v} faster", "ritmo {v} más rápido"),
    "g_pace_s_per_km_down": ("allure plus lente de {v}", "pace {v} slower", "ritmo {v} más lento"),
    "g_avg_hr_up": ("FC moyenne supérieure de {v} bpm", "average HR {v} bpm higher",
                    "FC media superior en {v} bpm"),
    "g_avg_hr_down": ("FC moyenne inférieure de {v} bpm", "average HR {v} bpm lower",
                      "FC media inferior en {v} bpm"),
    "g_max_hr_up": ("FC max supérieure de {v} bpm", "max HR {v} bpm higher", "FC máx. superior en {v} bpm"),
    "g_max_hr_down": ("FC max inférieure de {v} bpm", "max HR {v} bpm lower", "FC máx. inferior en {v} bpm"),
    "g_elevation_gain_m_up": ("dénivelé supérieur de {v} m", "climbing {v} m higher",
                              "desnivel superior en {v} m"),
    "g_elevation_gain_m_down": ("dénivelé inférieur de {v} m", "climbing {v} m lower",
                                "desnivel inferior en {v} m"),
    "gaps_one": ("{label}, par rapport {other} : {clauses}", "{label}, compared with {other}: {clauses}",
                 "{label}, frente {other}: {clauses}"),
    "gaps_identical": (", mesures identiques : ", ", identical: ", ", valores idénticos: "),
    "gaps_identical_item": ("mesures identiques : ", "identical: ", "valores idénticos: "),
    "gaps_many": ("Écarts : ", "Gaps: ", "Diferencias: "),
    "missing": ("Non disponible, donc non comparé : ", "Not available, so not compared: ",
                "No disponible, por lo que no se compara: "),
    "limit_diff": (
        "Ces deux séances n'ont pas la même distance et pas forcément le même objectif : ces écarts "
        "décrivent les séances, mais ne démontrent ni une progression, ni un changement de VO2max, "
        "de seuil ou de récupération, ni que l'une était plus difficile physiologiquement.",
        "These two sessions differ in distance and not necessarily in purpose: the gaps describe "
        "the sessions but do not show progress, a change in VO2max, threshold or recovery, or that "
        "one was physiologically harder.",
        "Estas dos sesiones no tienen la misma distancia ni necesariamente el mismo objetivo: las "
        "diferencias describen las sesiones, pero no demuestran ni una progresión, ni un cambio de "
        "VO2max, de umbral o de recuperación, ni que una fuera fisiológicamente más difícil."),
    "limit_same": (
        "Ces écarts décrivent les deux séances ; ils ne suffisent pas, seuls, à conclure sur ta forme, "
        "ta VO2max, ton seuil ou ta récupération.",
        "These gaps describe the two sessions; on their own they do not allow conclusions about "
        "fitness, VO2max, threshold or recovery.",
        "Estas diferencias describen las dos sesiones; por sí solas no bastan para concluir sobre tu "
        "forma, tu VO2max, tu umbral o tu recuperación."),
    # focused answers
    "progress": (
        "Je ne peux pas conclure que tu progresses à partir de ces deux séances. {a} {b} "
        "Deux séances isolées ne prouvent pas une évolution de ta forme ; "
        "pour en parler, il faudrait des séances comparables dans le temps. "
        "Je peux comparer avec tes dernières sorties similaires.",
        "I can't conclude that you are improving from these two sessions. {a} {b} "
        "Two isolated sessions do not show a change in fitness; that needs "
        "comparable sessions over time. I can compare with your most similar recent runs.",
        "No puedo concluir que estés progresando a partir de estas dos sesiones. {a} {b} "
        "Dos sesiones aisladas no demuestran una evolución de tu forma; para "
        "hablar de ello harían falta sesiones comparables a lo largo del tiempo. "
        "Puedo comparar con tus últimas salidas similares."),
    "hr_head": (
        "Côté cardio, la FC moyenne était de {a} bpm {la} et de {b} bpm {lb}",
        "On heart rate, the average was {a} bpm {la} and {b} bpm {lb}",
        "En cuanto a la frecuencia cardíaca, la FC media fue de {a} bpm {la} y de {b} bpm {lb}"),
    "hr_more": (", soit {gap} bpm de plus {l}.", ", {gap} bpm higher {l}.", ", es decir, {gap} bpm más {l}."),
    "hr_same": (", soit une FC moyenne identique.", ", i.e. identical.", ", es decir, una FC media idéntica."),
    "hr_max": (" FC max : {a} bpm contre {b} bpm.", " Max HR: {a} bpm versus {b} bpm.",
               " FC máx.: {a} bpm frente a {b} bpm."),
    "hr_why": (" Les données disponibles ne permettent pas d'isoler la cause de cet écart",
               " The available data do not isolate the cause of this gap",
               " Los datos disponibles no permiten aislar la causa de esta diferencia"),
    "hr_why_ctx": ((" ; les séances diffèrent aussi : {c}."), ("; the sessions also differ: {c}."),
                   ("; las sesiones también difieren: {c}.")),
    "hr_why_end": (" La chaleur, la fatigue ou la dérive cardiaque ne sont pas mesurées ici.",
                   " Heat, fatigue or cardiac drift are not measured here.",
                   " El calor, la fatiga o la deriva cardíaca no se miden aquí."),
    "pace_same": ("Ton allure moyenne est identique : {p}/km.", "Your average pace is identical: {p}/km.",
                  "Tu ritmo medio es idéntico: {p}/km."),
    "pace_win": (
        "C'est {w} que tu as couru le plus vite : {pw}/km contre {pl}/km, soit {gap} plus vite.",
        "You ran faster {w}: {pw}/km versus {pl}/km, {gap} faster.",
        "Corriste más rápido {w}: {pw}/km frente a {pl}/km, es decir, {gap} más rápido."),
    "pace_note": (
        " Les distances sont différentes, donc cet écart ne mesure pas à lui seul une différence de forme.",
        " The distances differ, so this gap alone does not measure a difference in fitness.",
        " Las distancias son distintas, así que esta diferencia no mide por sí sola una diferencia de forma."),
    "dem_one": (
        "Sur les indicateurs disponibles ({names}), c'est {l} que les valeurs sont les plus élevées.",
        "On the available indicators ({names}), the values are higher {l}.",
        "En los indicadores disponibles ({names}), los valores son más altos {l}."),
    "dem_mixed": (
        "Les indicateurs disponibles ne vont pas dans le même sens ({names}), donc je ne peux pas désigner "
        "la séance la plus exigeante.",
        "The available indicators do not agree ({names}), so I can't name the more demanding session.",
        "Los indicadores disponibles no van en el mismo sentido ({names}), así que no puedo señalar la "
        "sesión más exigente."),
    "dem_none": (
        "Je n'ai pas assez d'indicateurs comparables pour désigner la séance la plus exigeante.",
        "I don't have enough comparable indicators to name the more demanding session.",
        "No tengo suficientes indicadores comparables para señalar la sesión más exigente."),
    "dem_note": (
        " Ce n'est pas une mesure de difficulté physiologique : elle dépend aussi de l'objectif et de ton "
        "état du jour, que je ne connais pas ici.",
        " This is not a measure of physiological difficulty: it also depends on purpose and how you felt, "
        "which I don't have here.",
        " No es una medida de dificultad fisiológica: también depende del objetivo y de tu estado ese día, "
        "que aquí no conozco."),
    # history
    "h_long_unset": (
        "Je ne peux pas établir ce qu'est une sortie longue pour toi : il faut au moins {n} séances avec durée "
        "sur les {w} derniers jours avant celle-ci, et je n'en ai que {have}.",
        "I can't establish what a long run is for you: at least {n} timed sessions in the {w} days before this "
        "one are needed, and I have {have}.",
        "No puedo establecer qué es una salida larga para ti: hacen falta al menos {n} sesiones con duración "
        "en los {w} últimos días anteriores a esta, y solo tengo {have}."),
    "h_sim_unset": (
        "La distance de la séance de référence est absente : je ne peux pas chercher de séances similaires.",
        "The reference session has no distance: I can't look for similar sessions.",
        "Falta la distancia de la sesión de referencia: no puedo buscar sesiones similares."),
    "h_c_long": (
        "séances d'au moins {r} fois ta durée habituelle ({h} en médiane sur {w} jours), soit {t} ou plus",
        "sessions of at least {r} times your usual duration ({h} median over {w} days), i.e. {t} or more",
        "sesiones de al menos {r} veces tu duración habitual ({h} de mediana en {w} días), es decir, {t} o más"),
    "h_c_sim": (
        "distance de {lo} à {hi} km (±{p} % de la séance de référence)",
        "distance between {lo} and {hi} km (±{p}% of the reference session)",
        "distancia entre {lo} y {hi} km (±{p} % de la sesión de referencia)"),
    "h_c_recent": ("les sorties de course les plus récentes, sans autre critère",
                   "the most recent runs, with no other criterion",
                   "las salidas de carrera más recientes, sin otro criterio"),
    "h_none": (
        "Aucune séance antérieure ne correspond au critère ({c}) sur les {w} derniers jours.",
        "No earlier session matches the criterion ({c}) in the last {w} days.",
        "Ninguna sesión anterior cumple el criterio ({c}) en los últimos {w} días."),
    "h_head": ("Critère retenu : {c}. {n} {sessions} {kept}{of}, de la plus ancienne à la plus récente :",
               "Criterion: {c}. {n} {sessions} kept{of}, oldest to most recent:",
               "Criterio aplicado: {c}. {n} {sessions} {kept}{of}, de la más antigua a la más reciente:"),
    "h_session_one": ("séance", "session", "sesión"),
    "h_session_many": ("séances", "sessions", "sesiones"),
    "h_kept_one": ("retenue", "", "seleccionada"),
    "h_kept_many": ("retenues", "", "seleccionadas"),
    "h_of": (" sur {r} demandées", " out of {r} requested", " de {r} solicitadas"),
    "h_med_head": ("Par rapport à la médiane de ces séances : {g}", "Against the median of these sessions: {g}",
                   "Respecto a la mediana de estas sesiones: {g}"),
    "h_med_partial": (" (certaines mesures manquent pour une partie des séances).",
                      " (some measures are missing for part of the sessions).",
                      " (faltan algunas medidas en parte de las sesiones)."),
    "h_f_crit": ("Critère retenu : {c}.", "Criterion: {c}.", "Criterio aplicado: {c}."),
    "h_f_ref": ("{m} de la séance de référence ({d}) : {v}.", "{m} of the reference session ({d}): {v}.",
                "{m} de la sesión de referencia ({d}): {v}."),
    "h_f_ref_missing": (
        "{m} : non disponible pour la séance de référence ({d}), je ne peux donc pas la comparer.",
        "{m}: not available for the reference session ({d}), so I can't compare it.",
        "{m}: no disponible para la sesión de referencia ({d}), por lo que no puedo compararla."),
    "h_f_pop": ("Séances comparées ({n}/{total} avec cette mesure) : {vals}.",
                "Compared sessions ({n}/{total} with this measure): {vals}.",
                "Sesiones comparadas ({n}/{total} con esta medida): {vals}."),
    "h_f_pop_none": (
        "{m} : aucune des {total} séances comparées n'a cette mesure, je ne peux donc pas comparer.",
        "{m}: none of the {total} compared sessions has this measure, so I can't compare.",
        "{m}: ninguna de las {total} sesiones comparadas tiene esta medida, por lo que no puedo comparar."),
    "h_f_med": ("Médiane de ces {n} séances : {med} ; écart de la séance de référence : {gap}.",
                "Median of these {n} sessions: {med}; gap of the reference session: {gap}.",
                "Mediana de estas {n} sesiones: {med}; diferencia de la sesión de referencia: {gap}."),
    "h_same": ("identique", "identical", "idéntico"),
    "h_pace_same": ("allure identique", "same pace", "mismo ritmo"),
    "h_pace_slow": ("plus lente", "slower", "más lento"),
    "h_pace_fast": ("plus rapide", "faster", "más rápido"),
    "h_not_long": (
        "La séance de référence n'est pas elle-même une sortie longue selon ce critère, les séances ne sont "
        "donc pas directement comparables.",
        "The reference session is not itself a long run under this criterion, so the sessions are not "
        "directly comparable.",
        "La sesión de referencia no es en sí una salida larga según este criterio, por lo que las sesiones no "
        "son directamente comparables."),
    "h_descriptive": (
        "Cette comparaison est descriptive : elle ne démontre ni progression, ni changement de forme, de "
        "VO2max ou de récupération, car conditions et objectifs des séances peuvent différer.",
        "This comparison is descriptive: it does not show progress or a change in fitness, VO2max or "
        "recovery, as conditions and purposes may differ.",
        "Esta comparación es descriptiva: no demuestra ni progresión, ni cambio de forma, de VO2max o de "
        "recuperación, porque las condiciones y los objetivos de las sesiones pueden diferir."),
    # clarifications
    "c_multiple": (
        "J'ai trouvé plusieurs séances{when} : {listing}. Laquelle veux-tu ? Réponds par exemple « la 1 ».",
        "I found several sessions{when}: {listing}. Which one do you mean? For example, answer “1”.",
        "He encontrado varias sesiones{when}: {listing}. ¿Cuál quieres? Responde, por ejemplo, «la 1»."),
    "c_when": (" le {d}", " on {d}", " el {d}"),
    "c_none_day": (
        "Je ne trouve aucune course le {d} dans tes activités importées.",
        "I can't find any run on {d} in your imported activities.",
        "No encuentro ninguna carrera el {d} en tus actividades importadas."),
    "c_none": (
        "Je ne trouve aucune course correspondante dans tes activités importées.",
        "I can't find any run matching that in your imported activities.",
        "No encuentro ninguna carrera que coincida en tus actividades importadas."),
    "c_referent": (
        "De quelle séance parles-tu ? Donne-moi une date (par exemple « le 12 octobre ») ou « ma dernière "
        "sortie ».",
        "Which session do you mean? Give me a date (for example “October 12”) or “my last run”.",
        "¿De qué sesión hablas? Dame una fecha (por ejemplo «el 12 de octubre») o «mi última salida»."),
    "c_which_reference": (
        "Avec laquelle de ces séances veux-tu faire la comparaison ? Indique une date.",
        "Which of these sessions should be the reference? Please give a date.",
        "¿Con cuál de estas sesiones quieres hacer la comparación? Indica una fecha."),
    "c_invalid": (
        "Je n'ai pas identifié ton choix parmi ces séances. ",
        "I couldn't match your answer to one of these sessions. ",
        "No he podido identificar tu elección entre estas sesiones. "),
    "no_metric": (
        "Cette mesure n'est disponible pour aucune des deux séances, je ne peux donc pas la comparer.",
        "This measure is not available for either session, so I can't compare it.",
        "Esta medida no está disponible en ninguna de las dos sesiones, así que no puedo compararla."),
    "c_same": (
        "Une séance ne peut pas être comparée à elle-même. Indique une autre date.",
        "A session can't be compared with itself. Please give another date.",
        "Una sesión no puede compararse consigo misma. Indica otra fecha."),
}


def t(key: str, language: str, **kw) -> str:
    template = _T[key][LANGS.index(lang_of(language))]
    return template.format(**kw) if kw else template
