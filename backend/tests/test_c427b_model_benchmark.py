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
