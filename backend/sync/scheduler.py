"""Smart sync scheduler — PURE decision logic (no I/O).

Decides WHEN to sync each user based on their activity tier, so we never poll
everyone on a fixed interval (critical for 10k users on batch-only Garmin).

Tiers & cadence:
  ACTIVE   -> every 15 min   (recent app signal or very recent activity)
  NORMAL   -> every 2 h      (activity within the last few days)
  INACTIVE -> every 24 h     (nothing recent)

Signals (fed in by the scheduler worker):
  - active_signal_ts : app interaction (POST /activity-signal), Redis TTL
  - last_activity_ts : newest ingested Garmin activity
  - last_sync_ts     : last successful sync

All timestamps are epoch seconds (float) or None. Fully unit-testable.
"""

from __future__ import annotations

TIER_ACTIVE = "active"
TIER_NORMAL = "normal"
TIER_INACTIVE = "inactive"

# Cadence per tier (seconds).
INTERVAL_ACTIVE = 15 * 60        # 15 min (window 15-30)
INTERVAL_NORMAL = 2 * 3600       # 2 h   (window 2-6h)
INTERVAL_INACTIVE = 24 * 3600    # once per day

# Classification windows (seconds).
ACTIVE_SIGNAL_WINDOW = 45 * 60       # app-interaction freshness -> ACTIVE
ACTIVE_ACTIVITY_WINDOW = 6 * 3600    # a workout in the last 6h -> ACTIVE
NORMAL_ACTIVITY_WINDOW = 3 * 24 * 3600  # activity within 3 days -> NORMAL

_INTERVALS = {
    TIER_ACTIVE: INTERVAL_ACTIVE,
    TIER_NORMAL: INTERVAL_NORMAL,
    TIER_INACTIVE: INTERVAL_INACTIVE,
}


def classify_tier(now: float, active_signal_ts: float | None,
                  last_activity_ts: float | None) -> str:
    """Return the user's activity tier from freshness signals."""
    if active_signal_ts is not None and (now - active_signal_ts) <= ACTIVE_SIGNAL_WINDOW:
        return TIER_ACTIVE
    if last_activity_ts is not None and (now - last_activity_ts) <= ACTIVE_ACTIVITY_WINDOW:
        return TIER_ACTIVE
    if last_activity_ts is not None and (now - last_activity_ts) <= NORMAL_ACTIVITY_WINDOW:
        return TIER_NORMAL
    return TIER_INACTIVE


def interval_for(tier: str) -> int:
    return _INTERVALS.get(tier, INTERVAL_INACTIVE)


def is_due(now: float, last_sync_ts: float | None, tier: str) -> bool:
    """True if the user should be synced now given their tier cadence."""
    if last_sync_ts is None:
        return True  # never synced
    return (now - last_sync_ts) >= interval_for(tier)


def decide(now: float, *, active_signal_ts: float | None,
           last_activity_ts: float | None, last_sync_ts: float | None) -> dict:
    """Convenience: classify + due decision in one call (pure)."""
    tier = classify_tier(now, active_signal_ts, last_activity_ts)
    return {"tier": tier, "due": is_due(now, last_sync_ts, tier),
            "interval": interval_for(tier)}
