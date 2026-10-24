"""Synthetic Garmin producer → workout projection → V3, with read-only doubles."""

import asyncio
from copy import deepcopy
from types import SimpleNamespace

from garmin.providers.gccli_provider import GccliProvider
from garmin.service import activity_to_workout
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


def load(db):
    result = asyncio.run(load_scoped_workout_intelligence_v3(
        db=db, user_id="synthetic-user", workout_id="garmin-102", language="en",
    ))
    assert result is not None and result[1] is not None
    return result[1]


def test_source_maximum_reaches_historical_v3_without_product_copy():
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
