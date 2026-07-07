"""
Training Load Engine — pure deterministic ACWR computation.

Computes Acute:Chronic Workload Ratio from workout records and derives a
training-load score.

No FastAPI, no I/O — only pure computation.
"""

from __future__ import annotations

from typing import Sequence

# Approximate easy-pace proxy used when only distance is available (min/km).
ESTIMATED_PACE_MIN_PER_KM = 6.0


def _sum_load(workouts: Sequence[dict], days: int, reference_date=None) -> float:
    """Sum training load for workouts within *days* before reference_date.

    Each workout is expected to have at minimum:
        - ``date``            (ISO-8601 string or datetime)
        - ``duration_minutes`` (float, optional)
        - ``distance_km``     (float, optional)

    Load is approximated as ``duration_minutes`` when present, falling back
    to ``distance_km * 6`` (roughly 6 min/km easy pace) as a proxy.
    """
    from datetime import datetime, timezone, timedelta

    if reference_date is None:
        reference_date = datetime.now(tz=timezone.utc)

    cutoff = reference_date - timedelta(days=days)
    total = 0.0
    for w in workouts:
        raw_date = w.get("date")
        if raw_date is None:
            continue

        if isinstance(raw_date, str):
            try:
                workout_date = datetime.fromisoformat(raw_date.replace("Z", "+00:00"))
            except ValueError:
                continue
        elif isinstance(raw_date, datetime):
            workout_date = raw_date
        else:
            continue

        if workout_date.tzinfo is None:
            workout_date = workout_date.replace(tzinfo=timezone.utc)

        if cutoff <= workout_date <= reference_date:
            duration = w.get("duration_minutes")
            if duration is not None:
                total += float(duration)
            else:
                distance = w.get("distance_km")
                if distance is not None:
                    total += float(distance) * ESTIMATED_PACE_MIN_PER_KM

    return total


def compute_acwr(workouts: Sequence[dict], reference_date=None) -> float:
    """Compute the Acute:Chronic Workload Ratio.

    ACWR = load_last_7_days / load_last_28_days

    Returns 1.0 when chronic load is zero (no historic data).
    """
    load_7 = _sum_load(workouts, 7, reference_date)
    load_28 = _sum_load(workouts, 28, reference_date)

    if load_28 == 0:
        return 1.0
    return round(load_7 / load_28, 3)


def compute_training_load_score(acwr: float) -> float:
    """Convert ACWR to a training-load score (0-100).

    The optimal ACWR window is [0.8, 1.3].  Scores outside that range are
    penalised proportionally.

    Returns
    -------
    float
        Score in [0, 100].
    """
    if 0.8 <= acwr <= 1.3:
        score = 100.0
    elif acwr > 1.3:
        excess = acwr - 1.3
        score = max(0.0, 100.0 - excess * 100.0)
    else:
        deficit = 0.8 - acwr
        score = max(0.0, 100.0 - deficit * 100.0)

    return round(score, 1)


def compute_training_load(workouts: Sequence[dict], reference_date=None) -> dict:
    """Return ACWR and derived training-load score.

    Returns
    -------
    dict with keys:
        ``acwr``                – float
        ``training_load_score`` – float in [0, 100]
        ``status``              – "overtraining_risk" | "optimal" | "undertraining"
    """
    acwr = compute_acwr(workouts, reference_date)
    training_load_score = compute_training_load_score(acwr)

    if acwr > 1.3:
        status = "overtraining_risk"
    elif acwr < 0.8:
        status = "undertraining"
    else:
        status = "optimal"

    return {
        "acwr": acwr,
        "training_load_score": training_load_score,
        "status": status,
    }
