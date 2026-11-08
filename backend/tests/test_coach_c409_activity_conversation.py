"""C409 — conversational activity references, comparisons and follow-ups (deterministic).

Dates in these fixtures: "today" is Sunday 2026-11-08.
"""

from datetime import date
from unittest.mock import AsyncMock, patch

import pytest

from test_coach_contract_unified import _Collection, _FakeDB, _analyze_environment, _trial_access, _free_access  # sets env first
import server
import coach_activity_conversation as cac
from test_coach_c393_fallback_quota import _post

pytestmark = pytest.mark.asyncio

TODAY = date(2026, 11, 8)


def _run(wid, start, km, minutes, pace_s, hr, user="user-a", **extra):
    doc = {
        "id": wid, "user_id": user, "type": "run", "name": "Course", "date": start, "distance_km": km,
        "duration_minutes": minutes, "avg_pace_min_km": (pace_s / 60.0) if pace_s else None,
        "avg_heart_rate": hr, "data_source": "manual",
    }
    doc.update(extra)
    return doc


def A():
    return _run("wA", "2026-10-12T07:30:00", 9.33, 68, 441, 127)


def B():
    return _run("wB", "2026-09-13T08:00:00", 21.27, 122, 343, 160)


def _history_runs():
    minutes = [40, 45, 50, 45, 42, 48, 100, 95, 105]
    runs = []
    for i, m in enumerate(minutes):
        runs.append(_run(f"h{i}", f"2026-07-{i + 1:02d}T08:00:00", round(m / 6.0, 2), m, 360, 140 + i))
    return runs


def _db(*workouts):
    db = _FakeDB()
    db.workouts._docs.extend(dict(w) for w in workouts)
    return db


async def _turn(db, message, memory=None, user="user-a", language="fr"):
    return await cac.resolve_turn(
        db=db, user_id=user, message=message, language=language, today=TODAY, memory=memory)


# ---------------------------------------------------------------- parsing and resolution

async def test_exact_date_resolves_the_real_activity_id():
    turn = await _turn(_db(A(), B()), "Analyse ma sortie du 12 octobre.")
    assert turn["kind"] == "single" and turn["workout_id"] == "wA"
    assert turn["refs"]["workout_ids"] == ["wA"] and turn["refs"]["primary"] == "wA"


@pytest.mark.parametrize("message,expected", [
    ("Et celle du 13/09 ?", "2026-09-13"),
    ("la sortie du 13-09-2026", "2026-09-13"),
    ("Montre-moi la sortie du 13 septembre 2026", "2026-09-13"),
    ("my run on October 12", "2026-10-12"),
    ("analyse 2026-10-12", "2026-10-12"),
    ("ma sortie de dimanche", "2026-11-08"),
    ("ma sortie d'hier", "2026-11-07"),
])
async def test_date_formats(message, expected):
    selectors = cac.parse_message(message, TODAY)["selectors"]
    assert selectors and selectors[0]["date"].isoformat() == expected


async def test_year_defaults_to_most_recent_past_occurrence():
    selectors = cac.parse_message("la sortie du 20 décembre", TODAY)["selectors"]
    assert selectors[0]["date"].isoformat() == "2025-12-20"


async def test_two_runs_the_same_day_keep_distinct_identities_and_ask():
    morning = _run("m1", "2026-10-12T07:30:00", 9.33, 68, 441, 127)
    evening = _run("m2", "2026-10-12T18:00:00", 5.0, 30, 360, 140)
    db = _db(morning, evening, B())
    turn = await _turn(db, "Analyse ma sortie du 12 octobre")
    assert turn["kind"] == "reply"
    assert "plusieurs séances" in turn["text"] and "07:30" in turn["text"] and "18:00" in turn["text"]
    choices = turn["refs"]["pending"]["choices"]
    assert [c["id"] for c in choices] == ["m1", "m2"]
    answer = await _turn(db, "la 2", memory=turn["refs"])
    assert answer["kind"] == "single" and answer["workout_id"] == "m2"


async def test_date_without_activity_says_so_and_invents_nothing():
    turn = await _turn(_db(A(), B()), "Analyse ma sortie du 3 octobre")
    assert turn["kind"] == "reply" and "aucune course" in turn["text"] and turn["refs"] is None


async def test_last_activity_is_chronological_not_last_analysed():
    memory = cac._refs("single", ["wB"], primary="wB")
    turn = await _turn(_db(A(), B()), "Analyse ma dernière sortie", memory=memory)
    assert turn["kind"] == "single" and turn["workout_id"] == "wA"


async def test_last_half_marathon_uses_distance_range():
    short = _run("s1", "2026-11-01T08:00:00", 5.0, 30, 360, 140)
    turn = await _turn(_db(short, A(), B()), "Analyse mon dernier semi")
    assert turn["kind"] == "single" and turn["workout_id"] == "wB"


async def test_run_by_distance_ambiguous_lists_real_candidates():
    other = _run("wC", "2026-08-02T08:00:00", 21.1, 125, 355, 158)
    turn = await _turn(_db(B(), other, A()), "Analyse ma sortie de 21 km")
    assert turn["kind"] == "reply" and [c["id"] for c in turn["refs"]["pending"]["choices"]] == ["wB", "wC"]


# ---------------------------------------------------------------- continuity

async def test_previous_turn_reference_is_resolved_from_stored_ids():
    memory = cac._refs("single", ["wA"], primary="wA")
    turn = await _turn(_db(A(), B()), "Compare-la à celle du 13 septembre", memory=memory)
    assert turn["kind"] == "compare"
    assert [a["id"] for a in turn["contract"]["activities"]] == ["wB", "wA"]
    assert turn["refs"]["kind"] == "pair" and turn["refs"]["workout_ids"] == ["wB", "wA"]


async def test_comparison_of_two_activities_is_exact():
    turn = await _turn(_db(A(), B()), "Compare ma sortie du 12 octobre avec celle du 13 septembre")
    text, contract = turn["text"], turn["contract"]
    assert contract["deltas"]["distance_km"] == {"gap": 11.94, "leader_id": "wB"}
    assert contract["deltas"]["pace_s_per_km"] == {"gap": 98, "leader_id": "wB"}
    assert contract["deltas"]["avg_hr"] == {"gap": 33, "leader_id": "wB"}
    assert contract["deltas"]["duration_min"] == {"gap": 54, "leader_id": "wB"}
    for fragment in ("21,27 km", "2h02", "5:43/km", "160 bpm", "9,33 km", "1h08", "7:21/km", "127 bpm",
                     "11,94 km", "1 min 38 s/km", "33 bpm", "54 min"):
        assert fragment in text, fragment
    assert text.index("13 septembre") < text.index("12 octobre")  # chronological order
    assert contract["activities"][0]["date"] == "2026-09-13"
    assert contract["distances_comparable"] is False
    assert "ne démontrent ni une progression" in text
    assert text.count("FC moyenne") == 3  # each measure said once per session + one gap, no repeated block


async def test_follow_up_on_hr_is_limited_to_hr_of_the_same_activities():
    memory = cac._refs("pair", ["wB", "wA"], primary="wA")
    turn = await _turn(_db(A(), B()), "Et au niveau du cardio ?", memory=memory)
    assert turn["kind"] == "compare"
    text = turn["text"]
    assert "160 bpm" in text and "127 bpm" in text and "33 bpm" in text
    assert "5:43" not in text and "km" not in text
    assert turn["refs"]["workout_ids"] == ["wB", "wA"]


async def test_why_hr_gives_no_unproven_cause():
    memory = cac._refs("pair", ["wB", "wA"], primary="wA")
    turn = await _turn(_db(A(), B()), "Pourquoi ma FC était-elle plus élevée ?", memory=memory)
    assert "ne permettent pas d'isoler la cause" in turn["text"]
    assert "pas mesurées" in turn["text"]


async def test_pace_question_names_the_faster_session():
    memory = cac._refs("pair", ["wB", "wA"], primary="wA")
    turn = await _turn(_db(A(), B()), "Sur laquelle ai-je couru le plus vite ?", memory=memory)
    assert "le 13 septembre que tu as couru le plus vite" in turn["text"]
    assert "5:43/km" in turn["text"] and "1 min 38 s/km" in turn["text"]


async def test_demanding_question_stays_cautious():
    memory = cac._refs("pair", ["wB", "wA"], primary="wA")
    turn = await _turn(_db(A(), B()), "Laquelle était la plus exigeante ?", memory=memory)
    assert "Ce n'est pas une mesure de difficulté physiologique" in turn["text"]


async def test_progress_is_refused_when_not_demonstrated():
    memory = cac._refs("pair", ["wB", "wA"], primary="wA")
    turn = await _turn(_db(A(), B()), "Est-ce que cela signifie que je progresse ?", memory=memory)
    assert turn["kind"] == "compare"
    assert "Je ne peux pas conclure que tu progresses" in turn["text"]
    assert "ne prouvent pas" in turn["text"]


async def test_explicit_subject_change_replaces_the_references():
    memory = cac._refs("pair", ["wB", "wA"], primary="wA")
    turn = await _turn(_db(A(), B()), "Et celle du 13 septembre ?", memory=memory)
    assert turn["kind"] == "single" and turn["workout_id"] == "wB"
    assert turn["refs"]["workout_ids"] == ["wB"]
    assert (await _turn(_db(A(), B()), "Parlons d'autre chose, quelle allure cible ?", memory=memory))["kind"] == "passthrough"


async def test_plan_questions_are_not_captured_by_a_pair_memory():
    memory = cac._refs("pair", ["wB", "wA"], primary="wA")
    assert (await _turn(_db(A(), B()), "Quelle est mon allure cible demain ?", memory=memory))["kind"] == "passthrough"
    assert (await _turn(_db(A(), B()), "Bonjour"))["kind"] == "passthrough"


async def test_ambiguous_referent_asks_instead_of_guessing():
    db = _db(A(), B())
    no_memory = await _turn(db, "Compare ces deux séances")
    assert no_memory["kind"] == "reply" and "De quelle séance" in no_memory["text"]
    pair = cac._refs("pair", ["wB", "wA"], primary="wA")
    which = await _turn(db, "Compare avec mes dernières sorties similaires", memory=pair)
    assert which["kind"] == "reply" and "Avec laquelle" in which["text"]
    resolved = await _turn(db, "celle du 13 septembre", memory=which["refs"])
    assert resolved["kind"] == "compare" and resolved["contract"]["kind"] == "history"
    assert resolved["contract"]["reference"]["id"] == "wB"


async def test_anaphora_after_a_non_activity_turn_is_not_guessed():
    turn = await _turn(_db(A(), B()), "Compare-la avec celle du 13 septembre", memory=None)
    assert turn["kind"] == "reply" and "De quelle séance" in turn["text"]


# ---------------------------------------------------------------- historical comparison

async def test_history_similar_uses_real_population_in_chronological_order():
    runs = [_run(f"s{i}", f"2026-08-{i + 1:02d}T08:00:00", km, 120, 350, 150 + i)
            for i, km in enumerate([20.0, 5.0, 22.5, 19.0, 21.0])]
    db = _db(B(), A(), *runs)
    memory = cac._refs("single", ["wB"], primary="wB")
    turn = await _turn(db, "Compare avec mes trois dernières sorties similaires", memory=memory)
    contract = turn["contract"]
    assert [f["id"] for f in contract["population"]] == ["s2", "s3", "s4"]  # 22.5, 19, 21; the 5 km is excluded
    assert contract["criterion"]["min_km"] == 14.89 and contract["criterion"]["max_km"] == 27.65
    assert "3 séances retenues" in turn["text"]
    assert turn["text"].index("3 août") < turn["text"].index("4 août") < turn["text"].index("5 août")
    assert "descriptive" in turn["text"] and "ne démontre ni progression" in turn["text"]


async def test_history_long_runs_reuse_the_established_v3_criterion_and_report_real_count():
    db = _db(B(), *_history_runs())
    memory = cac._refs("single", ["wB"], primary="wB")
    turn = await _turn(db, "Compare avec mes trois dernières sorties longues", memory=memory)
    contract = turn["contract"]
    assert contract["criterion"]["established"] is True and contract["criterion"]["ratio"] == 1.5
    assert [f["duration_min"] for f in contract["population"]] == [100, 95, 105]
    assert "3 séances retenues" in turn["text"]
    assert contract["reference_matches_criterion"] is True


async def test_history_long_runs_with_fewer_found_says_the_real_number():
    db = _db(B(), *_history_runs()[:8])  # only 2 long runs among 8
    memory = cac._refs("single", ["wB"], primary="wB")
    turn = await _turn(db, "Compare avec mes 3 dernières sorties longues", memory=memory)
    assert len(turn["contract"]["population"]) == 2
    assert "2 séances retenues sur 3 demandées" in turn["text"]


async def test_history_long_runs_not_established_without_enough_history():
    db = _db(B(), *_history_runs()[:3])
    memory = cac._refs("single", ["wB"], primary="wB")
    turn = await _turn(db, "Compare avec mes trois dernières sorties longues", memory=memory)
    assert turn["contract"]["criterion"]["established"] is False
    assert "Je ne peux pas établir ce qu'est une sortie longue" in turn["text"]
    assert turn["contract"]["population"] == []


# ---------------------------------------------------------------- missing data, isolation, safety

async def test_missing_metric_is_reported_not_invented():
    no_hr = _run("wA", "2026-10-12T07:30:00", 9.33, 68, 441, None)
    turn = await _turn(_db(no_hr, B()), "Compare ma sortie du 12 octobre avec celle du 13 septembre")
    assert "avg_hr" in turn["contract"]["missing"] and "avg_hr" not in turn["contract"]["deltas"]
    assert "Non disponible, donc non comparé : FC moyenne (12/10/2026)" in turn["text"]
    assert "33 bpm" not in turn["text"]
    follow = await _turn(_db(no_hr, B()), "Et le cardio ?", memory=cac._refs("pair", ["wB", "wA"]))
    assert "Non disponible" in follow["text"] and "bpm de plus" not in follow["text"]


async def test_zero_distance_and_missing_pace_stay_missing():
    facts = cac.activity_facts(_run("x", "2026-10-12T07:30:00", 0.0, 68, None, 127))
    assert facts["distance_km"] is None and facts["pace_s_per_km"] is None and facts["avg_hr"] == 127


async def test_strict_user_isolation():
    other = _run("wZ", "2026-10-12T07:00:00", 12.0, 70, 350, 150, user="user-b")
    db = _db(A(), B(), other)
    assert (await _turn(db, "Analyse ma sortie du 12 octobre", user="user-b"))["workout_id"] == "wZ"
    assert (await _turn(db, "Analyse ma sortie du 13 septembre", user="user-b"))["kind"] == "reply"
    assert await cac.load_activity_facts(db, "user-b", "wA") is None
    forged = cac._refs("pair", ["wA", "wB"], primary="wA")
    turn = await _turn(db, "Et le cardio ?", memory=forged, user="user-b")
    assert turn["kind"] == "reply" and "De quelle séance" in turn["text"]
    last = await _turn(db, "Analyse ma dernière sortie", user="user-b")
    assert last["workout_id"] == "wZ"


async def test_resolution_never_writes_and_never_syncs_garmin():
    db = _db(A(), B(), *_history_runs())
    writes = []
    originals = {}
    for name in ("insert_one", "update_one", "find_one_and_update", "delete_many"):
        originals[name] = getattr(_Collection, name, None)

        async def boom(self, *a, _n=name, **k):
            writes.append(_n)
        setattr(_Collection, name, boom)
    try:
        with patch("garmin.service._ingest_activities", AsyncMock(side_effect=AssertionError("sync"))):
            await _turn(db, "Compare ma sortie du 12 octobre avec celle du 13 septembre")
            await _turn(db, "Compare avec mes trois dernières sorties longues",
                        memory=cac._refs("single", ["wB"], primary="wB"))
    finally:
        for name, original in originals.items():
            if original is None:
                delattr(_Collection, name)
            else:
                setattr(_Collection, name, original)
    assert writes == []
    source = open(cac.__file__, encoding="utf-8").read()
    assert "garmin.service" not in source and "providers" not in source


async def test_queries_are_bounded_and_field_limited():
    db = _db(A(), B())
    seen = []
    original = _Collection.find

    def spy(self, query=None, projection=None):
        seen.append((query, projection))
        return original(self, query, projection)

    with patch.object(_Collection, "find", spy):
        await _turn(db, "Analyse ma dernière sortie")
        await _turn(db, "Analyse ma sortie du 12 octobre")
    assert seen and all(q.get("user_id") == "user-a" and p and p.get("_id") == 0 for q, p in seen)


# ---------------------------------------------------------------- full Coach path (stubbed model)

def _server_env(db, access=_trial_access):
    return _analyze_environment(db, access)


async def test_full_conversation_path_memory_and_no_model_call_for_comparisons():
    db = _db(A(), B())
    narrative_loader = AsyncMock(return_value=(None, None))
    with (
        _server_env(db),
        patch("coach_activity_conversation.today_for", return_value=TODAY),
        patch("server.load_scoped_workout_analysis_v2",
              AsyncMock(side_effect=lambda **kw: ({"id": kw["workout_id"], "user_id": kw["user_id"]}, object()))) as scoped,
        patch("server.load_scoped_workout_coach_evidence", narrative_loader),
    ):
        llm = server.llm_coach.enrich_chat_response
        r1 = await _post({"message": "Analyse ma sortie du 12 octobre.", "language": "fr"})
        assert r1.status_code in (200, 503)
        scoped.assert_awaited_once()
        assert scoped.await_args.kwargs["workout_id"] == "wA"
        # Turn 1 stored with its reference so the next turns can use it (when the model path answered).
        calls_after_1 = llm.await_count
        db.conversations._docs.append({
            "id": "seed", "user_id": "user-a", "role": "assistant", "content": "x", "workout_id": None,
            "timestamp": __import__("datetime").datetime.now(__import__("datetime").timezone.utc).isoformat(), "coach_refs": cac._refs("single", ["wA"], primary="wA"),
        })
        r2 = await _post({"message": "Compare-la à celle du 13 septembre.", "language": "fr"})
        r3 = await _post({"message": "Et au niveau du cardio ?", "language": "fr"})
        r4 = await _post({"message": "Est-ce que je progresse ?", "language": "fr"})
    assert r2.status_code == r3.status_code == r4.status_code == 200
    assert llm.await_count == calls_after_1  # comparisons and follow-ups are answered from the contract
    assert "21,27 km" in r2.json()["response"] and "11,94 km" in r2.json()["response"]
    assert "160 bpm" in r3.json()["response"] and "33 bpm" in r3.json()["response"]
    assert "Je ne peux pas conclure que tu progresses" in r4.json()["response"]
    assistants = [d for d in db.conversations._docs if d["role"] == "assistant" and d["id"] != "seed"]
    assert [d["coach_refs"]["workout_ids"] for d in assistants[-3:]] == [["wB", "wA"]] * 3
    assert all(d["workout_id"] is None for d in db.conversations._docs)
    assert r2.json()["verification"]["response_source"] == "c409_comparison_contract"


async def test_free_tier_gets_the_workout_restriction_for_activity_questions():
    db = _db(A(), B())
    with _server_env(db, _free_access), patch("coach_activity_conversation.today_for", return_value=TODAY):
        response = await _post({"message": "Compare ma sortie du 12 octobre avec celle du 13 septembre", "language": "fr"})
        general = await _post({"message": "Bonjour", "language": "fr"})
    assert response.status_code == 200 and "essai actif ou Premium" in response.json()["response"]
    assert general.status_code == 200 and "essai actif" not in general.json()["response"]


async def test_ordinary_chat_and_explicit_workout_path_are_unchanged():
    db = _db(A(), B())
    with _server_env(db), patch("coach_activity_conversation.today_for", return_value=TODAY):
        response = await _post({"message": "Bonjour coach", "language": "fr"})
        assert response.status_code == 200
        assert server.llm_coach.enrich_chat_response.await_count == 1
        assert all("coach_refs" not in d for d in db.conversations._docs)


async def test_english_rendering_is_complete():
    db = _db(A(), B(), *_history_runs())
    pair = await _turn(db, "Compare my run on October 12 with the one on September 13", language="en")
    assert "11.94 km" in pair["text"] and "1 min 38 s/km" in pair["text"] and "33 bpm" in pair["text"]
    memory = cac._refs("pair", ["wB", "wA"], primary="wA")
    for message in ("What about heart rate?", "Which one was harder?", "Am I improving?"):
        turn = await _turn(db, message, memory=memory, language="en")
        assert turn["kind"] == "compare" and turn["text"]
    history = await _turn(db, "Compare with my last three long runs", memory=cac._refs("single", ["wB"]), language="en")
    assert "3 sessions kept" in history["text"]


@pytest.mark.parametrize("message", ["after-clear-7-1", "10-20 km facile", "rendez-vous à 7:21", "j'ai couru 5.2 km"])
async def test_ordinary_text_is_not_mistaken_for_a_date(message):
    assert not [s for s in cac.parse_message(message, TODAY)["selectors"] if s["type"] == "date"]
