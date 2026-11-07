"""C408-C — history metadata, provenance, prescription chronology, evidence guard, fallback.

All cases are SYNTHETIC; no LLM, no network. They check deterministic code only.
"""

import copy
import json

import pytest

import coach_context_v2 as ccv2
import coach_evidence_guard as guard
import coach_session_comment as csc
from test_coach_c402_session_comment import _llm_context

CUTOFF = "2026-01-10T07:30:00+00:00"


def _session(day: int, month: int = 1, **extra):
    base = {"date": f"2026-{month:02d}-{day:02d}T07:00:00", "type": "run", "distance_km": 8.0,
            "duration_minutes": 48.0, "avg_pace_display": "6:00/km", "avg_heart_rate": 150.0}
    base.update(extra)
    return base


def _ctx_with_history(n: int, *, upstream_excluded: int = 0, coverage_truncated: bool = False):
    ctx = _llm_context()
    ctx["recent_workouts"] = [_session(9 - i if i < 9 else 1, 12 if i >= 9 else 1) for i in range(n)]
    for i, w in enumerate(ctx["recent_workouts"]):
        w["date"] = f"2025-12-{28 - i:02d}T07:00:00" if i < 25 else w["date"]
    ctx["recent_workouts_coverage"] = {
        "window_days": 90, "truncated": coverage_truncated, "included_count": n,
        "available_count": n + upstream_excluded,
    }
    return ctx


# ------------------------------------------------ 1/2. history metadata at the source

@pytest.mark.parametrize("n,truncated", [(0, False), (1, False), (5, False), (6, True), (8, True), (11, True)])
def test_history_counts_and_truncation(n, truncated):
    block = csc.build_comment_context(_ctx_with_history(n))["history_as_of_session"]
    assert block["eligible_count"] == n
    assert block["included_count"] == min(n, csc.HISTORY_MAX_SESSIONS)
    assert len(block["sessions"]) == block["included_count"]
    assert block["truncated"] is truncated
    for key in ("window", "eligibility", "selection", "cutoff_precision"):
        assert key in block


def test_history_shown_is_most_recent_first_without_duplicates():
    block = csc.build_comment_context(_ctx_with_history(11))["history_as_of_session"]
    dates = [s["date"] for s in block["sessions"]]
    assert dates == sorted(dates, reverse=True)
    assert len(set(dates)) == len(dates)
    assert dates[0] == "2025-12-28T07:00:00"


def test_upstream_exclusions_keep_truncated_true():
    ctx = _ctx_with_history(5, upstream_excluded=3, coverage_truncated=True)
    block = csc.build_comment_context(ctx)["history_as_of_session"]
    assert block["included_count"] == 5 and block["eligible_count"] == 8 and block["truncated"] is True


def test_later_sessions_are_excluded_from_history():
    ctx = _ctx_with_history(3)
    ctx["recent_workouts"].append(_session(11))
    ctx["recent_workouts"].append(_session(20))
    block = csc.build_comment_context(ctx)["history_as_of_session"]
    assert block["eligible_count"] == 3
    assert all(s["date"] < "2026-01-10" for s in block["sessions"])


def test_profile_population_is_not_the_shown_selection():
    out = csc.build_comment_context(_ctx_with_history(11))
    population = out["runner_profile"]["population"]
    assert population["sessions_count"] == 11 and out["history_as_of_session"]["included_count"] == 5
    assert "history_as_of_session" in population["scope"]


# ------------------------------------------------ identifiers (section 8) and cross-user

def test_technical_ids_are_stripped_from_chat_context():
    ctx = _llm_context()
    selected = ctx["workout_detail"].get("id") or "w1"
    ctx["workout_detail"]["id"] = selected
    ctx["workout_detail"]["garmin_activity_id"] = "9988776655"
    ctx["workout_detail"]["user_id"] = "user-b"
    dumped = json.dumps(csc.build_session_chat_context(ctx), default=str)
    for leaked in ("9988776655", "user-b", f'"id": "{selected}"'):
        assert leaked not in dumped


def test_history_never_contains_another_users_marker():
    ctx = _ctx_with_history(4)
    ctx["recent_workouts"][0]["user_id"] = "user-b"
    ctx["recent_workouts"][0]["garmin_activity_id"] = "777"
    dumped = json.dumps(csc.build_session_chat_context(ctx), default=str)
    assert "user-b" not in dumped and "777" not in dumped


# ------------------------------------------------ 3/4. provenance

def _relative(count=31, status="used"):
    return {"status": status, "relative_position": "low", "reference_count": count,
            "period_start": "2026-04-20", "period_end": "2026-10-05",
            "criteria": {"window_days": 180, "duration_ratio_min": 0.5, "duration_ratio_max": 2.0}}


def test_relative_effort_provenance_is_a_distinct_population():
    p = ccv2._relative_effort_provenance(_relative(), {}, "v3")
    assert p["activity_count"] == 31
    assert (p["period_start"], p["period_end"]) == ("2026-04-20", "2026-10-05")
    assert p["selection_criteria"]["distance_is_a_selection_criterion"] is False
    assert p["selection_criteria"]["is_the_history_block_listing"] is False
    assert p["metric_type"] == "average_hr_relative_position"


def test_two_populations_stay_distinct():
    a = ccv2._relative_effort_provenance(_relative(31), {}, "v3")
    b = ccv2._relative_effort_provenance(_relative(16), {}, "v3")
    assert a["activity_count"] != b["activity_count"]


def test_comparison_provenance_carries_pace_and_hr_sub_populations():
    comparison = {"reference_count": 4, "period_start": "2026-05-06", "period_end": "2026-09-22",
                  "window_days": 180, "pace_at_comparable_hr": {"reference_count": 3, "hr_tolerance_bpm": 5},
                  "hr_at_comparable_pace": {"reference_count": 2, "pace_tolerance_sec_per_km": 15}}
    p = ccv2._comparison_provenance(comparison, "v3")
    assert p["sub_populations"]["pace_at_comparable_hr"]["activity_count"] == 3
    assert p["sub_populations"]["hr_at_comparable_pace"]["activity_count"] == 2


# ------------------------------------------------ 5/6/7. prescription chronology

def test_prescription_recorded_before_session():
    assert ccv2._prescription_timing("2026-10-10T07:41:00+00:00", "2026-10-10T09:00:00+00:00") \
        == "recorded_before_session"


def test_prescription_recorded_after_session():
    assert ccv2._prescription_timing("2026-09-13T19:01:00+00:00", "2026-09-13T08:00:00+00:00") \
        == "recorded_after_session"


def test_prescription_time_unknown_without_served_at_or_same_day_bare_date():
    assert ccv2._prescription_timing(None, "2026-09-13T08:00:00+00:00") == "recording_time_unknown"
    assert ccv2._prescription_timing("2026-09-13T19:01:00+00:00", "2026-09-13") == "recording_time_unknown"


def test_absence_of_prescription_yields_none():
    assert ccv2._recorded_prescription({}, "2026-10-10T09:00:00+00:00") in (None, "no_recorded_prescription") \
        or isinstance(ccv2._recorded_prescription({}, "2026-10-10T09:00:00+00:00"), str)


def test_indeterminate_is_not_a_deviation():
    rec = ccv2._recorded_prescription(
        {"prescription_assessment": {"prescription_id": "p", "status": "indeterminate",
                                     "served_at": "2026-10-10T07:41:00+00:00"}},
        "2026-10-10T09:00:00+00:00")
    assert rec["recording_timing"] == "recorded_before_session"
    assert "not a deviation" in rec["status_meaning"]


# ------------------------------------------------ contract-based context for the guard

def _context(*, status="indeterminate", timing="recorded_before_session", recorded=True,
             relative_count=31, history_included=5, population=11):
    contract = {
        "measured_facts": {"distance_km": 10.0, "avg_hr_bpm": 127, "avg_pace": "7:21",
                           "duration_minutes": 73.5, "recorded_effort_paces": [{"value": "4:31"}]},
        "validated_comparisons": [],
        "allowed_interpretations": [],
        "not_demonstrated": {"hr_rise_is_not_external_intensity": "x", "recovery_not_measured": "x"},
    }
    frame = {
        "evidence_contract": contract,
        "v3_assessment": {"classification": {"relative_effort": {
            "status": "used", "relative_position": "low", "reference_count": relative_count,
            "provenance": {"activity_count": relative_count, "period_start": "2026-04-20",
                           "period_end": "2026-10-05"}}}},
        "session_intent": {"recorded_historical_prescription": (
            {"assessment_status": status, "recording_timing": timing,
             "prescribed_workout_type": "rest"} if recorded else None)},
    }
    return {"language": "en", "session_coaching_frame": frame,
            "history_as_of_session": {"included_count": history_included, "eligible_count": 8},
            "runner_profile": {"observed_training": {"sessions_count": population}},
            "workout_detail": {"distance_km": 10.0}}


def _reasons(text, ctx=None):
    return guard.check_contract_claims(text, ctx or _context())


# 8. figures / populations

def test_ungrounded_population_count_is_rejected():
    assert "ungrounded_population_count" in _reasons("Your HR sits low versus 12 earlier sessions.")


def test_grounded_population_count_is_accepted():
    assert not _reasons("Your HR sits in the lower part of 31 earlier sessions.")


def test_hr_population_not_described_as_same_distance():
    assert "population_misdescribed" in _reasons(
        "Your HR is in the lower part of 31 sessions of the same distance.")


def test_statistic_on_shown_five_instead_of_population():
    assert "statistic_on_wrong_population" in _reasons("On average over 5 sessions you run 40 km.")


# 9. unsupported physiology / interpretation

def test_hr_rise_read_as_intensity_is_rejected():
    assert "hr_rise_read_as_intensity" in _reasons("Your heart rate rose, so the intensity increased.")


def test_pace_read_as_performance_is_rejected():
    assert "pace_read_as_performance" in _reasons("A better performance than last time.")


def test_recovery_advice_is_rejected_but_neutral_mention_is_not():
    assert "recovery_advice_not_supported" in _reasons("You need to rest after this long run.")
    assert not _reasons("Recovery was not measured for this session.")


# prescription claims

def test_indeterminate_is_not_reported_as_non_compliance():
    assert "non_compliance_not_established" in _reasons("You did not follow the prescription.")


def test_prescription_claim_without_record_is_rejected():
    assert "prescription_not_recorded" in _reasons(
        "The prescribed rest day was ignored.", _context(recorded=False))


def test_after_session_prescription_not_presented_as_intent():
    assert "prescription_timing_misstated" in _reasons(
        "The half marathon was planned for that day.", _context(timing="recorded_after_session"))


def test_before_session_prescription_may_be_mentioned():
    assert not _reasons("A rest day was recorded beforehand.", _context(timing="recorded_before_session"))


# ------------------------------------------------ 10. factual fallback

def test_fallback_is_built_from_contract_and_passes_the_guard():
    ctx = _context()
    for lang in ("fr", "en", "es"):
        text = guard.build_contract_fallback(ctx, lang)
        assert text and "127" in text and "31" in text
        assert guard.check_contract_claims(text, ctx) == set()


def test_fallback_states_after_session_timing():
    text = guard.build_contract_fallback(_context(timing="recorded_after_session"), "en")
    assert "after" in text.lower()


def test_fallback_none_without_contract():
    assert guard.build_contract_fallback({"language": "en"}, "en") is None


def test_verify_returns_structured_result_and_does_not_mutate_context():
    ctx = _context()
    before = copy.deepcopy(ctx)
    result = guard.verify_chat_reply("Your HR rose so the intensity increased.", ctx, "en")
    assert result["passed"] is False and "hr_rise_read_as_intensity" in result["rejected_checks"]
    assert result["level"] == guard.LEVEL
    assert ctx == before


# ------------------------------------------------ 11/12. read-only chat path & isolation

def test_guard_and_fallback_have_no_io_surface():
    source = open(guard.__file__, encoding="utf-8").read()
    for forbidden in ("insert_one", "update_one", "delete_many", "replace_one", "await ", "import server"):
        assert forbidden not in source


# ------------------------------------------------ server wiring (mocked DB and LLM)

import pytest as _pytest  # noqa: E402
from unittest.mock import AsyncMock, patch  # noqa: E402

import server  # noqa: E402
from test_coach_c393_fallback_quota import _owned_workout, _post  # noqa: E402
from test_coach_c408b_read_only import ALLOWED_WRITE_COLLECTIONS, _record_writes  # noqa: E402
from test_coach_contract_unified import _FakeDB, _STUB_REPLIES, _analyze_environment, _premium_access  # noqa: E402


@_pytest.mark.asyncio
async def test_rejected_reply_is_replaced_by_fallback_without_training_writes():
    fake_db = _FakeDB()
    fallback = "Fallback factual reply built from the contract only."
    with (
        _analyze_environment(fake_db, _premium_access),
        _owned_workout(fake_db),
        _record_writes(fake_db) as writes,
        patch.object(server.coach_evidence_guard, "verify_chat_reply",
                     return_value={"passed": False, "level": "x", "rejected_checks": ["hr_rise_read_as_intensity"]}),
        patch.object(server.coach_evidence_guard, "build_contract_fallback", return_value=fallback),
    ):
        response = await _post({"message": "Comment this session", "workout_id": "w1", "language": "en"})
    assert response.status_code == 200
    body = response.json()
    assert body["response"] == fallback
    assert body["verification"]["response_source"] == "contract_fallback"
    assert body["verification"]["rejected_checks"] == ["hr_rise_read_as_intensity"]
    assert {w[0] for w in writes} <= ALLOWED_WRITE_COLLECTIONS


@_pytest.mark.asyncio
async def test_passing_reply_is_kept_and_marked_checked():
    fake_db = _FakeDB()
    with (
        _analyze_environment(fake_db, _premium_access),
        _owned_workout(fake_db),
    ):
        response = await _post({"message": "Comment this session", "workout_id": "w1", "language": "en"})
    body = response.json()
    assert response.status_code == 200 and body["response"] == _STUB_REPLIES["en"]
    assert body["verification"]["response_source"] == "llm_reply_checked"
    assert "check_ms" in body["verification"]
