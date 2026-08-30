"""
Readiness Engine — pure deterministic physiological scoring.

Computes a readiness score (0-100) using:
- HRV (if available): 0.4 * hrv_score + 0.3 * sleep_score + 0.3 * training_load_score
- RHR fallback:       0.4 * rhr_score + 0.3 * sleep_score + 0.3 * training_load_score

No FastAPI, no I/O — only pure computation.
No fallback neutral values: None stays None (no sleep=70, no primary=70).
"""

from __future__ import annotations

from typing import Optional

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
    sleep_score: Optional[float] = None,
    hrv_score: Optional[float] = None,
    rhr_today: Optional[float] = None,
    baseline_rhr: Optional[float] = None,
) -> Optional[float]:
    """Compute overall readiness score (0-100).

    Parameters
    ----------
    training_load_score:
        Score derived from ACWR/training load (0-100).
    sleep_score:
        Sleep quality score (0-100).  When None, the sleep component is
        excluded from the weighted average (no synthetic default).
    hrv_score:
        Heart-rate variability score (0-100).  When provided, used as the
        primary recovery indicator.
    rhr_today:
        Today's resting heart rate (bpm).  Used only when hrv_score is None.
    baseline_rhr:
        User's average resting heart rate (bpm).  Used only when hrv_score is None.

    Returns
    -------
    Optional[float]
        Readiness score clamped to [0, 100], or None when no physio signal
        is available (neither HRV nor RHR).
    """
    training_load_score = max(0.0, min(100.0, training_load_score))

    if hrv_score is not None:
        primary_score: Optional[float] = max(0.0, min(100.0, hrv_score))
    elif rhr_today is not None and baseline_rhr is not None:
        primary_score = compute_rhr_score(rhr_today, baseline_rhr)
    else:
        # No physio signal — cannot produce a meaningful readiness score.
        return None

    pairs = [(primary_score, 0.4), (training_load_score, 0.3)]
    if sleep_score is not None:
        sleep_clamped = max(0.0, min(100.0, sleep_score))
        pairs.append((sleep_clamped, 0.3))

    total_weight = sum(w for _, w in pairs)
    readiness = sum(s * w for s, w in pairs) / total_weight
    return round(max(0.0, min(100.0, readiness)), 1)
