"""Tests for the RunIndex v2 Garmin Data Layer (PR01).

Uses REAL audited gccli 1.9.0 JSON payloads (trimmed) for the account probed
during the audit. Also covers the empty {} / [] / null degenerate cases.
"""

from garmin.data_layer import (
    GarminActivity,
    GarminDailyMetrics,
    GarminCapabilities,
)


# --------------------------------------------------------------------------- #
# Real audited payloads (trimmed to the fields the models read)
# --------------------------------------------------------------------------- #

ACTIVITY_SUMMARY = {
    "activityId": 23821475753,
    "activityName": "Vannes Course a pied",
    "activityTypeDTO": {"typeId": 1, "typeKey": "running"},
    "metadataDTO": {
        "lapCount": 7,
        "hasHrTimeInZones": True,
        "hasPowerTimeInZones": False,
        "hasSplits": True,
        "manufacturer": "GARMIN",
    },
    "summaryDTO": {
        "startTimeLocal": "2026-08-02T10:08:20.0",
        "startTimeGMT": "2026-08-02T08:08:20.0",
        "distance": 6769.92,
        "duration": 2787.479,
        "movingDuration": 2779.594,
        "averageSpeed": 2.4289999,
        "averageMovingSpeed": 2.4355786,
        "maxSpeed": 2.986,
        "calories": 604.0,
        "averageHR": 146.0,
        "maxHR": 164.0,
        "minHR": 98.0,
        "averageRunCadence": 162.28125,
        "maxRunCadence": 180.0,
        "strideLength": 89.694,
        "elevationGain": 23.1,
        "elevationLoss": 27.84,
        "moderateIntensityMinutes": 10,
        "vigorousIntensityMinutes": 30,
        "steps": 7538,
    },
}

# activity details descriptors observed: NO power / running-dynamics keys
ACTIVITY_DETAILS = {
    "activityId": 23821475753,
    "measurementCount": 16,
    "metricsCount": 483,
    "detailsAvailable": True,
    "metricDescriptors": [
        {"metricsIndex": 0, "key": "sumDuration"},
        {"metricsIndex": 3, "key": "directHeartRate"},
        {"metricsIndex": 4, "key": "directSpeed"},
        {"metricsIndex": 8, "key": "directRunCadence"},
        {"metricsIndex": 10, "key": "directElevation"},
        {"metricsIndex": 15, "key": "directVerticalSpeed"},
    ],
}

SLEEP = {
    "dailySleepDTO": {
        "calendarDate": "2026-08-03",
        "sleepTimeSeconds": 24660,
        "deepSleepSeconds": 1140,
        "lightSleepSeconds": 13680,
        "remSleepSeconds": 9840,
        "awakeSleepSeconds": 480,
        "averageRespirationValue": 12.0,
        "sleepScores": {"overall": {"value": 78}},
    }
}

STRESS = {"calendarDate": "2026-08-03", "maxStressLevel": 92, "avgStressLevel": 28}

BODY_BATTERY = [
    {
        "date": "2026-08-03",
        "charged": 48,
        "drained": 34,
        "bodyBatteryValuesArray": [
            [1785709620000, 9],
            [1785733920000, 53],
            [1785765420000, 41],
        ],
    }
]

HR = {"restingHeartRate": 52}


# --------------------------------------------------------------------------- #
# GarminActivity — real summary
# --------------------------------------------------------------------------- #

def test_activity_from_summary_real():
    a = GarminActivity.from_summary(ACTIVITY_SUMMARY, details_available=True)
    assert a.activity_id == "23821475753"
    assert a.activity_type == "running"
    assert a.start_time == "2026-08-02T08:08:20.0"
    assert a.distance_m == 6769.92
    assert a.duration_s == 2787.479
    assert a.moving_duration_s == 2779.594
    assert a.average_speed_mps == 2.4289999
    assert a.average_moving_speed_mps == 2.4355786
    assert a.max_speed_mps == 2.986
    assert a.average_hr == 146.0
    assert a.max_hr == 164.0
    assert a.min_hr == 98.0
    assert a.average_run_cadence == 162.28125
    assert a.max_run_cadence == 180.0
    assert a.stride_length == 89.694
    assert a.steps == 7538
    assert a.elevation_gain == 23.1
    assert a.elevation_loss == 27.84
    assert a.calories == 604.0
    assert a.moderate_intensity_minutes == 10
    assert a.vigorous_intensity_minutes == 30
    assert a.lap_count == 7
    assert a.has_hr_zones is True
    assert a.has_splits is True
    assert a.details_available is True
    assert a.source == "garmin"


def test_activity_from_flat_list_shape():
    # activities-list item shape (cadence uses *InStepsPerMinute)
    raw = {
        "activityId": 999,
        "activityType": {"typeKey": "running"},
        "distance": 5000.0,
        "duration": 1800.0,
        "averageHR": 140.0,
        "averageRunningCadenceInStepsPerMinute": 170.0,
        "maxRunningCadenceInStepsPerMinute": 182.0,
        "steps": 6000,
        "elevationGain": 12.0,
    }
    a = GarminActivity.from_summary(raw)
    assert a.activity_id == "999"
    assert a.average_run_cadence == 170.0
    assert a.max_run_cadence == 182.0
    assert a.distance_m == 5000.0
    assert a.details_available is None  # not provided


# --------------------------------------------------------------------------- #
# GarminDailyMetrics — real payloads
# --------------------------------------------------------------------------- #

def test_daily_metrics_real():
    m = GarminDailyMetrics.from_gccli(
        date="2026-08-03", hr=HR, sleep=SLEEP, stress=STRESS,
        body_battery=BODY_BATTERY, hrv={},  # device has no HRV
    )
    assert m.date == "2026-08-03"
    assert m.resting_hr == 52
    assert m.sleep_hours == 6.8  # 24660/3600 = 6.85 -> round(…,1) = 6.8 (banker's rounding)
    assert m.sleep_score == 78
    assert m.respiration == 12.0
    assert m.stress == 28
    assert m.body_battery == 41  # latest value in the timeseries
    assert m.hrv is None
    assert m.source == "garmin"


def test_daily_metrics_hrv_present():
    hrv = {"hrvSummary": {"lastNightAvg": 61, "weeklyAvg": 58}}
    m = GarminDailyMetrics.from_gccli(date="2026-08-03", hrv=hrv)
    assert m.hrv == 61


def test_stress_negative_sentinel_is_none():
    m = GarminDailyMetrics.from_gccli(stress={"avgStressLevel": -1})
    assert m.stress is None


# --------------------------------------------------------------------------- #
# GarminCapabilities — real probe (this watch: only basic metrics)
# --------------------------------------------------------------------------- #

def test_capabilities_real_probe():
    caps = GarminCapabilities.from_probe(
        hrv={},                                   # {} -> False
        max_metrics=[],                           # [] -> False (no VO2max)
        training_readiness=[],                    # [] -> False
        training_status={"mostRecentVO2Max": None, "mostRecentTrainingStatus": None},
        body_battery=BODY_BATTERY,                # has data -> True
        stress=STRESS,                            # avg 28 -> True
        activity_summary=ACTIVITY_SUMMARY,        # hasPowerTimeInZones False
        activity_details=ACTIVITY_DETAILS,        # no dynamics descriptors
        race_predictions=None,                    # 404 -> None -> False
    )
    assert caps.has_hrv is False
    assert caps.has_vo2max is False
    assert caps.has_training_readiness is False
    assert caps.has_training_status is False
    assert caps.has_body_battery is True
    assert caps.has_stress is True
    assert caps.has_running_dynamics is False
    assert caps.has_power is False
    assert caps.has_race_predictions is False


def test_capabilities_rich_watch():
    caps = GarminCapabilities.from_probe(
        hrv={"hrvSummary": {"lastNightAvg": 60}},
        max_metrics=[{"vo2MaxValue": 52}],
        training_readiness=[{"score": 70}],
        training_status={"mostRecentTrainingStatus": {"latestTrainingStatusData": {}}},
        body_battery=BODY_BATTERY,
        stress=STRESS,
        activity_summary={"metadataDTO": {"hasPowerTimeInZones": True},
                          "summaryDTO": {"avgGroundContactTime": 250.0}},
        activity_details={"metricDescriptors": [{"key": "directVerticalOscillation"}]},
        race_predictions={"time5K": 1500},
    )
    assert caps.has_hrv is True
    assert caps.has_vo2max is True
    assert caps.has_training_readiness is True
    assert caps.has_training_status is True
    assert caps.has_body_battery is True
    assert caps.has_stress is True
    assert caps.has_running_dynamics is True
    assert caps.has_power is True
    assert caps.has_race_predictions is True


# --------------------------------------------------------------------------- #
# Degenerate inputs: {} / [] / null must yield valid models (no raise)
# --------------------------------------------------------------------------- #

def test_activity_empty_inputs():
    for raw in ({}, [], None):
        a = GarminActivity.from_summary(raw)
        assert a.activity_id is None
        assert a.distance_m is None
        assert a.average_hr is None
        assert a.has_hr_zones is None
        assert a.source == "garmin"


def test_daily_metrics_empty_inputs():
    m = GarminDailyMetrics.from_gccli(
        date=None, hr={}, sleep={}, stress={}, body_battery=[], hrv=None,
    )
    assert m.date is None
    assert m.resting_hr is None
    assert m.sleep_hours is None
    assert m.sleep_score is None
    assert m.stress is None
    assert m.body_battery is None
    assert m.respiration is None
    assert m.hrv is None
    assert m.source == "garmin"


def test_capabilities_all_empty():
    caps = GarminCapabilities.from_probe(
        hrv={}, max_metrics=[], training_readiness=[], training_status={},
        body_battery=[], stress={}, activity_summary={}, activity_details={},
        race_predictions=None,
    )
    assert caps.model_dump() == {
        "has_hrv": False, "has_vo2max": False, "has_training_readiness": False,
        "has_training_status": False, "has_body_battery": False, "has_stress": False,
        "has_running_dynamics": False, "has_power": False, "has_race_predictions": False,
    }


# --------------------------------------------------------------------------- #
# Non-empty payloads whose business values are all null must yield False
# --------------------------------------------------------------------------- #

def test_capabilities_vo2max_null_value_is_false():
    assert GarminCapabilities.from_probe(max_metrics=[{"vo2MaxValue": None}]).has_vo2max is False
    # positive value -> True
    assert GarminCapabilities.from_probe(max_metrics=[{"generic": {"vo2MaxValue": 52.0}}]).has_vo2max is True


def test_capabilities_training_readiness_null_score_is_false():
    assert GarminCapabilities.from_probe(training_readiness=[{"score": None}]).has_training_readiness is False
    assert GarminCapabilities.from_probe(training_readiness=[{"score": 70}]).has_training_readiness is True


def test_capabilities_race_predictions_all_null_is_false():
    assert GarminCapabilities.from_probe(
        race_predictions={"time5K": None, "time10K": None, "timeHalfMarathon": None}
    ).has_race_predictions is False
    assert GarminCapabilities.from_probe(
        race_predictions={"time5K": 1500, "time10K": None}
    ).has_race_predictions is True
