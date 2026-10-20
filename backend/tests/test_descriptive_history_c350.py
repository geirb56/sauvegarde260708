"""C350 correction — descriptive history without proven structure.

Synthetic fixtures only. A distance-only description of the average is admitted
when the current structure is unknown, provided the precise Garmin activity type
is known and identical; strong history, km pacing and repetition judgments still
require a proven structure.
"""

import asyncio
import re
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from activity_phases import ActivityPhase
from workout_analysis_v2 import (
    WorkoutAnalysisV2Response,
    _build_similar_reference,
    build_workout_analysis_v2,
)
from workout_analysis_v2_service import _reliable_activity_type, load_scoped_workout_analysis_v2

LANGUAGES = ("fr", "en", "es")
CAVEAT = {
    "fr": "sans garantie de même nature ni de même structure",
    "en": "without any guarantee of the same nature or structure",
    "es": "sin garantía de que sean de la misma naturaleza ni de la misma estructura",
}
FORBIDDEN = re.compile(
    r"progr|fatigu|dérive|drift|deriva|bonne|mauvaise|good|bad|buena|mala|"
    r"bien|mal |well|poor|amélior|improv|mejor|forme|fitness",
    re.IGNORECASE,
)


def current(**changes):
    """12/10 shape: 9.33 km, no phases, no recorded structure."""
    base = dict(id="garmin-24701222152", name="Course à pied", date="2026-10-12", type="run",
                distance_km=9.33, duration_minutes=68.6, avg_pace_min_km=7.35,
                avg_heart_rate=127, data_source="garmin")
    base.update(changes)
    return base


def reference(index, **changes):
    base = dict(id=f"garmin-{100 + index}", name="Run", date=f"2026-10-0{index}", type="run",
                distance_km=9.0, duration_minutes=63.0, avg_pace_min_km=7.0,
                avg_heart_rate=130, data_source="garmin")
    base.update(changes)
    return base


def refs(count=5, **changes):
    return [reference(index, **changes) for index in range(1, count + 1)]


def types_for(workout, history, current_type="running", reference_type="running"):
    types = {ref["id"]: reference_type for ref in history}
    if current_type is not None:
        types[workout["id"]] = current_type
    return types


def analyze(workout, history, language="en", phases=None, types=None, **kwargs):
    return build_workout_analysis_v2(workout, history, language, phases,
                                     activity_types=types, **kwargs)


def history_items(analysis):
    return [item for item in analysis.coach_language.conclusions if item.category == "history"]


# 1. 12/10: five reliable references, no proven structure -> one descriptive observation.
@pytest.mark.parametrize("language", LANGUAGES)
def test_12_10_gets_one_descriptive_history_observation(language):
    workout, history = current(), refs()
    analysis = analyze(workout, history, language, types=types_for(workout, history))
    assert analysis.signals.session_structure.available is False
    similar = analysis.comparison.similar
    assert similar.sample_count == 5 and similar.pace_comparability == "distance_only"
    items = history_items(analysis)
    assert len(items) == 1
    item = items[0]
    assert item.code == "coach.history.pace" and item.kind == "descriptive"
    assert item.metadata == {"population": "pace_only", "comparability": "distance_only",
                             "session_structure": "unknown"}
    assert item.priority == 50
    # Figures match the similar reference exactly, in every language.
    assert item.evidence["pace_sample_count"] == similar.pace_sample_count == 5
    assert item.evidence["baseline_pace_min_km"] == similar.avg_pace_min_km == 7.0
    assert item.evidence["pace_difference_sec_per_km"] == pytest.approx(21.0)
    assert "21" in item.text and "5" in item.text
    assert CAVEAT[language] in item.text
    assert not FORBIDDEN.search(item.text)
    # No regularity or pacing judgment without proven structure.
    assert {i.category for i in analysis.coach_language.conclusions} == {"history"}


@pytest.mark.parametrize("language", LANGUAGES)
def test_descriptive_hr_figures_are_consistent(language):
    workout, history = current(avg_pace_min_km=None), refs(avg_pace_min_km=None)
    items = history_items(analyze(workout, history, language, types=types_for(workout, history)))
    assert [item.code for item in items] == ["coach.history.hr"]
    item = items[0]
    assert item.kind == "descriptive"
    assert item.evidence["current_heart_rate_bpm"] == 127
    assert item.evidence["baseline_heart_rate_bpm"] == 130
    assert item.evidence["heart_rate_difference_bpm"] == -3
    assert "127" in item.text and "130" in item.text
    assert CAVEAT[language] in item.text
    assert not FORBIDDEN.search(item.text)


def test_known_identical_nature_is_still_capped_to_descriptive_without_structure():
    workout, history = current(is_race=False), refs(is_race=False, session_structure="continuous")
    analysis = analyze(workout, history, types=types_for(workout, history))
    assert analysis.comparison.similar.pace_comparability == "strong"
    assert analysis.comparison.similar.pace_structure_status == "continuous_recorded"
    items = history_items(analysis)
    assert [(i.kind, i.metadata["comparability"]) for i in items] == [("descriptive", "distance_only")]


# 2. 19/10 treadmill: never compared with outdoor runs, never with unknown types.
@pytest.mark.parametrize("language", LANGUAGES)
@pytest.mark.parametrize("current_type, reference_type", [
    ("treadmill_running", "running"),
    ("running", "treadmill_running"),
    (None, "running"),
    ("treadmill_running", None),
])
def test_treadmill_and_outdoor_are_never_compared(language, current_type, reference_type):
    workout = current(id="garmin-24781607161", date="2026-10-19", name="Course à pied")
    history = refs()
    types = types_for(workout, history, current_type, reference_type)
    if reference_type is None:
        types = {key: value for key, value in types.items() if key == workout["id"]}
    analysis = analyze(workout, history, language, types=types)
    assert history_items(analysis) == []


def test_one_reference_of_another_type_blocks_the_metric():
    workout, history = current(), refs()
    types = types_for(workout, history)
    types[history[3]["id"]] = "treadmill_running"
    assert history_items(analyze(workout, history, types=types)) == []


def test_treadmill_name_never_sets_the_type():
    workout = current(name="Tapis de course")
    history = refs(name="Course à pied")
    assert history_items(analyze(workout, history, types={})) == []


def test_19_10_without_reference_stays_silent():
    workout = current(id="garmin-24781607161", date="2026-10-19", distance_km=5.0,
                      duration_minutes=35.0, avg_pace_min_km=7.0, avg_heart_rate=125)
    analysis = analyze(workout, [], types={workout["id"]: "treadmill_running"})
    assert analysis.comparison.similar.available is False
    assert analysis.coach_language.conclusions == []


def test_treadmill_against_treadmill_is_described():
    workout, history = current(), refs()
    types = types_for(workout, history, "treadmill_running", "treadmill_running")
    assert [i.kind for i in history_items(analyze(workout, history, types=types))] == ["descriptive"]


# 3. Intervals without phases: no strong conclusion, no regularity judgment.
KM_SPLITS = [{"km": index, "pace_min_km": pace, "avg_hr": 120 + index}
             for index, pace in enumerate((6.0, 8.5, 6.0, 8.5, 6.0, 8.5, 6.0, 8.5, 6.0), 1)]


def test_intervals_without_phases_get_no_strong_or_regularity_judgment():
    workout = current(km_splits=KM_SPLITS, is_race=False)
    history = refs(is_race=False, session_structure="continuous")
    analysis = analyze(workout, history, types=types_for(workout, history))
    categories = [item.category for item in analysis.coach_language.conclusions]
    assert "pacing" not in categories and "execution" not in categories
    assert "repetitions" not in categories
    assert all(item.kind == "descriptive" and item.metadata["comparability"] == "distance_only"
               for item in history_items(analysis))


def test_explicitly_recorded_intervals_abstain():
    workout = current(session_structure="intervals")
    history = refs()
    assert history_items(analyze(workout, history, types=types_for(workout, history))) == []


def test_known_interval_or_other_phases_abstain():
    workout, history = current(distance_km=6.0, duration_minutes=40.0), refs(distance_km=6.0)
    intervals = [ActivityPhase(order=0, phase_type="effort", duration_s=300, distance_m=1000,
                               source="garmin"),
                 ActivityPhase(order=1, phase_type="recovery", duration_s=120, distance_m=300,
                               source="garmin"),
                 ActivityPhase(order=2, phase_type="effort", duration_s=300, distance_m=1000,
                               source="garmin")]
    other = [ActivityPhase(order=0, phase_type="warmup", duration_s=600, distance_m=1500,
                           source="garmin")]
    for phases in (intervals, other):
        analysis = analyze(workout, history, phases=phases, types=types_for(workout, history))
        assert analysis.signals.session_structure.code in {"intervals", "other"}
        assert history_items(analysis) == []


# 4. Insufficient references or missing metrics: abstention.
@pytest.mark.parametrize("history_changes, workout_changes", [
    ({}, {"avg_pace_min_km": None, "avg_heart_rate": None}),
    ({"avg_pace_min_km": None, "avg_heart_rate": None}, {}),
    ({"distance_km": 4.0}, {}),
    ({"type": "cycle"}, {}),
])
def test_missing_metrics_or_incomparable_distances_abstain(history_changes, workout_changes):
    workout, history = current(**workout_changes), refs(**history_changes)
    assert history_items(analyze(workout, history, types=types_for(workout, history))) == []


def test_single_reference_abstains():
    workout, history = current(), refs(count=1)
    assert history_items(analyze(workout, history, types=types_for(workout, history))) == []


def test_race_with_unknown_nature_abstains():
    workout, history = current(is_race=True), refs()
    assert history_items(analyze(workout, history, types=types_for(workout, history))) == []


def test_metric_separation_is_preserved():
    """Two pace-only and two HR-only references: each metric on its own population."""
    workout = current()
    history = [reference(1, avg_heart_rate=None), reference(2, avg_heart_rate=None),
               reference(3, avg_pace_min_km=None), reference(4, avg_pace_min_km=None)]
    types = types_for(workout, history)
    # A foreign type in the HR population does not block pace.
    types[history[3]["id"]] = "treadmill_running"
    items = history_items(analyze(workout, history, types=types))
    assert [item.code for item in items] == ["coach.history.pace"]
    assert items[0].evidence["pace_sample_count"] == 2
    # And the reverse: blocked pace leaves HR admissible.
    types = types_for(workout, history)
    types[history[0]["id"]] = "treadmill_running"
    items = history_items(analyze(workout, history, types=types))
    assert [item.code for item in items] == ["coach.history.hr"]
    assert items[0].evidence["hr_sample_count"] == 2


# 5. Non-regression: contract unchanged, proven continuous path unchanged.
def test_contract_keys_unchanged():
    workout, history = current(), refs()
    payload = analyze(workout, history, types=types_for(workout, history)).model_dump()
    assert set(payload) == set(WorkoutAnalysisV2Response.model_fields)
    assert "activity_types" not in str(payload) and "environment" not in str(payload)
    assert set(payload["comparison"]["similar"]) == set(
        _build_similar_reference(workout, history, "en").model_dump()
    )


def test_proven_continuous_strong_history_unaffected_by_missing_types():
    workout = current(is_race=False, session_structure="continuous")
    history = refs(is_race=False, session_structure="continuous")
    items = history_items(analyze(workout, history))
    assert [(i.kind, i.metadata["comparability"], i.metadata["session_structure"])
            for i in items] == [("conclusion", "strong", "continuous")]


# 6. Service: precise Garmin type read only from the source document.
@pytest.mark.parametrize("doc, expected", [
    ({"activity_type": "running"}, "running"),
    ({"activity_type": "Treadmill_Running"}, "treadmill_running"),
    ({"garmin_activity": {"activity_type": "running"}}, "running"),
    ({"activity_type": "running", "garmin_activity": {"activity_type": "running"}}, "running"),
    ({"activity_type": "running", "garmin_activity": {"activity_type": "treadmill_running"}}, None),
    ({"activity_type": ""}, None),
    ({"activity_type": 3}, None),
    ({"name": "Tapis"}, None),
    (None, None),
])
def test_reliable_activity_type(doc, expected):
    assert _reliable_activity_type(doc) == expected


class Cursor:
    def __init__(self, docs):
        self.docs = docs

    def sort(self, *_):
        return self

    async def to_list(self, **_):
        return self.docs


def run_service(workout, activity, history, reference_type):
    docs = [{"external_id": ref["id"][len("garmin-"):], "activity_type": reference_type}
            for ref in history]
    db = SimpleNamespace(
        workouts=SimpleNamespace(find_one=AsyncMock(return_value=workout),
                                 find=lambda *_: Cursor(history)),
        garmin_activities=SimpleNamespace(find_one=AsyncMock(return_value=activity),
                                          find=lambda *_: Cursor(docs)),
    )
    return asyncio.run(load_scoped_workout_analysis_v2(
        db=db, user_id="synthetic", workout_id=workout["id"], language="fr",
    ))[1]


def test_service_12_10_end_to_end_descriptive():
    workout = current()
    activity = {"user_id": "synthetic", "external_id": "24701222152", "activity_type": "running"}
    analysis = run_service(workout, activity, refs(), "running")
    items = history_items(analysis)
    assert [(i.code, i.kind) for i in items] == [("coach.history.pace", "descriptive")]
    assert CAVEAT["fr"] in items[0].text


def test_service_19_10_treadmill_against_outdoor_is_silent():
    workout = current(id="garmin-24781607161", date="2026-10-19")
    activity = {"user_id": "synthetic", "external_id": "24781607161",
                "activity_type": "treadmill_running"}
    assert history_items(run_service(workout, activity, refs(), "running")) == []
