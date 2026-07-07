"""
Readiness Engine — pure deterministic physiological scoring.

Computes a readiness score (0-100) using:
- HRV (if available): 0.4 * hrv_score + 0.3 * sleep_score + 0.3 * training_load_score
- RHR fallback:       0.4 * rhr_score + 0.3 * sleep_score + 0.3 * training_load_score

No FastAPI, no I/O — only pure computation.
"""

# Penalty applied to the readiness score per BPM above the user's baseline RHR.
# A higher resting heart rate than usual signals accumulated fatigue.
RHR_PENALTY_PER_BPM = 5


def compute_rhr_score(rhr_today: float, baseline_rhr: float) -> float:
    """Convert resting heart rate into a score (0-100) relative to baseline.

    A higher-than-usual RHR indicates fatigue and lowers the score.
    """
    delta = rhr_today - baseline_rhr
    score = 100 - delta * RHR_PENALTY_PER_BPM
    return max(0.0, min(100.0, score))


def compute_readiness(
    training_load_score: float,
    sleep_score: float = 70.0,
    hrv_score: float | None = None,
    rhr_today: float | None = None,
    baseline_rhr: float | None = None,
) -> float:
    """Compute overall readiness score (0-100).

    Parameters
    ----------
    training_load_score:
        Score derived from ACWR/training load (0-100).
    sleep_score:
        Sleep quality score (0-100).  Defaults to 70 when unavailable.
    hrv_score:
        Heart-rate variability score (0-100).  When provided, used as the
        primary recovery indicator.
    rhr_today:
        Today's resting heart rate (bpm).  Used only when hrv_score is None.
    baseline_rhr:
        User's average resting heart rate (bpm).  Used only when hrv_score is None.

    Returns
    -------
    float
        Readiness score clamped to [0, 100].
    """
    sleep_score = max(0.0, min(100.0, sleep_score))
    training_load_score = max(0.0, min(100.0, training_load_score))

    if hrv_score is not None:
        primary_score = max(0.0, min(100.0, hrv_score))
    elif rhr_today is not None and baseline_rhr is not None:
        primary_score = compute_rhr_score(rhr_today, baseline_rhr)
    else:
        primary_score = 70.0

    readiness = (
        0.4 * primary_score
        + 0.3 * sleep_score
        + 0.3 * training_load_score
    )
    return round(max(0.0, min(100.0, readiness)), 1)
