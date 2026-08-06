"""PR04 — Tests for GarminCapabilities as single source of truth.

Verifies:
1. Payloads vides → False, pas d'exception
2. Faux positifs null → False
3. Valeurs réelles → True
4. Persistance multi-utilisateur
5. Source unique (from_probe est le seul point de décision)
6. Aucun nouvel appel gccli massif dans la boucle quotidienne
"""

from __future__ import annotations

import asyncio
import inspect
from unittest.mock import AsyncMock, MagicMock

import pytest

from garmin.data_layer import GarminCapabilities
import garmin.service as garmin_service
import garmin.runner as garmin_runner


# --------------------------------------------------------------------------- #
# 1. Payloads vides
# --------------------------------------------------------------------------- #

def test_empty_dict_yields_all_false():
    c = GarminCapabilities.from_probe(hrv={})
    assert c.has_hrv is False


def test_empty_list_yields_false():
    c = GarminCapabilities.from_probe(max_metrics=[], training_readiness=[])
    assert c.has_vo2max is False
    assert c.has_training_readiness is False


def test_none_payload_yields_false():
    c = GarminCapabilities.from_probe(
        hrv=None, max_metrics=None, training_readiness=None,
        training_status=None, body_battery=None, stress=None,
        activity_summary=None, activity_details=None, race_predictions=None,
    )
    assert c.has_hrv is False
    assert c.has_vo2max is False
    assert c.has_training_readiness is False
    assert c.has_training_status is False
    assert c.has_body_battery is False
    assert c.has_stress is False
    assert c.has_running_dynamics is False
    assert c.has_power is False
    assert c.has_race_predictions is False


def test_empty_payloads_no_exception():
    """Aucune exception sur des payloads dégénérés."""
    for payload in ({}, [], None, "", 0, False, "garbage"):
        c = GarminCapabilities.from_probe(
            hrv=payload, max_metrics=payload, training_readiness=payload,
            training_status=payload, body_battery=payload, stress=payload,
        )
        assert isinstance(c, GarminCapabilities)


# --------------------------------------------------------------------------- #
# 2. Faux positifs null
# --------------------------------------------------------------------------- #

def test_vo2max_null_value_is_false():
    c = GarminCapabilities.from_probe(max_metrics=[{"vo2MaxValue": None}])
    assert c.has_vo2max is False


def test_training_readiness_null_score_is_false():
    c = GarminCapabilities.from_probe(training_readiness=[{"score": None}])
    assert c.has_training_readiness is False


def test_race_predictions_null_times_is_false():
    c = GarminCapabilities.from_probe(
        race_predictions={"time5K": None, "time10K": None}
    )
    assert c.has_race_predictions is False


def test_training_status_all_null_is_false():
    c = GarminCapabilities.from_probe(
        training_status={
            "mostRecentVO2Max": None,
            "mostRecentTrainingStatus": None,
        }
    )
    assert c.has_training_status is False


def test_hrv_empty_summary_is_false():
    c = GarminCapabilities.from_probe(hrv={"hrvSummary": {}})
    assert c.has_hrv is False


def test_stress_negative_sentinel_is_false():
    # Garmin uses -1/-2 as "no measurement"
    c = GarminCapabilities.from_probe(stress={"avgStressLevel": -1})
    assert c.has_stress is False


# --------------------------------------------------------------------------- #
# 3. Valeurs réelles → True
# --------------------------------------------------------------------------- #

def test_hrv_real_value_is_true():
    c = GarminCapabilities.from_probe(hrv={"hrvSummary": {"lastNightAvg": 61}})
    assert c.has_hrv is True


def test_hrv_weekly_avg_is_true():
    c = GarminCapabilities.from_probe(hrv={"hrvSummary": {"weeklyAvg": 55}})
    assert c.has_hrv is True


def test_vo2max_real_value_is_true():
    c = GarminCapabilities.from_probe(max_metrics=[{"vo2MaxValue": 52.5}])
    assert c.has_vo2max is True


def test_training_readiness_real_score_is_true():
    c = GarminCapabilities.from_probe(training_readiness=[{"score": 72}])
    assert c.has_training_readiness is True


def test_training_status_real_value_is_true():
    c = GarminCapabilities.from_probe(
        training_status={"mostRecentVO2Max": 52.0, "mostRecentTrainingStatus": "PRODUCTIVE"}
    )
    assert c.has_training_status is True


def test_body_battery_real_value_is_true():
    c = GarminCapabilities.from_probe(body_battery=75)
    assert c.has_body_battery is True


def test_stress_real_value_is_true():
    c = GarminCapabilities.from_probe(stress={"avgStressLevel": 35})
    assert c.has_stress is True


def test_power_real_value_is_true():
    c = GarminCapabilities.from_probe(
        activity_summary={"metadataDTO": {"hasPowerTimeInZones": True}}
    )
    assert c.has_power is True


def test_race_predictions_real_value_is_true():
    c = GarminCapabilities.from_probe(
        race_predictions={"time5K": 1350, "time10K": 2800}
    )
    assert c.has_race_predictions is True


# --------------------------------------------------------------------------- #
# 4. Persistance multi-utilisateur
# --------------------------------------------------------------------------- #

def _make_db(docs_by_user: dict) -> MagicMock:
    """Build a mock MongoDB db that returns per-user documents."""
    db = MagicMock()

    async def find_one_side_effect(query, projection=None, sort=None):
        user_id = query.get("user_id")
        docs = docs_by_user.get(user_id, [])
        # Find by the key present in the query (hrv, body_battery, stress, connected…)
        for key in ("hrv", "body_battery", "stress", "connected"):
            if key in query:
                cond = query[key]
                for doc in docs:
                    if key == "connected":
                        if doc.get(key) == cond:
                            return doc
                    elif isinstance(cond, dict) and "$ne" in cond:
                        if doc.get(key) is not None:
                            return doc
                return None
        # garmin_connections lookup (no metric filter)
        return docs[0] if docs else None

    db.garmin_daily_metrics.find_one = find_one_side_effect
    db.garmin_connections.find_one = find_one_side_effect

    updates = []

    async def update_one_side_effect(filt, update, upsert=False):
        updates.append((filt, update))
        result = MagicMock()
        result.upserted_id = None
        return result

    db.garmin_connections.update_one = update_one_side_effect
    db._updates = updates
    return db


@pytest.mark.asyncio
async def test_persist_capabilities_targets_correct_user():
    caps = GarminCapabilities(has_hrv=True)
    db = MagicMock()
    calls = []

    async def update_one(filt, update, upsert=False):
        calls.append((filt, update))
        return MagicMock(upserted_id=None)

    db.garmin_connections.update_one = update_one

    await garmin_service._persist_capabilities(db, "user-abc", caps)

    assert len(calls) == 1
    filt, update = calls[0]
    assert filt == {"user_id": "user-abc"}
    assert update["$set"]["garmin_capabilities"]["has_hrv"] is True
    assert "capabilities_updated_at" in update["$set"]


@pytest.mark.asyncio
async def test_persist_capabilities_does_not_touch_other_user():
    """Two consecutive upserts for different users must not overlap."""
    db = MagicMock()
    calls = []

    async def update_one(filt, update, upsert=False):
        calls.append((filt.copy(), update))
        return MagicMock(upserted_id=None)

    db.garmin_connections.update_one = update_one

    caps_a = GarminCapabilities(has_hrv=True)
    caps_b = GarminCapabilities(has_hrv=False)

    await garmin_service._persist_capabilities(db, "user-a", caps_a)
    await garmin_service._persist_capabilities(db, "user-b", caps_b)

    assert calls[0][0] == {"user_id": "user-a"}
    assert calls[1][0] == {"user_id": "user-b"}
    assert calls[0][1]["$set"]["garmin_capabilities"]["has_hrv"] is True
    assert calls[1][1]["$set"]["garmin_capabilities"]["has_hrv"] is False


@pytest.mark.asyncio
async def test_persist_capabilities_uses_set_not_replace():
    """The upsert must use $set (not a full replace) to preserve other fields."""
    db = MagicMock()

    async def update_one(filt, update, upsert=False):
        assert "$set" in update, "must use $set to avoid overwriting other fields"
        assert "$unset" not in update
        return MagicMock(upserted_id=None)

    db.garmin_connections.update_one = update_one
    caps = GarminCapabilities()
    await garmin_service._persist_capabilities(db, "user-x", caps)


@pytest.mark.asyncio
async def test_persist_capabilities_stores_all_fields():
    db = MagicMock()
    stored = {}

    async def update_one(filt, update, upsert=False):
        stored.update(update["$set"])
        return MagicMock(upserted_id=None)

    db.garmin_connections.update_one = update_one
    caps = GarminCapabilities(has_hrv=True, has_body_battery=True)
    await garmin_service._persist_capabilities(db, "user-z", caps)

    assert "garmin_capabilities" in stored
    assert "capabilities_updated_at" in stored
    gc = stored["garmin_capabilities"]
    assert gc["has_hrv"] is True
    assert gc["has_body_battery"] is True
    assert gc["has_vo2max"] is False


# --------------------------------------------------------------------------- #
# 5. Source unique — GarminCapabilities.from_probe est le seul point de décision
# --------------------------------------------------------------------------- #

def test_service_does_not_reimplement_hrv_detection():
    """Pas de logique `has_hrv = bool(payload)` ou similaire dans service.py."""
    src = inspect.getsource(garmin_service)
    forbidden = [
        "has_hrv = bool",
        "has_hrv = len",
        "has_vo2max = bool",
        "has_vo2max = len",
        "has_training_status = payload is not None",
        "has_body_battery = payload is not None",
        "has_stress = bool",
    ]
    for pattern in forbidden:
        assert pattern not in src, (
            f"Service reimplémente la détection des capacités : '{pattern}' trouvé. "
            "Toute détection doit passer par GarminCapabilities.from_probe()."
        )


def test_runner_does_not_reimplement_capabilities():
    """Pas de logique de capacités dans runner.py."""
    src = inspect.getsource(garmin_runner)
    forbidden = [
        "has_hrv",
        "has_vo2max",
        "has_training_readiness",
        "has_training_status",
        "has_body_battery",
        "has_stress",
        "has_running_dynamics",
        "has_power",
        "has_race_predictions",
    ]
    for pattern in forbidden:
        assert pattern not in src, (
            f"Runner reimplémente la détection : '{pattern}' trouvé. "
            "Les capabilities doivent passer uniquement par GarminCapabilities.from_probe()."
        )


def test_service_calls_from_probe():
    """service.py doit appeler GarminCapabilities.from_probe."""
    src = inspect.getsource(garmin_service)
    assert "GarminCapabilities.from_probe" in src, (
        "service.py doit appeler GarminCapabilities.from_probe() comme source unique."
    )


# --------------------------------------------------------------------------- #
# 6. Aucun nouvel appel gccli massif dans la boucle quotidienne
# --------------------------------------------------------------------------- #

def test_fetch_daily_metrics_no_new_heavy_commands():
    """fetch_daily_metrics ne doit pas appeler max-metrics, training-readiness, etc."""
    src = inspect.getsource(garmin_runner.GccliRunner.fetch_daily_metrics)
    forbidden_commands = [
        "max-metrics",
        "training-readiness",
        "training-status",
        "race-predictions",
        "power-zones",
    ]
    for cmd in forbidden_commands:
        assert cmd not in src, (
            f"fetch_daily_metrics ne doit pas appeler '{cmd}' — PR04 interdit "
            "l'ajout de nouvelles commandes gccli dans la boucle quotidienne."
        )
