"""C371 synthetic bounded recorded observations; no external service authority."""

from copy import deepcopy
from dataclasses import replace
import json
import math
import socket

import pytest

from access_control import UserAccess
import hybrid_coach_c359 as hybrid
from hybrid_coach_editorial_c365 import (
    MAX_RECORDED_METRIC_CHARS, RECORDED_FRACTION_DIGITS, RECORDED_WHOLE_DIGITS,
    allowed_forms, format_recorded_seconds, realize_clause, validate_editorial_selection,
)
from test_hybrid_coach_c359 import _access, _context, _facts, _provider, _run, synthetic_case
from workout_intelligence_v3_models import (
    WIV3EffortDuration, WIV3EffortDurationObservations,
    WIV3EffortPace, WIV3EffortPaceObservations, WIV3PrescriptionAssessment,
)


def recorded_case(n=4, *, orders=None, pace=True, duration=True, base=None):
    """Build the canonical C368/C369 boundary, without Garmin or V2 execution."""
    v3 = base or synthetic_case("intervals_4x4")
    orders = orders if orders is not None else [2 * i + 1 for i in range(n)]
    updates = {}
    for kind, enabled, model, block_model, field, count_field in (
        ("pace", pace, WIV3EffortPace, WIV3EffortPaceObservations,
         "pace_sec_per_km", "available_pace_count"),
        ("duration", duration, WIV3EffortDuration, WIV3EffortDurationObservations,
         "duration_s", "available_duration_count"),
    ):
        if not enabled:
            updates[f"effort_{kind}_observations"] = block_model()
            continue
        rows = [
            model(
                id=f"recorded_effort_{kind}:{order}", order=order, effort_number=i + 1,
                available=True, **{field: (288 + i * 3 if kind == "pace" else 240 + i)},
                source_paths=[
                    f"garmin_activities.activity_details.phases[{order}]" + (".duration_s" if kind == "duration" else ""),
                    f"workout_analysis_v2.phase_analysis.efforts[{i}].{field}",
                ],
            )
            for i, order in enumerate(orders)
        ]
        updates[f"effort_{kind}_observations"] = block_model(
            status="available", recorded_effort_count=n, efforts=rows, **{count_field: n},
        )
    return v3.model_copy(update=updates, deep=True)


def change_row(v3, kind, index=0, **changes):
    name = f"effort_{kind}_observations"
    block = getattr(v3, name)
    rows = list(block.efforts)
    rows[index] = rows[index].model_copy(update=changes)
    return v3.model_copy(update={name: block.model_copy(update={"efforts": rows})})


def effort_facts(v3, **kwargs):
    return {f.id: f for f in _facts(v3, **kwargs) if f.id.startswith("effort.")}


def values(v3, id="effort.first"):
    return dict(effort_facts(v3)[id].values)


def selection(primary="effort.first", supporting=(), **extra):
    return json.dumps({
        "primary": {"fact_id": primary, "form": "direct"},
        "supporting": [{"fact_id": id, "form": "direct"} for id in supporting],
        "editorial_intent": "describe_session", **extra,
    })


@pytest.fixture(autouse=True)
def isolated(monkeypatch):
    monkeypatch.delenv(hybrid.FEATURE_FLAG, raising=False)
    monkeypatch.delenv("C355_NARRATIVE_LLM_ENABLED", raising=False)

    def forbidden(*args, **kwargs):
        raise AssertionError("No network, Mongo, Garmin, or default transport")

    monkeypatch.setattr(socket, "create_connection", forbidden)
    monkeypatch.setattr(socket.socket, "connect", forbidden)
    monkeypatch.setattr(hybrid, "_transport", forbidden)


def test_four_efforts_bounded_packet_and_realization(monkeypatch):
    v3 = recorded_case()
    facts = effort_facts(v3)
    assert set(facts) == {"effort.first", "effort.last", "effort.coverage"}
    assert values(v3) == {"effort_number": 1, "recorded_pace": 288, "recorded_duration": 240}
    assert values(v3, "effort.last")["effort_number"] == 4
    assert values(v3, "effort.coverage") == {
        "recorded_total": 4, "pace_count": 4, "duration_count": 4, "both_count": 4,
    }
    assert len(_context(recorded_case(100))["facts"]) == len(_context(v3)["facts"])
    packet = json.dumps(_context(v3))
    assert "recorded_effort_pace:" not in packet
    assert "source_paths" not in packet and "synthetic-owner" not in packet
    assert all(allowed_forms(f, "fr") == ["direct", "explain"] for f in facts.values())
    monkeypatch.setenv(hybrid.FEATURE_FLAG, "true")
    result = _run(v3, transport=_provider(lambda *_: selection(supporting=("effort.last", "effort.coverage"))))
    assert result.mode == "editorial_realization"
    assert len(result.claims) == 3
    assert "a duré 4 min, à 4'48/km" in result.text
    assert "Dans l'ordre enregistré par Garmin" in result.text


def test_one_effort_not_duplicated():
    facts = effort_facts(recorded_case(1))
    assert set(facts) == {"effort.first", "effort.coverage"}
    assert dict(facts["effort.coverage"].values)["both_count"] == 1


@pytest.mark.parametrize("language,expected", [
    ("fr", "Sur 1 effort enregistré par Garmin : 1 avec allure, 1 avec durée, 1 avec les deux."),
    ("en", "Of 1 Garmin-recorded effort: 1 with pace, 1 with duration, 1 with both."),
    ("es", "De 1 esfuerzo registrado por Garmin: 1 con ritmo, 1 con duración, 1 con ambos."),
])
def test_single_effort_coverage_uses_natural_singular(language, expected):
    coverage = effort_facts(recorded_case(1), language=language)["effort.coverage"]
    assert coverage.assertion == expected
    assert realize_clause(coverage, "direct", language) == expected
    assert realize_clause(coverage, "explain", language) == expected


@pytest.mark.parametrize("kind", ["pace", "duration"])
def test_single_block_does_not_invent_other_coverage(kind):
    v3 = recorded_case(pace=kind == "pace", duration=kind == "duration")
    first = values(v3)
    assert set(first) == {"effort_number", f"recorded_{kind}"}
    coverage = values(v3, "effort.coverage")
    assert coverage == {"recorded_total": 4, f"{kind}_count": 4}
    for lang, phrase in (("fr", "seule mesure disponible"), ("en", "only available metric"),
                         ("es", "única medida disponible")):
        assert phrase in effort_facts(v3, language=lang)["effort.first"].assertion


@pytest.mark.parametrize("bad", [None, 0, -1, True, False, float("nan"), float("inf"), -float("inf"), 10**400])
@pytest.mark.parametrize("kind,field", [("pace", "pace_sec_per_km"), ("duration", "duration_s")])
def test_invalid_numeric_never_admitted_or_counted(kind, field, bad):
    v3 = change_row(recorded_case(), kind, **{field: bad})
    assert f"recorded_{kind}" not in values(v3)
    assert values(v3, "effort.coverage")[f"{kind}_count"] == 3
    assert values(v3, "effort.coverage")["both_count"] == 3
    json.dumps(_context(v3), allow_nan=False)


@pytest.mark.parametrize("available", [False, "available", 1, None])
def test_availability_is_strict_boolean(available):
    v3 = change_row(recorded_case(), "pace", available=available)
    assert "recorded_pace" not in values(v3)
    assert values(v3, "effort.coverage")["pace_count"] == 3


@pytest.mark.parametrize("kind", ["pace", "duration"])
def test_available_row_with_unavailable_reason_is_not_admitted(kind):
    v3 = change_row(recorded_case(), kind, unavailable_reason="measurement_missing")
    assert f"recorded_{kind}" not in values(v3)
    assert values(v3, "effort.coverage")[f"{kind}_count"] == 3
    assert values(v3, "effort.coverage")["both_count"] == 3


@pytest.mark.parametrize("count", [0, 999, True, None, float("nan")])
def test_stale_available_count_does_not_authorize_invalid_measurement(count):
    v3 = change_row(recorded_case(), "pace", pace_sec_per_km=None)
    block = v3.effort_pace_observations
    v3 = v3.model_copy(update={"effort_pace_observations": block.model_copy(update={
        "available_pace_count": count, "status": "available",
    })})
    assert "recorded_pace" not in values(v3)
    assert values(v3, "effort.coverage")["pace_count"] == 3
    json.dumps(_context(v3), allow_nan=False)


def test_partial_status_does_not_override_individual_admissions():
    v3 = recorded_case()
    block = v3.effort_pace_observations
    v3 = v3.model_copy(update={"effort_pace_observations": block.model_copy(update={
        "available_pace_count": 0, "status": "partial",
    })})
    assert values(v3, "effort.coverage")["pace_count"] == 4
    assert values(v3)["recorded_pace"] == 288
    v3 = v3.model_copy(update={"effort_pace_observations": block.model_copy(update={
        "available_pace_count": 4, "status": "unavailable",
    })})
    assert values(v3, "effort.coverage")["pace_count"] == 0
    assert "recorded_pace" not in values(v3)


@pytest.mark.parametrize("field,bad", [("order", True), ("order", -1), ("order", 1.0),
                                      ("effort_number", True), ("effort_number", 0),
                                      ("effort_number", 1.0)])
def test_bypassed_constructed_identity_is_not_admitted(field, bad):
    v3 = recorded_case()
    block = v3.effort_pace_observations
    row = block.efforts[0]
    constructed = WIV3EffortPace.model_construct(**{**row.model_dump(), field: bad})
    v3 = v3.model_copy(update={"effort_pace_observations": block.model_copy(update={
        "efforts": [constructed, *block.efforts[1:]],
    })})
    assert "recorded_pace" not in values(v3)
    assert "recorded_duration" in values(v3)


@pytest.mark.parametrize("kind", ["pace", "duration"])
@pytest.mark.parametrize("field,bad", [
    ("source", "training"), ("endpoint", "laps"), ("method", "injected"),
    ("source_paths", ["injected-secret"]), ("code", "injected"), ("unit", "min"),
    ("id", "injected-secret"),
])
def test_inadmissible_provenance_cannot_combine(kind, field, bad):
    v3 = change_row(recorded_case(), kind, **{field: bad})
    first = values(v3)
    assert f"recorded_{kind}" not in first
    assert len(first) == 2
    assert "injected" not in json.dumps(_context(v3))


def test_source_paths_bind_phase_and_v2_index_not_list_position():
    v3 = recorded_case(orders=[0, 4, 9, 20])
    for kind in ("pace", "duration"):
        name = f"effort_{kind}_observations"
        block = getattr(v3, name)
        indices = [3, 0, 2, 1] if kind == "pace" else [1, 2, 0, 3]
        v3 = v3.model_copy(update={name: block.model_copy(update={
            "efforts": [block.efforts[i] for i in indices],
        })})
    assert values(v3)["recorded_duration"] == 240
    assert values(v3, "effort.last") == {
        "effort_number": 4, "recorded_pace": 297, "recorded_duration": 243,
    }
    assert values(v3, "effort.coverage")["both_count"] == 4
    first = effort_facts(v3)["effort.first"]
    assert first.source_paths == (
        "effort_pace_observations.efforts[1].pace_sec_per_km",
        "effort_duration_observations.efforts[2].duration_s",
    )
    broken = change_row(v3, "pace", 1, source_paths=[
        "garmin_activities.activity_details.phases[0]",
        "workout_analysis_v2.phase_analysis.efforts[1].pace_sec_per_km",
    ])
    assert "recorded_pace" not in values(broken)


@pytest.mark.parametrize("numbers", [[2, 7], [7, 2]])
def test_preserves_noncontiguous_v2_effort_numbering(numbers):
    v3 = recorded_case(2, orders=[5, 9])
    for kind in ("pace", "duration"):
        for index, number in enumerate(numbers):
            v3 = change_row(v3, kind, index, effort_number=number)
    assert values(v3)["effort_number"] == numbers[0]
    assert values(v3, "effort.last")["effort_number"] == numbers[1]
    assert values(v3, "effort.coverage") == {
        "recorded_total": 2, "pace_count": 2, "duration_count": 2, "both_count": 2,
    }
    assert len(values(v3)) == 3
    assert effort_facts(v3)["effort.first"].source_paths == (
        "effort_pace_observations.efforts[0].pace_sec_per_km",
        "effort_duration_observations.efforts[0].duration_s",
    )


def test_real_v2_to_v3_extractors_preserve_numbers_independent_of_source_indices():
    from activity_phases import ActivityPhase
    from workout_analysis_v2 import build_workout_analysis_v2
    from workout_intelligence_v3 import build_workout_intelligence_v3, extract_workout_intelligence_input

    workout = {
        "id": "synthetic-extractor", "user_id": "synthetic-owner",
        "date": "2026-06-01", "type": "run", "duration_minutes": 30,
        "distance_km": 5, "avg_heart_rate": 145, "avg_pace_min_km": 6,
    }
    v2 = build_workout_analysis_v2(workout, [], phases=[
        ActivityPhase(order=5, phase_type="effort", duration_s=240, distance_m=1000, source="garmin"),
        ActivityPhase(order=9, phase_type="effort", duration_s=180, distance_m=500, source="garmin"),
    ])
    efforts = [
        row.model_copy(update={"effort_number": number})
        for row, number in zip(v2.phase_analysis.efforts, [2, 7])
    ]
    v2 = v2.model_copy(update={"phase_analysis": v2.phase_analysis.model_copy(update={"efforts": efforts})})
    original = deepcopy(v2.model_dump())
    extracted = extract_workout_intelligence_input(workout, [], v2_analysis=v2)
    v3 = build_workout_intelligence_v3(extracted, "fr")
    assert [row.effort_number for row in v3.effort_duration_observations.efforts] == [2, 7]
    assert v3.effort_duration_observations.efforts[0].source_paths == [
        "garmin_activities.activity_details.phases[5].duration_s",
        "workout_analysis_v2.phase_analysis.efforts[0].duration_s",
    ]
    assert values(v3) == {"effort_number": 2, "recorded_pace": 240, "recorded_duration": 240}
    assert values(v3, "effort.last") == {"effort_number": 7, "recorded_pace": 360, "recorded_duration": 180}
    assert values(v3, "effort.coverage")["both_count"] == 2
    assert v2.model_dump() == original


def test_v2_source_index_is_not_effort_number_or_v3_list_position():
    v3 = recorded_case(2, orders=[5, 9])
    for kind, field in (("pace", "pace_sec_per_km"), ("duration", "duration_s")):
        for index, number in enumerate([7, 2]):
            paths = list(getattr(v3, f"effort_{kind}_observations").efforts[index].source_paths)
            paths[1] = f"workout_analysis_v2.phase_analysis.efforts[{1 - index}].{field}"
            v3 = change_row(v3, kind, index, effort_number=number, source_paths=paths)
    assert values(v3)["effort_number"] == 7
    assert values(v3)["recorded_duration"] == 240
    assert values(v3, "effort.coverage")["both_count"] == 2


def test_inconsistent_cross_block_v2_indices_never_combine():
    v3 = recorded_case(2)
    for index in range(2):
        paths = list(v3.effort_duration_observations.efforts[index].source_paths)
        paths[1] = f"workout_analysis_v2.phase_analysis.efforts[{1 - index}].duration_s"
        v3 = change_row(v3, "duration", index, source_paths=paths)
    assert set(effort_facts(v3)) == {"effort.coverage"}
    assert values(v3, "effort.coverage") == {
        "recorded_total": 2, "pace_count": 0, "duration_count": 0, "both_count": 0,
    }


@pytest.mark.parametrize("mode", ["order", "number", "duplicate"])
def test_cross_block_identity_conflicts_quarantined(mode):
    v3 = recorded_case()
    if mode == "order":
        v3 = change_row(v3, "duration", effort_number=2)
    elif mode == "number":
        v3 = change_row(v3, "duration", order=2, id="recorded_effort_duration:2")
    else:
        block = v3.effort_pace_observations
        v3 = v3.model_copy(update={"effort_pace_observations": block.model_copy(update={
            "efforts": [block.efforts[0], block.efforts[0], *block.efforts[2:]],
        })})
    facts = effort_facts(v3)
    assert "effort.first" not in facts
    assert "effort.last" in facts
    assert "effort.coverage" not in facts


def test_first_last_not_extremes_and_never_fill_missing_endpoint():
    v3 = recorded_case()
    v3 = change_row(v3, "pace", 1, pace_sec_per_km=100)
    v3 = change_row(v3, "pace", 2, pace_sec_per_km=999)
    assert values(v3)["recorded_pace"] == 288
    assert values(v3, "effort.last")["recorded_pace"] == 297
    for kind, field in (("pace", "pace_sec_per_km"), ("duration", "duration_s")):
        v3 = change_row(v3, kind, 0, **{field: None})
    facts = effort_facts(v3)
    assert "effort.first" not in facts
    assert dict(facts["effort.last"].values)["effort_number"] == 4


@pytest.mark.parametrize("kind", ["pace", "duration"])
@pytest.mark.parametrize("index,label", [(0, "first"), (3, "last")])
@pytest.mark.parametrize("field", ["order", "effort_number"])
@pytest.mark.parametrize("reorder", [False, True])
def test_unresolved_single_block_identity_never_promotes_inner_effort(kind, index, label, field, reorder):
    v3 = recorded_case(pace=kind == "pace", duration=kind == "duration")
    v3 = change_row(v3, kind, index, **{field: None})
    if reorder:
        name = f"effort_{kind}_observations"
        block = getattr(v3, name)
        v3 = v3.model_copy(update={name: block.model_copy(update={
            "efforts": [block.efforts[i] for i in [2, 0, 3, 1]],
        })})
    facts = effort_facts(v3)
    assert f"effort.{label}" not in facts
    assert "effort.coverage" not in facts
    for id in ("effort.first", "effort.last"):
        if id in facts:
            assert dict(facts[id].values)["effort_number"] == (1 if id == "effort.first" else 4)


def test_partial_coverage_recomputed_not_trusted_or_classification_based():
    v3 = recorded_case(3)
    v3 = change_row(v3, "pace", 0, available=False)
    v3 = change_row(v3, "duration", 1, duration_s=None)
    assert values(v3, "effort.coverage") == {
        "recorded_total": 3, "pace_count": 2, "duration_count": 2, "both_count": 1,
    }
    block = v3.effort_duration_observations
    v3 = v3.model_copy(update={"effort_duration_observations": block.model_copy(update={
        "recorded_effort_count": 500,
    })})
    assert "effort.coverage" not in effort_facts(v3)
    assert "effort.first" in effort_facts(v3)


@pytest.mark.parametrize("status", ["partial", "unavailable", "injected"])
def test_block_status_is_admission_boundary(status):
    v3 = recorded_case()
    block = v3.effort_pace_observations
    v3 = v3.model_copy(update={"effort_pace_observations": block.model_copy(update={"status": status})})
    assert ("recorded_pace" in values(v3)) is (status == "partial")


@pytest.mark.parametrize("language,pace", [("fr", "4'48,125/km"), ("en", "4:48.125/km"),
                                          ("es", "4:48,125/km")])
def test_localized_exact_realization(language, pace):
    v3 = change_row(recorded_case(1), "pace", pace_sec_per_km=288.125)
    v3 = change_row(v3, "duration", duration_s=60.000001)
    fact = effort_facts(v3, language=language)["effort.first"]
    text = realize_clause(fact, "direct", language)
    decimal = "." if language == "en" else ","
    assert pace in text
    assert f"1 min 00{decimal}000001 s" in text
    assert realize_clause(fact, "explain", language) == text


@pytest.mark.parametrize("language,expected", [
    ("fr", "Dans l'ordre enregistré par Garmin, le premier effort (n° 1) a duré 4 min, à 4'48/km."),
    ("en", "In Garmin's recorded order, the first effort (no. 1) lasted 4 min at 4:48/km."),
    ("es", "En el orden registrado por Garmin, el primer esfuerzo (n.º 1) duró 4 min, a 4:48/km."),
])
def test_natural_backend_sentence_preserves_recorded_order_scope(language, expected):
    first = effort_facts(recorded_case(1), language=language)["effort.first"]
    assert first.assertion == expected
    assert "recorded_order_not_verified_absolute_chronology" in first.important_limits


@pytest.mark.parametrize("value,expected", [
    (59.99999999999999, "59.99999999999999 s"),
    (60, "1 min"), (0.125, "0.125 s"),
    (1e-18, "0.000000000000000001 s"),
])
def test_duration_precision_boundaries_and_exponents(value, expected):
    assert format_recorded_seconds(value, "en") == expected
    v3 = change_row(recorded_case(1), "duration", duration_s=value)
    assert expected in effort_facts(v3, language="en")["effort.first"].assertion


@pytest.mark.parametrize("value", [1e-18, 1e-10, 999999, 999999.9999999999])
@pytest.mark.parametrize("language", ["fr", "en", "es"])
def test_extreme_exponents_exact_pace_decomposition(value, language):
    from decimal import Decimal

    whole, _, fraction = format(Decimal(str(value)), "f").partition(".")
    minutes, seconds = divmod(int(whole), 60)
    separator = "'" if language == "fr" else ":"
    decimal = "." if language == "en" else ","
    suffix = decimal + fraction.rstrip("0") if fraction.rstrip("0") else ""
    expected = f"{minutes}{separator}{seconds:02d}{suffix}/km"
    v3 = change_row(recorded_case(1), "pace", pace_sec_per_km=value)
    assert expected in effort_facts(v3, language=language)["effort.first"].assertion
    assert format_recorded_seconds(value, language, pace=True) == expected


@pytest.mark.parametrize("value", [
    1e308, 1.7976931348623157e308, 1e20, 1e6, 5e-324, 1e-19,
    math.nextafter(1e-18, 0), None, "240", "malformed", True, False,
    0, -1, float("nan"), float("inf"), -float("inf"),
    pytest.param(10 ** 5000, id="oversized-integer"),
])
@pytest.mark.parametrize("language", ["fr", "en", "es"])
def test_unrepresentable_formatter_never_expands_or_fabricates(value, language):
    for pace in (False, True):
        assert format_recorded_seconds(value, language, pace=pace) is None


@pytest.mark.parametrize("kind,field", [("pace", "pace_sec_per_km"), ("duration", "duration_s")])
@pytest.mark.parametrize("value", [
    1e308, 5e-324, "malformed", pytest.param(10 ** 5000, id="oversized-integer"),
])
def test_unrepresentable_measure_excluded_before_assertion_with_independent_fallback(
    monkeypatch, kind, field, value,
):
    v3 = change_row(recorded_case(1), kind, **{field: value})
    other_kind = "duration" if kind == "pace" else "pace"
    first = values(v3)
    assert f"recorded_{kind}" not in first
    assert f"recorded_{other_kind}" in first
    coverage = values(v3, "effort.coverage")
    assert coverage[f"{kind}_count"] == 0
    assert coverage[f"{other_kind}_count"] == 1
    assert coverage["both_count"] == 0
    assert "seule mesure disponible" in effort_facts(v3)["effort.first"].assertion
    packet = json.dumps(_context(v3), allow_nan=False)
    assert "malformed" not in packet and "1e+308" not in packet
    monkeypatch.setenv(hybrid.FEATURE_FLAG, "true")

    async def failed(*args):
        raise RuntimeError("private technical details")

    result = _run(v3, transport=failed)
    assert result.mode == "deterministic_fallback"
    assert result.text and len(result.text) <= hybrid.MAX_COACH_TEXT_CHARS
    assert "private" not in result.text and "None" not in result.text
    assert result.claims[0].id == "effort.first"


@pytest.mark.parametrize("empty", [False, True])
def test_all_measures_excluded_or_no_efforts_keeps_honest_fallback(monkeypatch, empty):
    v3 = synthetic_case("intervals_4x4") if empty else recorded_case(1)
    if not empty:
        v3 = change_row(v3, "pace", pace_sec_per_km=1e308)
        v3 = change_row(v3, "duration", duration_s=5e-324)
    assert not {"effort.first", "effort.last"} & effort_facts(v3).keys()
    if not empty:
        assert values(v3, "effort.coverage") == {
            "recorded_total": 1, "pace_count": 0, "duration_count": 0, "both_count": 0,
        }
    monkeypatch.setenv(hybrid.FEATURE_FLAG, "true")
    result = _run(v3, transport=_provider(lambda *_: "not a selection"))
    assert result.mode == "deterministic_fallback"
    assert result.claims and result.text
    assert len(result.claims) <= 3
    assert "1e+308" not in result.text and "None" not in result.text
    assert all(c.id in {"interval.count", "intensity.position"} for c in result.claims)


@pytest.mark.parametrize("language", ["fr", "en", "es"])
@pytest.mark.parametrize("value", [
    1e-18, math.nextafter(10 ** RECORDED_WHOLE_DIGITS, 0), 59.99999999999999,
    60.00000000000001, 0.12345678901234568,
])
def test_display_boundaries_preserve_exact_precision_and_bound_new_fact_lengths(language, value):
    from decimal import Decimal

    assert RECORDED_WHOLE_DIGITS == 6 and RECORDED_FRACTION_DIGITS == 18
    v3 = recorded_case(2, orders=[999998, 999999])
    for kind, field in (("pace", "pace_sec_per_km"), ("duration", "duration_s")):
        for index in (0, 1):
            v3 = change_row(v3, kind, index, **{field: value, "effort_number": 999998 + index})
    facts = effort_facts(v3, language=language)
    assert len(facts) == 3
    for fact in facts.values():
        assert len(fact.assertion) <= 256
        for form in allowed_forms(fact, language):
            assert len(realize_clause(fact, form, language)) <= 256
    for pace in (False, True):
        text = format_recorded_seconds(value, language, pace=pace)
        assert text is not None and len(text) <= MAX_RECORDED_METRIC_CHARS
        localized = text.replace(",", ".").replace("'", ":")
        if pace:
            minutes, seconds = localized.removesuffix("/km").split(":")
            restored = Decimal(minutes) * 60 + Decimal(seconds)
        elif " min " in localized:
            minutes, seconds = localized.removesuffix(" s").split(" min ")
            restored = Decimal(minutes) * 60 + Decimal(seconds)
        elif localized.endswith(" min"):
            restored = Decimal(localized.removesuffix(" min")) * 60
        else:
            restored = Decimal(localized.removesuffix(" s"))
        assert restored == Decimal(str(value))
    packet = _context(v3, language=language)
    assert len(json.dumps(packet, ensure_ascii=False, allow_nan=False)) < hybrid.MAX_CONTEXT_CHARS
    response = selection(supporting=("effort.last", "effort.coverage"))
    chosen = validate_editorial_selection(response, tuple(facts.values()), language)
    claims = hybrid.realize_editorial_selection(chosen, tuple(facts.values()), language)
    assert len(hybrid._render(claims)) <= 3 * 256 + 2


@pytest.mark.parametrize("field", ["order", "effort_number"])
def test_oversized_identity_never_reaches_integer_string_conversion(field):
    v3 = change_row(recorded_case(1, duration=False), "pace", **{field: 10 ** 5000})
    assert not effort_facts(v3)
    json.dumps(_context(v3), allow_nan=False)


def test_effort_does_not_displace_independent_intensity_with_available_support_slot():
    facts = _facts(recorded_case())
    assert "intensity.position" in {f.id for f in facts}
    assert [c.id for c in hybrid.select_deterministic_synthesis(facts)] == [
        "effort.first", "intensity.position", "effort.last",
    ]
    rich = _facts(
        recorded_case(base=synthetic_case("comparable_history")),
        permissions=hybrid.HybridPermissions(history=True),
    )
    claims = hybrid.select_deterministic_synthesis(rich)
    assert claims[0].id == "effort.first"
    assert claims[1].id.startswith("trend.")
    assert claims[2].id == "intensity.position"


@pytest.mark.parametrize("prescription", [False, True])
def test_historical_comparison_and_prescription_survive_without_new_ranking(prescription):
    v3 = recorded_case(base=synthetic_case("comparable_history"))
    v3.performance_trend.status = "insufficient_data"
    if prescription:
        v3.prescription_assessment.status = "consistent"
    facts = _facts(v3, permissions=hybrid.HybridPermissions(history=True, prescription=prescription))
    claims = hybrid.select_deterministic_synthesis(facts)
    assert len(claims) == 3 and claims[0].id == "effort.first"
    assert claims[1].id.startswith("comparison.")
    assert claims[2].id == ("prescription.review" if prescription else "intensity.position")


def test_above_threshold_observation_kept_instead_of_redundant_effort_coverage():
    v3 = recorded_case()
    v3.intensity_assessment.hr_used_bpm = 180
    v3.intensity_assessment.position = "above_LT2"
    facts = _facts(v3)
    intensity = next(f for f in facts if f.id == "intensity.position")
    assert dict(intensity.values)["position"] == "above_LT2"
    assert "intensity.position" in {c.id for c in hybrid.select_deterministic_synthesis(facts)}


def test_oversized_context_uses_fallback_without_calling_provider(monkeypatch):
    monkeypatch.setenv(hybrid.FEATURE_FLAG, "true")
    v3 = recorded_case()
    size = len(json.dumps(_context(v3), ensure_ascii=False, allow_nan=False))

    async def forbidden(*args):
        pytest.fail("oversized context must not reach provider")

    monkeypatch.setattr(hybrid, "MAX_CONTEXT_CHARS", size - 1)
    result = _run(v3, transport=forbidden)
    assert result.mode == "deterministic_fallback" and result.reason == "context_size_limit"
    assert result.text and not result.provider_attempted
    monkeypatch.setattr(hybrid, "MAX_CONTEXT_CHARS", size)
    assert _run(v3, transport=_provider(lambda *_: selection())).mode == "editorial_realization"


def test_coach_text_budget_rejects_whole_editorial_output_and_preserves_fallback_clauses(monkeypatch):
    facts = _facts(recorded_case())
    first = next(f for f in facts if f.id == "effort.first")
    oversized = replace(first, assertion="x" * (hybrid.MAX_COACH_TEXT_CHARS + 1))
    bounded = hybrid.select_deterministic_synthesis(tuple(oversized if f is first else f for f in facts))
    assert bounded and first.id not in {c.id for c in bounded}
    assert len(hybrid._render(bounded)) <= hybrid.MAX_COACH_TEXT_CHARS
    assert all(c.text == next(f.assertion for f in facts if f.id == c.id) for c in bounded)
    clause = selection()
    chosen = validate_editorial_selection(clause, facts, "fr")
    monkeypatch.setattr(hybrid, "MAX_COACH_TEXT_CHARS", len(first.assertion) - 1)
    with pytest.raises(ValueError, match="realization_size_limit"):
        hybrid.realize_editorial_selection(chosen, facts, "fr")


def test_existing_provider_response_length_guard_still_rejects_without_echo(monkeypatch):
    monkeypatch.setenv(hybrid.FEATURE_FLAG, "true")
    result = _run(recorded_case(), transport=_provider(lambda *_: "x" * (hybrid.MAX_RESPONSE_CHARS + 1)))
    assert result.mode == "deterministic_fallback"
    assert result.reason == "transport_response_limit"
    assert result.text and "xxxx" not in result.text


def test_no_phases_legacy_unchanged():
    v3 = synthetic_case("intervals_4x4")
    assert not effort_facts(v3)
    assert [c.id for c in hybrid.select_deterministic_synthesis(_facts(v3))] == [
        "interval.count", "intensity.position",
    ]


def test_no_duplicate_total_and_two_support_limit():
    facts = _facts(recorded_case())
    with pytest.raises(ValueError, match="redundant_selection"):
        validate_editorial_selection(selection(supporting=("effort.coverage", "interval.count")), facts, "fr")
    with pytest.raises(ValueError):
        validate_editorial_selection(selection(supporting=("effort.last", "effort.coverage", "interval.count")), facts, "fr")
    claims = hybrid.select_deterministic_synthesis(facts)
    assert len(claims) <= 3 and claims[0].id == "effort.first"
    assert not {"effort.coverage", "interval.count"} <= {c.id for c in claims}


@pytest.mark.parametrize("payload", [
    selection("unknown-id"), selection("fatigue"), selection("regularity"),
    selection("progress"), selection(text="You improved because fatigue disappeared"),
    selection(value=999), selection(primary="recorded_effort_pace:1"),
    json.dumps({"primary": {"fact_id": "effort.first", "form": "rounded"},
                "supporting": [], "editorial_intent": "describe_session"}),
    json.dumps({"primary": {"fact_id": "effort.first", "form": "direct", "text": "regular efforts"},
                "supporting": [], "editorial_intent": "describe_session"}),
])
def test_unknown_ids_injected_values_and_inferences_fall_back(monkeypatch, payload):
    monkeypatch.setenv(hybrid.FEATURE_FLAG, "true")
    result = _run(recorded_case(), transport=_provider(lambda *_: payload))
    assert result.mode == "deterministic_fallback"
    assert result.reason == "invalid_editorial_selection"
    assert result.claims[0].id == "effort.first" and len(result.claims) <= 3
    assert "999" not in result.text and "fatigue" not in result.text


@pytest.mark.parametrize("base", ["long", "comparable_history"])
def test_historical_and_prescription_admissions_preserved_in_fallback(monkeypatch, base):
    permissions = hybrid.HybridPermissions(history=True, prescription=True)
    v3 = recorded_case(base=synthetic_case(base))
    v3 = v3.model_copy(update={"prescription_assessment": WIV3PrescriptionAssessment(status="consistent")})
    facts = _facts(v3, permissions=permissions)
    claims = hybrid.select_deterministic_synthesis(facts)
    assert len(claims) == 3
    assert claims[0].id == "effort.first"
    assert claims[1].id.startswith(("trend.", "comparison.")) or claims[1].id == "session.long"
    assert claims[2].id == "prescription.review"
    unauthorized = {f.id for f in _facts(v3)}
    assert "prescription.review" not in unauthorized
    assert not any(id.startswith(("trend.", "comparison.")) for id in unauthorized)
    monkeypatch.setenv(hybrid.FEATURE_FLAG, "true")

    async def failed(*args):
        raise RuntimeError("private provider failure")

    result = _run(v3, transport=failed, permissions=permissions)
    assert result.mode == "deterministic_fallback"
    assert [c.id for c in result.claims] == [c.id for c in claims]
    assert "private" not in result.text


def test_isolation_no_mutation_flag_default_and_injected_transport(monkeypatch):
    v3 = recorded_case()
    original = deepcopy(v3.model_dump())
    called = []

    async def transport(system, prompt, user, context_type):
        called.append(json.loads(prompt))
        assert user == "anonymous"
        assert "synthetic-owner" not in prompt
        return selection(), True, {}

    assert _run(v3, transport=transport).mode == "disabled"
    assert called == []
    monkeypatch.setenv(hybrid.FEATURE_FLAG, "true")
    result = _run(v3, transport=transport)
    assert result.mode == "editorial_realization" and len(called) == 1
    assert v3.model_dump() == original
    assert _context(recorded_case()) == _context(v3)
    other = UserAccess(user_id="another-isolated-user", tier=_access().tier)
    assert _context(v3, access=other) == _context(v3)
    assert not effort_facts(synthetic_case())
    assert hybrid.build_admissible_facts(v3, access=None) == ()
    assert _access().user_id not in json.dumps(called)
