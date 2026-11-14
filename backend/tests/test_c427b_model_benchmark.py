"""C427B benchmark tests: offline only, no OpenAI call, no MongoDB."""

import asyncio
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from benchmarks import coach_model_benchmark as bench
from benchmarks import export_coach_contexts as export

PRICES = {
    "gpt-6-luna": bench.Price(1.0, 0.5, 4.0),
    "gpt-4.1": bench.Price(2.0, 0.5, 8.0),
}
CONTEXTS = {"s0511": {"k": 1}, "s0311": {"k": 2}, "comparison": {"k": 3}}


class FakeCaller:
    def __init__(self, fail_model=None, no_usage=False):
        self.current = None
        self.calls = []
        self.fail_model, self.no_usage = fail_model, no_usage

    def set_model(self, model):
        self.current = model

    async def __call__(self, *, user_message, context, conversation_history, user_id):
        self.calls.append((self.current, user_message, list(conversation_history), user_id))
        if self.current == self.fail_model:
            return None, False, {"error": "timeout", "duration_sec": 30.0}
        meta = {"duration_sec": 1.5, "success": True}
        if not self.no_usage:
            meta.update(input_tokens=1000, cached_input_tokens=0, output_tokens=200)
        return f"answer from {self.current}", True, meta


def run(caller, **overrides):
    params = dict(contexts=CONTEXTS, models=list(PRICES), prices=PRICES, repetitions=3,
                  budget=bench.BudgetGuard(1.0, 200), max_output_tokens=2000,
                  caller=caller, set_model=caller.set_model)
    params.update(overrides)
    return asyncio.run(bench.run_benchmark(**params))


def test_percentile_and_summary():
    assert bench.percentile_nearest_rank([1, 2, 3, 4, 5], 95) == 5
    assert bench.summarize([])["median"] is None
    assert bench.summarize([3, 1, 2])["median"] == 2


def test_model_order_alternates_and_inputs_identical():
    caller = FakeCaller()
    records, _ = run(caller)
    s3 = [r for r in records if r.scenario == "S3_analysis_0311"]
    first_models = [next(r.model for r in s3 if r.repetition == rep) for rep in range(3)]
    assert len(set(first_models)) == 2
    by_model = {}
    for model, message, history, user in caller.calls:
        assert user == "benchmark"
        by_model.setdefault(message, set()).add(model)
    assert all(models == set(PRICES) for models in by_model.values())


def test_chained_followups_use_same_models_own_answer():
    caller = FakeCaller()
    run(caller, repetitions=1)
    for model, message, history, _ in caller.calls:
        if message == "Qu'est-ce que je dois retenir surtout ?":
            assert history[-1] == {"role": "assistant", "content": f"answer from {model}"}


def test_failed_chain_is_not_continued_and_cost_is_computed():
    caller = FakeCaller(fail_model="gpt-4.1")
    records, _ = run(caller, repetitions=1)
    assert not [r for r in records if r.model == "gpt-4.1" and r.scenario == "S2_retain_0511" and r.turn == 1]
    luna = next(r for r in records if r.model == "gpt-6-luna")
    assert luna.cost_usd == pytest.approx((1000 * 1.0 + 200 * 4.0) / 1e6)


def test_missing_context_is_skipped_not_invented():
    caller = FakeCaller()
    records, notes = run(caller, contexts={"s0311": {"k": 2}}, repetitions=1)
    assert {r.scenario for r in records} == {"S3_analysis_0311", "S4_improve_0311", "S6_heart_rate",
                                             "S7_followup", "S8_missing_data"}
    assert any("S1_accel_0511" in n for n in notes) and any("S5_compare" in n for n in notes)


def test_budget_ceiling_and_call_cap_stop_the_run():
    caller = FakeCaller()
    records, notes = run(caller, budget=bench.BudgetGuard(1.0, 5))
    assert len(records) == 5 and any("max_calls_reached" in n for n in notes)
    records, notes = run(FakeCaller(), budget=bench.BudgetGuard(0.0005, 100))
    assert records == [] and any("budget_ceiling" in n for n in notes)


def test_missing_usage_stops_run():
    records, notes = run(FakeCaller(no_usage=True))
    assert len(records) == 1 and any("usage_untrackable" in n for n in notes)


def test_live_requires_authorisation(monkeypatch):
    args = bench.parse_args(["--fixtures", "/x", "--out-dir", "/y", "--live"])
    monkeypatch.delenv(bench.AUTH_ENV_VAR, raising=False)
    with pytest.raises(SystemExit) as exc:
        bench.check_live_authorization(args, "")
    message = str(exc.value)
    assert "OPENAI_API_KEY" in message and "authorisation" in message and "remaining-budget" in message
    ok = bench.parse_args(["--fixtures", "/x", "--out-dir", "/y", "--live", "--i-authorize-paid-calls",
                           "--remaining-budget-usd", "10", "--budget-usd", "1"])
    monkeypatch.setenv(bench.AUTH_ENV_VAR, "yes")
    bench.check_live_authorization(ok, "k")
    ok.budget_usd = 2.0
    with pytest.raises(SystemExit):
        bench.check_live_authorization(ok, "k")


def test_dry_run_makes_no_call_and_rejects_repo_paths(tmp_path, capsys):
    fixtures = tmp_path / "f.json"
    fixtures.write_text(json.dumps({"contexts": CONTEXTS}))
    assert bench.main(["--fixtures", str(fixtures), "--out-dir", str(tmp_path / "o")]) == 0
    assert "Dry run" in capsys.readouterr().out
    with pytest.raises(SystemExit):
        bench.main(["--fixtures", str(bench.REPO_ROOT / "f.json"), "--out-dir", str(tmp_path)])


def test_report_has_no_responses_and_blind_files_hide_models(tmp_path):
    records, _ = run(FakeCaller(), repetitions=1)
    stats = {m: bench.model_stats(records, m) for m in PRICES}
    econ = {m: bench.economics(stats[m]["cost_usd_per_response_mean"], 0.9) for m in PRICES}
    report = bench.render_report(stats, econ, {"mode": "test", "spent_usd": 0, "calls": len(records),
                                               "stop_reason": None})
    assert "answer from" not in report and "à évaluer" in report
    assert econ["gpt-6-luna"]["usd_1000_subscribers_month"] == pytest.approx(
        stats["gpt-6-luna"]["cost_usd_per_response_mean"] * 30 * 1000, rel=1e-3)
    bench.write_blind_files(tmp_path, records, seed=1)
    blind = json.loads((tmp_path / "responses_blind_private.json").read_text())
    assert all(set(item) == {"item", "label", "response"} for item in blind)
    assert json.loads((tmp_path / "blind_key_private.json").read_text())


def test_anonymizer_drops_identity_and_aliases_ids():
    pseudo = export.Pseudonymizer()
    wid = "123e4567-e89b-12d3-a456-426614174000"
    raw = {"email": "a@b.fr", "workout_id": wid, "name": "Run Paris", "pace": "5:10",
           "history": [{"id": wid, "note": f"see {wid}"}], "latitude": 1.0}
    clean = export.anonymize(raw, pseudo)
    assert clean == {"workout_id": "w1", "pace": "5:10", "history": [{"id": "w1", "note": "see w1"}]}
    export.assert_no_leaks(clean)


def test_leak_scan_fails_closed():
    for bad in ({"t": "mail me at x@y.com"}, {"t": "https://connect.garmin.com/x"},
                {"t": "123e4567-e89b-12d3-a456-426614174000"}, {"t": "sk-abcdefghijklmnopqrstu"}):
        with pytest.raises(export.AnonymizationError):
            export.assert_no_leaks(bad)


def test_identity_check_and_workout_parsing():
    assert export.identity_matches({"email": "A@b.fr"}, " a@B.fr ")
    assert not export.identity_matches({"email": "a@b.fr"}, "c@d.fr")
    assert not export.identity_matches(None, "a@b.fr")
    assert export.parse_workouts(["s0511=abc"]) == {"s0511": "abc"}
    with pytest.raises(SystemExit):
        export.parse_workouts(["other=abc"])


# ---------------------------------------------------------------- C427B corrections: call count

FULL = {"s0511": {"k": 1}, "s0311": {"k": 2}, "comparison": {"k": 3}}
MODELS = list(PRICES)


def full_run(caller, repetitions, max_calls=None, **kw):
    planned = bench.planned_calls(bench.SCENARIOS, 2, repetitions)
    budget = bench.BudgetGuard(1.0, max_calls or planned)
    records, notes = run(caller, contexts=FULL, repetitions=repetitions, budget=budget, **kw)
    return planned, records, notes, budget


def test_eight_scenarios_are_twelve_turns():
    assert bench.total_turns(list(bench.SCENARIOS)) == 12
    assert [bench.planned_calls(list(bench.SCENARIOS), 2, r) for r in (1, 2, 3)] == [24, 48, 72]


@pytest.mark.parametrize("repetitions,expected", [(1, 24), (2, 48), (3, 72)])
def test_campaign_completes_with_equal_calls_per_model(repetitions, expected):
    caller = FakeCaller()
    planned, records, notes, budget = full_run(caller, repetitions)
    assert planned == expected == len(records) == len(caller.calls) == budget.calls
    status = bench.campaign_status(records, MODELS, planned, [], budget.stop_reason)
    assert status["complete"] and status["balanced"]
    assert status["per_model"] == {m: expected // 2 for m in MODELS}


def test_cap_below_plan_is_refused_before_any_call():
    scenarios = list(bench.SCENARIOS)
    with pytest.raises(ValueError, match="72 calls.*--max-calls is 60.*max 2 fits"):
        bench.validate_campaign(models=MODELS, repetitions=3, max_calls=60, scenarios=scenarios)
    assert bench.validate_campaign(models=MODELS, repetitions=2, max_calls=60, scenarios=scenarios) == 48
    assert bench.validate_campaign(models=MODELS, repetitions=3, max_calls=72, scenarios=scenarios) == 72
    with pytest.raises(ValueError):
        bench.validate_campaign(models=MODELS, repetitions=1, max_calls=24, scenarios=scenarios[:3])
    with pytest.raises(ValueError):
        bench.validate_campaign(models=["a", "a"], repetitions=1, max_calls=99, scenarios=scenarios)
    with pytest.raises(ValueError):
        bench.validate_campaign(models=["a", "b", "c"], repetitions=1, max_calls=99, scenarios=scenarios)


def test_main_refuses_underbudgeted_live_campaign(tmp_path, monkeypatch):
    fixtures = tmp_path / "f.json"
    fixtures.write_text(json.dumps({"contexts": FULL}))
    monkeypatch.setenv("OPENAI_API_KEY", "x")
    argv = ["--fixtures", str(fixtures), "--out-dir", str(tmp_path / "o"), "--live", "--max-calls", "60",
            "--price", "gpt-6-luna=1,0.5,4", "--price", "gpt-4.1=2,0.5,8"]
    with pytest.raises(SystemExit) as exc:
        bench.main(argv)
    assert "Refused before any call" in str(exc.value) and "72" in str(exc.value)
    dry = ["--fixtures", str(fixtures), "--out-dir", str(tmp_path / "o")]
    assert bench.main(dry + ["--max-calls", "72"]) == 0  # dry run, 72 accepted
    assert bench.main(dry) == 0  # default cap = planned campaign


@pytest.mark.parametrize("stop_after", [1, 25, 71])
def test_interrupted_campaign_is_never_complete(stop_after):
    class Crashing(FakeCaller):
        async def __call__(self, **kw):
            if len(self.calls) >= stop_after:
                raise RuntimeError("boom")
            return await super().__call__(**kw)

    caller = Crashing()
    planned, records, notes, budget = full_run(caller, 3)
    status = bench.campaign_status(records, MODELS, planned, [], budget.stop_reason)
    assert len(records) == stop_after and not status["complete"]
    assert budget.stop_reason == "usage_untrackable" and any("interrupted" in n for n in notes)
    report = bench.render_report({m: bench.model_stats(records, m) for m in MODELS},
                                 {m: {} for m in MODELS},
                                 {"mode": "t", "spent_usd": budget.spent, "calls": budget.calls,
                                  "stop_reason": budget.stop_reason, "status": status})
    assert "INCOMPLETE" in report and "STATUS: COMPLETE" not in report


def test_cancellation_returns_partial_and_unbalanced_status():
    class Cancelled(FakeCaller):
        async def __call__(self, **kw):
            if len(self.calls) >= 3:
                raise asyncio.CancelledError()
            return await super().__call__(**kw)

    planned, records, _, budget = full_run(Cancelled(), 1)
    status = bench.campaign_status(records, MODELS, planned, [], budget.stop_reason)
    assert len(records) == 3 and not status["balanced"] and not status["complete"]


def test_failed_call_makes_campaign_incomplete():
    planned, records, notes, budget = full_run(FakeCaller(fail_model="gpt-4.1"), 1)
    assert not bench.campaign_status(records, MODELS, planned, [], budget.stop_reason)["complete"]


# ---------------------------------------------------------------- C427B corrections: budget safety

@pytest.mark.parametrize("spec", [
    "m=nan,1,1", "m=1,inf,1", "m=1,1,-inf", "m=-1,0,1", "m=1,0,-4", "m=0,0,1", "m=1,0,0",
    "m=1,2,3", "m=1e9,0,1", "m=1,1", "=1,1,1", "m=a,b,c", "m=true,1,1",
])
def test_invalid_prices_are_rejected(spec):
    with pytest.raises(ValueError):
        bench.parse_price(spec)


def test_prices_required_for_each_model_and_not_duplicated():
    assert set(bench.parse_prices(["a=1,0.5,2", "b=1,0,2"], ["a", "b"])) == {"a", "b"}
    with pytest.raises(ValueError, match="no verified"):
        bench.parse_prices(["a=1,0.5,2"], ["a", "b"])
    with pytest.raises(ValueError, match="duplicate"):
        bench.parse_prices(["a=1,0.5,2", "a=1,0.5,2"], ["a"])


@pytest.mark.parametrize("flag", ["--budget-usd", "--remaining-budget-usd", "--eur-per-usd"])
@pytest.mark.parametrize("value", ["nan", "inf", "-1"])
def test_invalid_numeric_flags_rejected(flag, value):
    with pytest.raises(SystemExit):
        bench.parse_args(["--fixtures", "/x", "--out-dir", "/y", flag, value])


@pytest.mark.parametrize("ceiling", [0, -1, float("nan"), float("inf"), 1.01])
def test_budget_guard_rejects_invalid_or_oversized_ceiling(ceiling):
    with pytest.raises(ValueError):
        bench.BudgetGuard(ceiling, 10)
    with pytest.raises(ValueError):
        bench.BudgetGuard(1.0, 0)


def test_cost_validation():
    price = PRICES["gpt-4.1"]
    for bad in ((-1, 0, 5), (10, 11, 5), (10, 0, -1), (1.5, 0, 1), (True, 0, 1)):
        assert not bench.valid_usage(*bad)
        with pytest.raises(ValueError):
            bench.cost_usd(price, *bad)
    assert bench.cost_usd(price, 1000, 400, 100) == pytest.approx((600 * 2 + 400 * 0.5 + 100 * 8) / 1e6)


def test_worst_case_is_conservative_for_multibyte_text_and_inflated():
    price = PRICES["gpt-4.1"]
    text = "é" * 1000
    worst = bench.worst_case_call_cost(price, len(text.encode()), 2000)
    # every token >= 1 byte, so input tokens <= bytes; output at the cap; margin applied
    assert worst >= bench.cost_usd(price, len(text.encode()), 0, 2000)
    assert worst == pytest.approx(
        bench.cost_usd(price, len(text.encode()) + bench.PROMPT_WRAPPER_TOKENS, 0, 2000) * bench.WORST_CASE_MARGIN)


def test_cumulative_counter_and_ceiling_never_exceeded():
    caller = FakeCaller()
    big = {m: bench.Price(300.0, 100.0, 600.0) for m in PRICES}  # ~0.42 USD per call
    budget = bench.BudgetGuard(1.0, 72)
    records, notes = run(caller, contexts=FULL, prices=big, repetitions=3, budget=budget)
    assert budget.spent <= 1.0 and len(records) < 72
    assert budget.stop_reason in {"budget_ceiling_would_be_exceeded", "budget_ceiling_reached"}
    assert budget.spent == pytest.approx(sum(r.cost_usd for r in records))
    assert any("stopped" in n for n in notes)


@pytest.mark.parametrize("meta", [
    {"duration_sec": 1.0},
    {"input_tokens": 100, "cached_input_tokens": 200, "output_tokens": 5},
    {"input_tokens": -5, "cached_input_tokens": 0, "output_tokens": 5},
    {"input_tokens": "x", "cached_input_tokens": 0, "output_tokens": 5},
    {"input_tokens": 100, "cached_input_tokens": 0, "output_tokens": float("nan")},
])
def test_missing_or_invalid_usage_stops_and_charges_worst_case(meta):
    async def caller(**kw):
        return "ok", True, dict(meta)

    budget = bench.BudgetGuard(1.0, 72)
    records, notes = asyncio.run(bench.run_benchmark(
        contexts=FULL, models=MODELS, prices=PRICES, repetitions=1, budget=budget, max_output_tokens=2000,
        caller=caller, set_model=lambda m: None))
    assert len(records) == 1 and records[0].cost_usd is None and records[0].input_tokens is None
    assert budget.stop_reason == "usage_untrackable" and budget.spent > 0
    assert any("usage_untrackable" in n for n in notes)


def test_api_error_without_usage_stops_campaign_as_unmeasurable():
    async def caller(**kw):
        return None, False, {"error": "rate_limited", "duration_sec": 0.2}

    budget = bench.BudgetGuard(1.0, 72)
    records, _ = asyncio.run(bench.run_benchmark(
        contexts=FULL, models=MODELS, prices=PRICES, repetitions=1, budget=budget, max_output_tokens=2000,
        caller=caller, set_model=lambda m: None))
    assert len(records) == 1 and not records[0].success and records[0].error == "rate_limited"
    assert budget.stop_reason == "usage_untrackable"


def test_api_error_with_usage_is_billed_and_counted():
    class Erroring(FakeCaller):
        async def __call__(self, **kw):
            text, ok, meta = await super().__call__(**kw)
            return (None, False, {**meta, "error": "empty_response"}) if self.current == "gpt-4.1" else (text, ok, meta)

    planned, records, _, budget = full_run(Erroring(), 1)
    errored = [r for r in records if r.model == "gpt-4.1"]
    assert errored and all(r.cost_usd is not None and not r.success for r in errored)
    assert budget.spent == pytest.approx(sum(r.cost_usd for r in records))


# ---------------------------------------------------------------- C427B corrections: anonymisation

GARMIN_ID = 12345678901
SHORT_ID = "132"


def sport_context():
    return {
        "workout_id": GARMIN_ID,
        "activity_id": str(GARMIN_ID),
        "date": "2026-11-05",
        "distance_km": 9.64,
        "duration": "52:14",
        "paces": ["5:01/km", "4:45/km", "5:10/km"],
        "summary": f"Séance {GARMIN_ID} : 4 accélérations à 4:45/km, FC 132 puis 148 bpm sur 9.64 km le 05/11/2026.",
        "avg_hr": 132, "max_hr": "148 bpm", "reps": 4, "laps": [{"lap_id": 3, "hr": 148, "pace": "4:45/km"}],
        "comparison": {"other_workout_id": 98765432109, "text": f"vs {98765432109} et {GARMIN_ID}",
                       "delta": "-0:16/km"},
    }


def test_numeric_garmin_ids_replaced_only_as_whole_identifiers():
    pseudo = export.Pseudonymizer()
    raw = sport_context()
    clean = export.anonymize(raw, pseudo)
    assert clean["workout_id"] == clean["activity_id"] == "w1"
    assert clean["comparison"]["other_workout_id"] == "w2"
    assert clean["summary"] == "Séance w1 : 4 accélérations à 4:45/km, FC 132 puis 148 bpm sur 9.64 km le 05/11/2026."
    assert clean["comparison"]["text"] == "vs w2 et w1"  # cross-references stay consistent
    assert clean["laps"] == [{"lap_id": 3, "hr": 148, "pace": "4:45/km"}]  # small index untouched
    for untouched in ("date", "distance_km", "duration", "paces", "avg_hr", "max_hr", "reps"):
        assert clean[untouched] == raw[untouched]
    export.verify_sport_data_preserved(raw, clean, pseudo)
    export.assert_no_leaks(clean)


def test_short_numeric_values_equal_to_an_id_fragment_are_never_substituted():
    pseudo = export.Pseudonymizer()
    raw = {"workout_id": 13212345,  # contains 132 as a prefix, 2345 inside...
           "text": "FC 132, 148 bpm, 5:01/km, 4:45/km, 13212345 mètres? non: id 13212345.",
           "pace": "5:01/km", "date": "2026-11-03", "distance": "5.79 km", "t": "0:13:21"}
    clean = export.anonymize(raw, pseudo)
    assert clean["text"] == "FC 132, 148 bpm, 5:01/km, 4:45/km, w1 mètres? non: id w1."
    assert (clean["pace"], clean["date"], clean["distance"], clean["t"]) == (
        "5:01/km", "2026-11-03", "5.79 km", "0:13:21")


def test_id_embedded_in_a_longer_number_or_pace_is_not_replaced():
    pseudo = export.Pseudonymizer()
    raw = {"workout_id": 12345678, "text": "ref 912345678 et 12345678.5 et 5:12345678 et x12345678 et 12345678"}
    clean = export.anonymize(raw, pseudo)
    assert clean["text"] == "ref 912345678 et 12345678.5 et 5:12345678 et x12345678 et w1"
    with pytest.raises(export.AnonymizationError):  # the leftover 9-digit run is doubt -> export fails
        export.assert_no_leaks(clean)


def test_ambiguous_identifier_under_id_key_fails_instead_of_guessing():
    for bad in ({"workout_id": "abc-123"}, {"activity_id": 3.5}, {"id": "W-77x"}, {"session_id": ["ok1", 5]}):
        with pytest.raises(export.AnonymizationError):
            export.anonymize(bad)
    assert export.anonymize({"lap_id": 2, "id": None}) == {"lap_id": 2, "id": None}


def test_identifier_appearing_in_text_before_its_id_key_is_still_replaced():
    raw = {"summary": f"voir {GARMIN_ID}", "later": {"workout_id": GARMIN_ID}}
    assert export.anonymize(raw) == {"summary": "voir w1", "later": {"workout_id": "w1"}}


def test_identity_secrets_and_coordinates_removed_and_unknown_leaks_fail():
    raw = {"email": "a@b.fr", "access_token": "t", "refresh_token": "r", "polyline": "abc", "lat": 1.5,
           "start_location": "Paris", "api_key": "k", "pace": "5:01/km"}
    assert export.anonymize(raw) == {"pace": "5:01/km"}
    for bad in ({"t": "48.856614, 2.352222"}, {"t": "contact www.example.com"}, {"t": "id 1731234567890"}):
        with pytest.raises(export.AnonymizationError):
            export.assert_no_leaks(bad)
    export.assert_no_leaks({"t": "5:01/km 4:45/km 132 148 bpm 9.64 km 2026-11-05 52:14 4x1000 m"})


def test_verification_gate_detects_altered_sport_values():
    pseudo = export.Pseudonymizer()
    raw = sport_context()
    clean = export.anonymize(raw, pseudo)
    clean["paces"] = ["5:02/km", "4:45/km", "5:10/km"]
    with pytest.raises(export.AnonymizationError):
        export.verify_sport_data_preserved(raw, clean, pseudo)
    clean = export.anonymize(raw, pseudo)
    clean["avg_hr"] = 133
    with pytest.raises(export.AnonymizationError):
        export.verify_sport_data_preserved(raw, clean, pseudo)
