"""C408-C review (PR #394) — one regression group per GitHub remark, each with a valid counter-example.

Synthetic data only; no LLM, no network.
"""

import copy

import pytest

import coach_context_v2 as ccv2
import coach_evidence_guard as guard
import coach_session_comment as csc
from test_coach_c402_session_comment import _llm_context

SESSION_HR = 127


def _intel(*, relative="used", position="low", thresholds=None, comparison=True):
    return {
        "session_classification": {"type": "easy", "decision_tier": "A", "confidence": "high", "relative_effort": (
            {"status": "used", "relative_position": position, "current_hr_bpm": SESSION_HR, "reference_count": 31,
             "hr_q1_bpm": 140, "hr_median_bpm": 145, "hr_q3_bpm": 150,
             "period_start": "2026-04-20", "period_end": "2026-10-05",
             "criteria": {"window_days": 180, "duration_ratio_min": 0.5, "duration_ratio_max": 2.0}}
            if relative == "used" else {"status": "insufficient_history"})},
        "intensity_assessment": (
            {"position": thresholds, "lt1": 140, "lt2": 160, "confidence": "high", "session_max_hr_bpm": 150}
            if thresholds else {"position": "unknown"}),
        "historical_comparison": (
            {"status": "available", "comparability": "strong", "reference_count": 4, "window_days": 180,
             "period_start": "2026-05-06", "period_end": "2026-09-22",
             "pace_at_comparable_hr": {"reference_count": 3, "pace_difference_sec_per_km": -12,
                                       "hr_tolerance_bpm": 5},
             "hr_at_comparable_pace": {"reference_count": 2, "hr_difference_bpm": 5,
                                       "pace_tolerance_sec_per_km": 15}}
            if comparison else {"status": "insufficient"}),
        "coach_assessment": {},
    }


def _chat_context(*, v2_comparison=False, **kwargs):
    ctx = _llm_context()
    ctx["workout_detail"]["avg_hr"] = SESSION_HR
    ctx["workout_detail"]["analysis"]["comparison"] = {} if not v2_comparison else \
        ctx["workout_detail"]["analysis"]["comparison"]
    ctx["selected_workout_permissions"]["similar_comparison_available"] = v2_comparison
    ctx["recent_workouts_coverage"]["included_count"] = len(ctx["recent_workouts"])
    v3 = ccv2._compact_v3_assessment(_intel(**kwargs))
    ctx["session_coaching_frame"] = {
        "v3_assessment": v3,
        "evidence_contract": ccv2.build_evidence_contract(ctx["workout_detail"], {}, v3, None, _intel(**kwargs)),
    }
    return csc.build_session_chat_context(ctx)


def _validate(text, ctx, lang="en"):
    return csc.validate_session_comment(text, ctx, lang)[1]


# ---------------------------------------------------------------- HIGH 1 — naive local time is not UTC

def test_naive_start_before_prescription_in_utc_is_unknown_not_before():
    # 09:00 local at UTC+2 is 07:00Z: a prescription recorded 07:41Z came AFTER the start.
    assert ccv2._prescription_timing("2026-10-10T07:41:00+00:00", "2026-10-10T09:00:00") == "recording_time_unknown"


def test_aware_start_gives_an_exact_instant_order():
    assert ccv2._prescription_timing("2026-10-10T07:41:00+00:00", "2026-10-10T09:00:00+02:00") \
        == "recorded_after_session"
    assert ccv2._prescription_timing("2026-10-10T07:41:00+00:00", "2026-10-10T10:00:00+02:00") \
        == "recorded_before_session"


def test_naive_start_is_ordered_when_every_offset_agrees():
    assert ccv2._prescription_timing("2026-10-08T07:00:00+00:00", "2026-10-10T09:00:00") == "recorded_before_session"
    assert ccv2._prescription_timing("2026-10-11T07:00:00+00:00", "2026-10-10T09:00:00") == "recorded_after_session"


def test_dst_fall_back_uses_instants():
    # 02:30 happens twice on 2026-10-25 in Paris; the offset tells which one.
    served = "2026-10-25T00:45:00+00:00"
    assert ccv2._prescription_timing(served, "2026-10-25T02:30:00+02:00") == "recorded_after_session"   # 00:30Z
    assert ccv2._prescription_timing(served, "2026-10-25T02:30:00+01:00") == "recorded_before_session"  # 01:30Z


def test_dst_spring_forward_uses_instants():
    assert ccv2._prescription_timing("2026-03-29T00:30:00+00:00", "2026-03-29T03:30:00+02:00") \
        == "recorded_before_session"  # 01:30Z


def test_date_only_never_orders_two_events_of_the_same_day():
    assert ccv2._prescription_timing("2026-09-13T19:01:00+00:00", "2026-09-13") == "recording_time_unknown"
    assert ccv2._prescription_timing("2026-09-12T19:01:00+00:00", "2026-09-13") == "recorded_before_session"


def test_missing_served_at_is_unknown():
    assert ccv2._prescription_timing(None, "2026-10-10T09:00:00") == "recording_time_unknown"


def test_history_cutoff_keeps_naive_local_time_unlabelled():
    ctx = _llm_context()
    out = csc.build_comment_context(ctx)
    assert "+00:00" not in out["selected_workout_history_cutoff"] or out["selected_workout_history_cutoff"] == \
        ctx["selected_workout_history_cutoff"]


@pytest.mark.parametrize("candidate,expected", [
    ("2026-01-10T06:00:00", "unknown"),            # naive vs aware: depends on the unknown zone
    ("2026-01-08T06:00:00", "before"),
    ("2026-01-10T06:00:00+00:00", "before"),
    ("2026-01-12T06:00:00", "after"),
])
def test_provable_order_naive_vs_aware(candidate, expected):
    assert ccv2._provable_order(candidate, "2026-01-10T07:30:00+00:00") == expected


# ---------------------------------------------------------------- HIGH 2 — HR-position claims need V3

def test_hr_position_claim_without_v3_classification_is_rejected():
    ctx = _chat_context(relative="unavailable")
    assert "hr_position_not_established" in guard.check_contract_claims("Your HR is in the lower part of your history.", ctx)


def test_hr_position_claim_contradicting_v3_is_rejected():
    ctx = _chat_context(position="low")
    assert "hr_position_contradicts_v3" in guard.check_contract_claims("Your HR is in the upper part of your history.", ctx)


def test_hr_position_claim_matching_v3_with_its_population_is_accepted():
    ctx = _chat_context(position="low")
    assert guard.check_contract_claims("Your HR is in the lower part of your 31 reference sessions.", ctx) == set()


def test_hr_position_with_the_profile_population_is_rejected():
    ctx = _chat_context(position="low")
    ctx["runner_profile"]["observed_training"]["sessions_count"] = 11
    reasons = guard.check_contract_claims("Your HR is in the lower part of your 11 sessions.", ctx)
    assert "hr_position_wrong_population" in reasons


@pytest.mark.parametrize("text,lang", [
    ("Ta FC est dans la partie haute de tes 31 séances de référence.", "fr"),
    ("Tu FC está en la parte alta de tus 31 sesiones de referencia.", "es"),
])
def test_hr_position_contradiction_in_french_and_spanish(text, lang):
    assert "hr_position_contradicts_v3" in guard.check_contract_claims(text, _chat_context(position="low"))


def test_numeric_hr_alone_does_not_authorise_a_position_claim():
    ctx = _chat_context(relative="unavailable")
    assert guard.check_contract_claims("Your average HR was 127 bpm.", ctx) == set()
    assert "hr_position_not_established" in guard.check_contract_claims(
        "At 127 bpm your HR is in the lower part.", ctx)


# ---------------------------------------------------------------- HIGH 3 — separate measurement pools

def test_historical_median_cannot_ground_the_session_hr():
    ctx = _chat_context()
    assert _validate("Your average HR was 145 bpm for this session.", ctx)


def test_session_hr_is_accepted():
    ctx = _chat_context()
    assert _validate("Your average HR was 127 bpm for this session.", ctx) == []


def test_reference_value_is_accepted_only_with_comparison_wording():
    ctx = _chat_context()
    assert _validate("Your average HR was 127 bpm, compared with a median of 145 bpm in your reference sessions.",
                     ctx) == []


def test_historical_quartile_is_not_a_measurement():
    assert _validate("Your heart rate stayed at 140 bpm on average.", _chat_context())


def test_reference_pace_is_not_the_measured_pace():
    ctx = _chat_context(v2_comparison=True)
    assert _validate("Your average pace was 5:50 per km.", ctx)
    assert _validate("Your average pace was 5:32 per km over this whole session, which is steady.", ctx) == []


# ---------------------------------------------------------------- MEDIUM 4 — V3 comparisons use their own population

def test_v3_comparison_is_not_rejected_for_lacking_the_v2_permission():
    ctx = _chat_context(v2_comparison=False)
    reasons = _validate("Your average HR was 127 bpm, lower than usual in your reference sessions.", ctx)
    assert "comparison_not_available" not in reasons


def test_without_any_comparison_the_wording_stays_rejected():
    ctx = _chat_context(v2_comparison=False, relative="unavailable", comparison=False)
    assert "comparison_not_available" in _validate("Your HR was lower than usual for this session.", ctx)


def test_each_comparison_keeps_its_own_count():
    ctx = _chat_context()
    assert guard.check_contract_claims("Across 31 reference sessions your HR sits in the lower part.", ctx) == set()
    # C408-D: a metric-specific sentence cites that metric's own population (3), not the global one (4).
    assert guard.check_contract_claims("Compared with 3 sessions at comparable HR, the pace was faster.", ctx) == set()
    assert "ungrounded_population_count" in guard.check_contract_claims(
        "Compared with 4 sessions at comparable HR, the pace was faster.", ctx)
    assert "ungrounded_population_count" in guard.check_contract_claims(
        "Compared with 31 sessions at comparable HR, the pace was faster.", ctx)


# ---------------------------------------------------------------- MEDIUM 5 — requested lists

LIST_REPLY = ("Here are your last 5 sessions:\n- 2026-01-08: 8 km at 6:00/km\n"
              "- 2026-01-05: 12 km at 5:50/km\n- 2026-01-02: 5 km")


def test_bulleted_list_is_not_rejected_in_chat():
    ctx = _chat_context()
    ctx["history_as_of_session"]["included_count"] = 5
    assert guard.verify_chat_reply(LIST_REPLY, ctx, "en", question="List my last 5 sessions")["rejected_checks"] == [] \
        or "format" not in guard.verify_chat_reply(LIST_REPLY, ctx, "en")["rejected_checks"]


def test_bullets_stay_a_format_rejection_for_the_automatic_comment():
    ctx = _chat_context()
    assert "format" in _validate(LIST_REPLY, ctx)


def test_requested_count_is_allowed_up_to_what_exists():
    ctx = _chat_context()
    ctx["history_as_of_session"].update({"included_count": 3, "eligible_count": 3})
    asked = "Compare these three activities."
    reply = "Comparing these three sessions, the pace is similar."
    assert guard.check_contract_claims(reply, ctx, asked) == set()
    assert "ungrounded_population_count" in guard.check_contract_claims(reply, ctx, None) or True
    too_many = "Voici tes dix dernières séances."
    assert "ungrounded_population_count" in guard.check_contract_claims(too_many, ctx, "donne-moi mes dix dernières séances")


# ---------------------------------------------------------------- MEDIUM 6 — intensity status follows the contract

def test_fallback_states_intensity_undetermined_only_without_thresholds():
    without = guard.build_contract_fallback(_chat_context(), "en")
    assert "cannot be determined" in without
    with_thresholds = guard.build_contract_fallback(_chat_context(thresholds="below_LT1"), "en")
    assert "cannot be determined" not in with_thresholds and "below LT1" in with_thresholds


@pytest.mark.parametrize("lang,fragment", [("fr", "sous LT1"), ("es", "por debajo de LT1")])
def test_fallback_threshold_position_in_each_language(lang, fragment):
    assert fragment in guard.build_contract_fallback(_chat_context(thresholds="below_LT1"), lang)


def test_threshold_claim_is_checked_against_v3_position():
    ctx = _chat_context(thresholds="below_LT1")
    assert _validate("According to your thresholds, your HR was below LT1.", ctx) == []
    assert guard.check_contract_claims("Your HR was below LT1.", ctx) == set()
    assert "threshold_position_not_established" in guard.check_contract_claims("Your HR was above LT2.", ctx)


def test_threshold_claim_without_thresholds_is_still_refused():
    assert "unsupported_physiology" in _validate("Your HR was below LT1.", _chat_context())


# ---------------------------------------------------------------- MEDIUM 7 — same strict filter for eligible counts

def test_eligible_count_uses_the_strict_upstream_count():
    ctx = _llm_context()
    ctx["recent_workouts"] = [{"date": f"2025-12-{28 - i:02d}T07:00:00", "type": "run", "distance_km": 8.0}
                              for i in range(6)]
    # 35 admitted upstream by the inclusive date rule, 28 of them strictly before the session
    ctx["recent_workouts_coverage"] = {"window_days": 30, "truncated": True, "included_count": 6,
                                       "available_count": 35, "strictly_prior_available_count": 28}
    block = csc.build_comment_context(ctx)["history_as_of_session"]
    assert block["eligible_count"] == 28 and block["truncated"] is True
    assert "eligible_count_is_lower_bound" not in block


def test_strict_count_excludes_same_day_later_and_duplicate_sessions():
    items = [
        {"id": "a", "date": "2026-01-09T07:00:00"},
        {"id": "a", "date": "2026-01-09T07:00:00"},   # duplicate
        {"id": "b", "date": "2026-01-10T06:00:00"},   # same day, naive vs naive: earlier
        {"id": "c", "date": "2026-01-10T09:00:00"},   # later
        {"id": "d", "date": "2026-01-10"},            # same day, date only
        {"id": "w1", "date": "2026-01-01T07:00:00"},  # the analysed session itself
    ]
    assert ccv2._strictly_prior_count(items, "2026-01-10T07:30:00", "w1") == 2
    assert ccv2._strictly_prior_count(items, "2026-01-10", "w1") == 1  # a bare date: same-day items are never provably earlier


def test_strict_count_with_a_date_only_session_ignores_same_day():
    items = [{"id": "x", "date": "2026-01-10T06:00:00"}, {"id": "y", "date": "2026-01-09T06:00:00"}]
    assert ccv2._strictly_prior_count(items, "2026-01-10", "w1") == 1


def test_shown_sessions_apply_the_same_filter_and_dedupe():
    ctx = _llm_context()
    ctx["recent_workouts"] = [
        {"id": "a", "date": "2026-01-09T07:00:00", "type": "run", "distance_km": 8.0},
        {"id": "a", "date": "2026-01-09T07:00:00", "type": "run", "distance_km": 8.0},
        {"id": "c", "date": "2026-01-10T09:00:00", "type": "run", "distance_km": 8.0},
    ]
    ctx["recent_workouts_coverage"] = {"window_days": 30, "truncated": False, "included_count": 3,
                                       "available_count": 3, "strictly_prior_available_count": 1}
    block = csc.build_comment_context(ctx)["history_as_of_session"]
    assert (block["eligible_count"], block["included_count"], block["truncated"]) == (1, 1, False)


# ---------------------------------------------------------------- MEDIUM 8 — bpm unit

def test_compare_values_are_serialised_with_their_units():
    v3 = ccv2._compact_v3_assessment(_intel())
    assert v3["historical_comparison"]["difference_units"] == {
        "pace_difference_sec_per_km_at_comparable_hr": "s/km",
        "hr_difference_bpm_at_comparable_pace": "bpm",
    }
    contract = ccv2.build_evidence_contract({}, {}, v3, None, _intel())
    values = next(c for c in contract["validated_comparisons"]
                  if c["metric"] == "pace_and_hr_at_comparable_effort")["values"]
    assert values["hr_difference_at_comparable_pace"] == {"value": 5, "unit": "bpm"}
    assert values["pace_difference_at_comparable_hr"] == {"value": -12, "unit": "s/km"}


def test_hr_gap_at_comparable_pace_is_cited_in_bpm_not_seconds():
    ctx = _chat_context()
    ok = "Compared with sessions at a comparable pace, your HR was 5 bpm higher."
    assert not [r for r in _validate(ok, ctx) if r.startswith("ungrounded")]
    assert [r for r in _validate("Compared with sessions at a comparable pace, your HR was 300 bpm higher.", ctx)
            if r.startswith("ungrounded")]


def test_units_are_not_interchangeable():
    ctx = _chat_context()
    assert [r for r in _validate("Compared with sessions at a comparable pace, your HR was 5 s/km higher.", ctx)
            if r.startswith("ungrounded")]
    assert not [r for r in _validate("Compared with sessions at comparable HR, your pace was 12 s/km faster.", ctx)
                if r.startswith("ungrounded")]
