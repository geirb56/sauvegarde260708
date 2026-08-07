"""PR04 — TrainingState: pure deterministic training-state layer for V2.

Design rules
------------
- PURE: no MongoDB, no Garmin calls, no API calls, no LLM, no cache,
  no global mutable state, no environment variables.
- reference_date must be supplied explicitly by the caller — datetime.now()
  is NEVER called inside this module.
- All results are deterministic and fully reproducible for identical inputs.
- No imports from training_engine, training_load_engine, llm_coach,
  or coach_service.

Two-axis architecture
---------------------
TrainingState answers two independent questions:

  1. What is the recent training continuity?  → continuity_state
  2. What is the current load state?          → load_state

A runner can simultaneously be:
  continuity_state = "partial_reprise"
  load_state       = "elevated"

These two axes are fully independent.

Continuity states
-----------------
  "no_history"     : No exploitable running history at all.
  "deep_reprise"   : Prior history exists but no run in the last
                     NO_RUN_DEEP_REPRISE_DAYS days.
  "partial_reprise": A comeback has started but recent weekly volume is
                     below PARTIAL_REPRISE_VOLUME_RATIO of the observable
                     baseline.
  "reprise_exit"   : Continuity is back but not yet stable enough to be
                     considered "normal".  Defined as: at least one run in
                     the last 28 days AND recent weekly equivalent >=
                     PARTIAL_REPRISE_VOLUME_RATIO of baseline but < 1.0,
                     AND fewer than REPRISE_EXIT_STABLE_WEEKS weeks of
                     consistent coverage.
  "normal"         : No significant continuity break detected.

Load states (mirror of TrainingLoadSnapshot.status)
----------------------------------------------------
  "unavailable"
  "very_low"
  "low"
  "balanced"
  "elevated"
  "high"

Confidence values
-----------------
  "none" | "low" | "medium" | "high"

Continuity confidence thresholds (calendar days of history):
  0          → "none"
  1 – 29     → "low"
  30 – 89    → "medium"
  ≥ 90       → "high"

Overall confidence = minimum(continuity_confidence, load_confidence)
with order: none < low < medium < high.

Load confidence is taken directly from TrainingLoadSnapshot.confidence.

Reason codes
------------
Deterministic, language-neutral, UI-independent:
  NO_RUNNING_HISTORY
  NO_RUN_LAST_28D
  RECENT_VOLUME_FAR_BELOW_BASELINE
  RECENT_VOLUME_RECOVERING
  CONTINUITY_STABLE
  LOAD_UNAVAILABLE
  LOAD_VERY_LOW
  LOAD_LOW
  LOAD_BALANCED
  LOAD_ELEVATED
  LOAD_HIGH

days_since_last_run
-------------------
Computed deterministically from reference_date and the last valid running
activity recorded in TrainingHistory.  Never sourced from the system clock.
None when no history is available.
"""

from __future__ import annotations

from datetime import date
from typing import List, Optional

from pydantic import BaseModel, ConfigDict

from .training_history import TrainingHistory
from .training_load import TrainingLoadSnapshot
from .runner_profile import RunnerProfile

# ---------------------------------------------------------------------------
# Constants (centralised — never dispersed inline in logic)
# ---------------------------------------------------------------------------

# Continuity thresholds
NO_RUN_DEEP_REPRISE_DAYS: int = 28
"""No run in the last N days (with prior history) → deep_reprise."""

PARTIAL_REPRISE_VOLUME_RATIO: float = 0.50
"""Recent weekly equivalent < this fraction of observable baseline → partial_reprise."""

REPRISE_EXIT_STABLE_WEEKS: int = 4
"""Minimum weeks of consistent recent coverage required to leave reprise_exit."""

# Continuity confidence thresholds (days of observable history)
CONTINUITY_CONF_LOW_MIN_DAYS: int = 1
CONTINUITY_CONF_MEDIUM_MIN_DAYS: int = 30
CONTINUITY_CONF_HIGH_MIN_DAYS: int = 90

# Confidence ordering (lowest to highest)
_CONFIDENCE_ORDER = ["none", "low", "medium", "high"]


# ---------------------------------------------------------------------------
# Output model
# ---------------------------------------------------------------------------


class TrainingState(BaseModel):
    """Immutable snapshot describing the current training state of a runner.

    TrainingState describes.  TrainingState does NOT prescribe.

    No field carries a decision about what the runner should do next.
    Decisional fields (recommended_weekly_km, allow_intensity, etc.) belong
    to future layers (WeeklyTarget, WorkoutGenerator, …).
    """

    model_config = ConfigDict(frozen=True)

    reference_date: date

    # --- Axis 1: continuity ---
    continuity_state: str   # no_history | deep_reprise | partial_reprise | reprise_exit | normal
    continuity_confidence: str  # none | low | medium | high

    # --- Axis 2: load ---
    load_state: str         # unavailable | very_low | low | balanced | elevated | high
    load_confidence: str    # none | low | medium | high

    # --- Combined ---
    overall_confidence: str  # minimum(continuity_confidence, load_confidence)

    # --- Derived metrics ---
    days_since_last_run: Optional[int]

    recent_7d_km: Optional[float]
    recent_28d_km: Optional[float]

    acute_load: Optional[float]
    chronic_weekly_load: Optional[float]
    acwr: Optional[float]

    reason_codes: List[str]


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _continuity_confidence(available_history_days: int) -> str:
    """Return confidence level from the depth of observable running history.

    Declared profile data MUST NOT raise confidence; only observed history counts.
    """
    if available_history_days >= CONTINUITY_CONF_HIGH_MIN_DAYS:
        return "high"
    if available_history_days >= CONTINUITY_CONF_MEDIUM_MIN_DAYS:
        return "medium"
    if available_history_days >= CONTINUITY_CONF_LOW_MIN_DAYS:
        return "low"
    return "none"


def _min_confidence(a: str, b: str) -> str:
    """Return the lower of two confidence values."""
    idx_a = _CONFIDENCE_ORDER.index(a) if a in _CONFIDENCE_ORDER else 0
    idx_b = _CONFIDENCE_ORDER.index(b) if b in _CONFIDENCE_ORDER else 0
    return _CONFIDENCE_ORDER[min(idx_a, idx_b)]


def _recent_weekly_equivalent_km(training_history: TrainingHistory) -> Optional[float]:
    """Return the most relevant recent weekly equivalent distance in km.

    Uses the 28-day window (window_30d covers 30 days; we use the 7-day
    window for acute weekly comparison).  The 7-day window is the most direct
    representation of current weekly volume.
    """
    w7 = training_history.window_7d
    if w7.activity_count > 0 and w7.distance_km > 0:
        return w7.distance_km
    return None


def _observable_baseline_km(runner_profile: RunnerProfile) -> Optional[float]:
    """Return the observable (history-derived) typical_weekly_km from RunnerProfile.

    Returns None if no history-based baseline is available.
    The declared profile value alone MUST NOT produce a baseline.
    RunnerProfile.typical_weekly_km already uses history-first priority
    (30d observed → 90d fallback → declared).  We accept it directly but
    only when the history depth is sufficient (available_history_days > 0).
    """
    if runner_profile.available_history_days <= 0:
        return None
    return runner_profile.typical_weekly_km  # may still be None


def _has_recent_run(training_history: TrainingHistory, days: int, reference_date: date) -> bool:
    """Return True if there is at least one valid run in the last *days* days."""
    days_since = training_history.days_since_last_run
    if days_since is None:
        return False
    return days_since < days


def _classify_continuity(
    training_history: TrainingHistory,
    runner_profile: RunnerProfile,
    reference_date: date,
) -> tuple[str, List[str]]:
    """Return (continuity_state, reason_codes) for the continuity axis."""
    codes: List[str] = []

    available_days = training_history.available_history_days
    has_any_history = training_history.has_any_running_history

    # ── no_history ───────────────────────────────────────────────────────
    if not has_any_history:
        codes.append("NO_RUNNING_HISTORY")
        return "no_history", codes

    # From here onwards: prior history exists.
    days_since = training_history.days_since_last_run  # int (not None)

    # ── deep_reprise ──────────────────────────────────────────────────────
    if days_since is not None and days_since >= NO_RUN_DEEP_REPRISE_DAYS:
        codes.append("NO_RUN_LAST_28D")
        return "deep_reprise", codes

    # ── compute recent weekly equivalent and observable baseline ──────────
    recent_weekly_km = _recent_weekly_equivalent_km(training_history)
    baseline_km = _observable_baseline_km(runner_profile)

    # ── partial_reprise ───────────────────────────────────────────────────
    if (
        baseline_km is not None
        and baseline_km > 0
        and recent_weekly_km is not None
        and recent_weekly_km < PARTIAL_REPRISE_VOLUME_RATIO * baseline_km
    ):
        codes.append("RECENT_VOLUME_FAR_BELOW_BASELINE")
        return "partial_reprise", codes

    # ── reprise_exit ──────────────────────────────────────────────────────
    # Volume is recovering (>= 50% of baseline if baseline is known, or any
    # run in last 7d if no baseline), but not yet stable.
    # Stability criterion: available history >= REPRISE_EXIT_STABLE_WEEKS weeks
    # AND 30-day window shows consistent activity.
    w30 = training_history.window_30d
    w7 = training_history.window_7d

    # "Not yet stable": fewer than REPRISE_EXIT_STABLE_WEEKS weeks of history
    # OR the 30d window is suspiciously sparse (< 4 runs in 30d for context).
    reprise_exit_min_days = REPRISE_EXIT_STABLE_WEEKS * 7

    if available_days < reprise_exit_min_days:
        # History too short to be "normal"
        if w7.activity_count > 0:
            codes.append("RECENT_VOLUME_RECOVERING")
            return "reprise_exit", codes

    # Even with sufficient history depth, if volume is below baseline
    # but above 50% threshold, still in reprise_exit.
    if (
        baseline_km is not None
        and baseline_km > 0
        and recent_weekly_km is not None
        and recent_weekly_km < baseline_km
        and w30.activity_count < REPRISE_EXIT_STABLE_WEEKS * 3
    ):
        codes.append("RECENT_VOLUME_RECOVERING")
        return "reprise_exit", codes

    # ── normal ────────────────────────────────────────────────────────────
    codes.append("CONTINUITY_STABLE")
    return "normal", codes


def _load_reason_code(load_state: str) -> str:
    mapping = {
        "unavailable": "LOAD_UNAVAILABLE",
        "very_low": "LOAD_VERY_LOW",
        "low": "LOAD_LOW",
        "balanced": "LOAD_BALANCED",
        "elevated": "LOAD_ELEVATED",
        "high": "LOAD_HIGH",
    }
    return mapping.get(load_state, "LOAD_UNAVAILABLE")


# ---------------------------------------------------------------------------
# Public entry-point
# ---------------------------------------------------------------------------


def build_training_state(
    *,
    training_history: TrainingHistory,
    training_load: TrainingLoadSnapshot,
    runner_profile: RunnerProfile,
    reference_date: date,
) -> TrainingState:
    """Build an immutable :class:`TrainingState` from explicit V2 inputs.

    All data is injected.  No external I/O is performed.

    Parameters
    ----------
    training_history:
        Observed running history windows.
    training_load:
        ACWR-based load snapshot.
    runner_profile:
        Athlete profile combining observed and declared data.
    reference_date:
        The anchor date for all calculations.  Must be supplied explicitly.
    """
    # ── Axis 1: continuity ────────────────────────────────────────────────
    continuity_state, reason_codes = _classify_continuity(
        training_history, runner_profile, reference_date
    )
    continuity_conf = _continuity_confidence(training_history.available_history_days)

    # ── Axis 2: load ──────────────────────────────────────────────────────
    # Mirror load classification directly from TrainingLoadSnapshot — no
    # re-computation, no new thresholds.
    load_state = training_load.status
    load_conf = training_load.confidence

    reason_codes.append(_load_reason_code(load_state))

    # ── Combined confidence ───────────────────────────────────────────────
    overall_conf = _min_confidence(continuity_conf, load_conf)

    # ── Derived metrics ───────────────────────────────────────────────────
    w7 = training_history.window_7d
    w30 = training_history.window_30d

    recent_7d_km: Optional[float] = w7.distance_km if w7.activity_count > 0 else None
    recent_28d_km: Optional[float] = w30.distance_km if w30.activity_count > 0 else None

    acute_load: Optional[float] = (
        training_load.acute_load_7d if training_load.is_available else None
    )
    chronic_weekly_load: Optional[float] = (
        training_load.chronic_weekly_load if training_load.is_available else None
    )
    acwr: Optional[float] = training_load.acwr

    return TrainingState(
        reference_date=reference_date,
        continuity_state=continuity_state,
        continuity_confidence=continuity_conf,
        load_state=load_state,
        load_confidence=load_conf,
        overall_confidence=overall_conf,
        days_since_last_run=training_history.days_since_last_run,
        recent_7d_km=recent_7d_km,
        recent_28d_km=recent_28d_km,
        acute_load=acute_load,
        chronic_weekly_load=chronic_weekly_load,
        acwr=acwr,
        reason_codes=reason_codes,
    )


__all__ = ["TrainingState", "build_training_state"]
