"""Synthetic Garmin producer → workout projection → V3, with read-only doubles."""

import asyncio
import socket
import subprocess
from copy import deepcopy
from types import SimpleNamespace

import pytest

from garmin.providers.gccli_provider import GccliProvider
from garmin.service import activity_to_workout
import workout_intelligence_v3_service as v3_service
from workout_analysis_v2_service import _historical_garmin_sources
from workout_intelligence_v3_service import load_scoped_workout_intelligence_v3


class ReadOnlyCollection:
    def __init__(self, docs):
        self.docs = docs
        self.queries = []

    @staticmethod
    def matches(doc, query):
        for key, expected in query.items():
            value = doc.get(key)
            if isinstance(expected, dict):
                if "$in" in expected and value not in expected["$in"]:
                    return False
                if "$gte" in expected and (value is None or value < expected["$gte"]):
                    return False
                if "$lt" in expected and (value is None or value >= expected["$lt"]):
                    return False
            elif value != expected:
                return False
        return True

    @staticmethod
    def project(doc, projection):
        if not any(projection.values()):
            return deepcopy(doc)
        result = {}
        for path, included in projection.items():
            if not included:
                continue
            source, target = doc, result
            parts = path.split(".")
            for part in parts[:-1]:
                source = source.get(part)
                if not isinstance(source, dict):
                    break
                target = target.setdefault(part, {})
            else:
                if parts[-1] in source:
                    target[parts[-1]] = deepcopy(source[parts[-1]])
        return result

    def find(self, query, projection):
        self.queries.append((deepcopy(query), deepcopy(projection)))
        return Cursor([
            self.project(doc, projection) for doc in self.docs if self.matches(doc, query)
        ])

    async def find_one(self, query, projection):
        cursor = self.find(query, projection)
        return cursor.docs[0] if cursor.docs else None


class Cursor:
    def __init__(self, docs):
        self.docs = docs

    def sort(self, key, direction):
        self.docs.sort(key=lambda doc: doc[key], reverse=direction < 0)
        return self

    async def to_list(self, length=None):
        return self.docs[:length]


def source(activity_id, day, maximum=180, *, user_id="synthetic-user"):
    normalized = GccliProvider._normalize({
        "activityId": activity_id,
        "activityName": "Synthetic run",
        "activityType": {"typeKey": "running"},
        "startTimeLocal": f"{day}T08:00:00",
        "startTimeGMT": f"{day}T08:00:00",
        "distance": 10000,
        "duration": 3600,
        "averageHR": 145,
        "maxHR": maximum,
        "averageSpeed": 10000 / 3600,
    })
    return {**normalized, "user_id": user_id}


def database(maximum=180):
    activities = [
        source(101, "2026-10-01", maximum),
        source(102, "2026-10-10", 190),
    ]
    return SimpleNamespace(
        workouts=ReadOnlyCollection([
            activity_to_workout(activity, activity["user_id"]) for activity in activities
        ]),
        garmin_activities=ReadOnlyCollection(activities),
    )


def load(db, **kwargs):
    result = asyncio.run(load_scoped_workout_intelligence_v3(
        db=db, user_id="synthetic-user", workout_id="garmin-102", language="en",
        **kwargs,
    ))
    assert result is not None and result[1] is not None
    return result[1]


@pytest.fixture(autouse=True)
def no_external_access(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("External access is forbidden in these synthetic tests")

    monkeypatch.setattr(socket.socket, "connect", forbidden)
    monkeypatch.setattr(subprocess, "Popen", forbidden)


@pytest.fixture
def captured_input(monkeypatch):
    captured = []
    original = v3_service.extract_workout_intelligence_input

    def extract(*args, **kwargs):
        data = original(*args, **kwargs)
        captured.append(data)
        return data

    monkeypatch.setattr(v3_service, "extract_workout_intelligence_input", extract)
    return captured


def test_source_maximum_reaches_historical_v3_without_product_copy(captured_input):
    db = database()
    before = deepcopy((db.workouts.docs, db.garmin_activities.docs))
    assert db.garmin_activities.docs[0]["garmin_activity"]["max_hr"] == 180
    assert "max_heart_rate" not in db.workouts.docs[0]
    assert "max_hr" not in db.workouts.docs[0]

    intensity = load(db).intensity_assessment

    assert intensity.observed_max_hr_bpm == 180
    assert intensity.observed_max_hr_observation_count == 1
    assert intensity.fcmax_bpm is None
    assert intensity.position == "unknown"
    assert intensity.lt1 is None and intensity.lt2 is None
    assert (db.workouts.docs, db.garmin_activities.docs) == before
    observed = captured_input[0].profile.observed_max_hr
    assert observed.value_bpm == 180
    assert observed.source == "garmin_activities_strictly_prior"
    assert observed.kind == "observed_maximum_lower_bound"
    assert captured_input[0].history[0].max_hr == 180
    group_queries = [
        (query, projection) for query, projection in db.garmin_activities.queries
        if isinstance(query.get("external_id"), dict)
    ]
    assert len(group_queries) == 1
    assert group_queries[0][0]["user_id"] == "synthetic-user"
    assert group_queries[0][1]["garmin_activity.max_hr"] == 1
    assert group_queries[0][1]["source"] == 1


@pytest.mark.parametrize("maximum,expected", [
    (None, None), (0, None), (-1, None), (True, None), (False, None),
    (float("nan"), None), (float("inf"), None), ("bad", None),
    (149, None), (231, None), ("180", 180),
])
def test_source_maximum_uses_existing_validation_and_credibility(maximum, expected):
    db = database()
    db.garmin_activities.docs[0]["garmin_activity"]["max_hr"] = maximum
    intensity = load(db).intensity_assessment
    assert intensity.observed_max_hr_bpm == expected
    assert intensity.observed_max_hr_observation_count == (0 if expected is None else 1)
    assert intensity.fcmax_bpm is None
    assert intensity.fcmax_source == "unavailable"
    assert intensity.position == "unknown"
    assert intensity.lt1 is None and intensity.lt2 is None


@pytest.mark.parametrize("existing,expected", [
    ({"max_heart_rate": 175}, 175),
    ({"max_hr": 175}, 175),
    ({"max_heart_rate": 175, "max_hr": 185}, 175),
    ({"max_heart_rate": None, "max_hr": 175}, 175),
    ({"max_heart_rate": 0, "max_hr": 175}, 175),
    ({"max_heart_rate": 0}, None),
    ({"max_hr": False}, None),
    ({"max_heart_rate": "bad"}, None),
    ({"max_heart_rate": None, "max_hr": None}, 180),
])
def test_existing_workout_maximum_aliases_are_never_replaced(existing, expected):
    db = database()
    db.workouts.docs[0].update(existing)
    before = deepcopy(db.workouts.docs)
    assert load(db).intensity_assessment.observed_max_hr_bpm == expected
    assert db.workouts.docs == before


@pytest.mark.parametrize("fields,expected", [
    ({"max_heart_rate": 175, "max_hr": 185}, 175),
    ({"max_heartrate": 175, "maxHR": 185}, 175),
    ({"max_hr": 175}, 175),
    ({"max_heart_rate": 0}, 180),
])
def test_source_alias_priority_matches_existing_current_enrichment(fields, expected):
    db = database()
    db.garmin_activities.docs[0].update(fields)
    assert load(db).intensity_assessment.observed_max_hr_bpm == expected


@pytest.mark.parametrize("mode", ["absent", "ambiguous", "other-source", "no-source"])
def test_unproven_source_maximum_is_not_used(mode):
    db = database()
    if mode == "absent":
        db.garmin_activities.docs.pop(0)
    elif mode == "ambiguous":
        db.garmin_activities.docs.append(deepcopy(db.garmin_activities.docs[0]))
    elif mode == "other-source":
        db.garmin_activities.docs[0]["source"] = "manual"
    else:
        db.garmin_activities.docs[0].pop("source")
    assert load(db).intensity_assessment.observed_max_hr_bpm is None


def test_user_isolation_includes_colliding_external_ids(captured_input):
    db = database()
    other_user = source(101, "2026-10-01", 225, user_id="another-user")
    db.garmin_activities.docs.append(other_user)
    db.workouts.docs.append(activity_to_workout(other_user, other_user["user_id"]))
    assert load(db).intensity_assessment.observed_max_hr_bpm == 180
    assert len(captured_input[0].history) == 1
    assert all(query["user_id"] == "synthetic-user"
               for query, _ in db.garmin_activities.queries + db.workouts.queries)
    db.garmin_activities.docs.pop(0)
    assert load(db).intensity_assessment.observed_max_hr_bpm is None


def test_prior_only_cutoff_ignores_current_equal_and_future(captured_input):
    db = database()
    for activity_id, timestamp in [
        (103, "2026-10-10T07:59:59"),
        (104, "2026-10-10T08:00:00"),
        (105, "2026-10-10T08:00:01"),
        (106, "2026-10-11T08:00:00"),
    ]:
        activity = source(activity_id, "2026-10-10", 220)
        activity["start_time"] = timestamp
        db.garmin_activities.docs.append(activity)
        db.workouts.docs.append(activity_to_workout(activity, activity["user_id"]))
    load(db)
    data = captured_input[0]
    assert {item.id for item in data.history} == {"garmin-101", "garmin-103"}
    assert data.profile.observed_max_hr.observation_count == 2


def test_numeric_external_id_matches_without_name_fallback():
    db = database()
    db.garmin_activities.docs[0]["external_id"] = 101
    assert load(db).intensity_assessment.observed_max_hr_bpm == 180
    db.garmin_activities.docs[0]["external_id"] = "unrelated-id"
    assert load(db).intensity_assessment.observed_max_hr_bpm is None


def test_non_garmin_workout_does_not_gain_a_garmin_maximum(captured_input):
    db = database()
    db.workouts.docs[0].update({"id": "manual-101", "data_source": "manual"})
    assert load(db).intensity_assessment.observed_max_hr_bpm is None
    assert captured_input[0].history[0].max_hr is None


def test_unreadable_historical_sources_degrade_without_fabricating(monkeypatch):
    db = database()
    find = db.garmin_activities.find

    def unavailable(query, projection):
        if isinstance(query.get("external_id"), dict):
            raise RuntimeError("Synthetic read failure")
        return find(query, projection)

    monkeypatch.setattr(db.garmin_activities, "find", unavailable)
    assert load(db).intensity_assessment.observed_max_hr_bpm is None


def test_existing_comparison_guard_consumes_the_recovered_maximum():
    db = database(maximum=140)
    result = load(db)
    assert result.historical_comparison.exclusion_reasons["missing_or_aberrant_hr"] == 1


def test_v2_receives_original_history_while_v3_receives_only_copies(monkeypatch):
    db = database()
    original = v3_service.build_workout_analysis_v2
    inputs = []
    results = []

    def build(**kwargs):
        inputs.append((kwargs["historical_workouts"], deepcopy(kwargs["historical_workouts"])))
        result = original(**kwargs)
        results.append(result.model_dump())
        return result

    monkeypatch.setattr(v3_service, "build_workout_analysis_v2", build)
    first = load(db)
    assert inputs[0][0] == inputs[0][1]
    assert all("max_heart_rate" not in item for item in inputs[0][0])
    db.garmin_activities.docs[0]["garmin_activity"]["max_hr"] = None
    second = load(db)
    assert inputs[0][0] == inputs[1][0]
    assert results[0] == results[1]
    assert first.intensity_assessment.observed_max_hr_bpm == 180
    assert second.intensity_assessment.observed_max_hr_bpm is None


def test_declared_fcmax_is_preserved_separately_from_observed_lower_bound():
    intensity = load(database(), user_profile={"max_hr": 195}).intensity_assessment
    assert intensity.fcmax_bpm == 195
    assert intensity.fcmax_source == "user_declared"
    assert intensity.observed_max_hr_bpm == 180
    assert intensity.position == "unknown"
    assert intensity.lt1 is None and intensity.lt2 is None


def test_v2_default_source_reader_keeps_its_existing_projection_and_contract():
    db = database()
    result = asyncio.run(_historical_garmin_sources(
        db, "synthetic-user", db.workouts.docs[:1],
    ))
    assert isinstance(result, tuple) and len(result) == 2
    assert db.garmin_activities.queries[0][1] == {
        "_id": 0, "external_id": 1, "activity_details": 1,
        "activity_type": 1, "garmin_activity.activity_type": 1,
    }
