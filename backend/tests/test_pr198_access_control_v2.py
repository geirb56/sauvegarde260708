"""
test_pr198_access_control_v2.py
================================

PR #198 — ACCESS CONTROL V2: FREE / TRIAL / PREMIUM canonical contract.

Test matrix (from problem statement):

    FREE_RUNINDEX_ACCESS            = PASS
    FREE_READINESS_ACCESS           = PASS
    FREE_PROGRESS_PAYWALL           = PASS  (isFree=True → paywall rendered)
    FREE_PROGRESS_PREMIUM_API_CALLS = 0     (no premium endpoints called)
    FREE_TRAINING_PREMIUM_API_CALLS = 0     (training gated by isFree)
    FREE_VO2MAX_ACCESS              = DENIED
    FREE_VO2MAX_HISTORY_ACCESS      = DENIED
    FREE_RACE_PREDICTIONS_ACCESS    = DENIED

    TRIAL_PROGRESS_ACCESS           = PASS
    TRIAL_TRAINING_ACCESS           = PASS
    TRIAL_VO2MAX_ACCESS             = PASS

    PREMIUM_PROGRESS_ACCESS         = PASS
    PREMIUM_TRAINING_ACCESS         = PASS

    TRIAL_EQUALS_PREMIUM            = PASS
    SUBSCRIPTION_FAIL_CLOSED        = PASS

All tests use access_control directly — no DB, no server startup required.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from access_control import (
    FREE_FEATURES,
    PREMIUM_FEATURES,
    Tier,
    UserAccess,
    _resolve_access,
    get_route_access,
    RouteAccess,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _free_access(user_id: str = "u_free") -> UserAccess:
    return UserAccess(user_id=user_id, tier=Tier.FREE)


def _trial_access(user_id: str = "u_trial", days_remaining: int = 20) -> UserAccess:
    trial_end = datetime.now(timezone.utc) + timedelta(days=days_remaining)
    return UserAccess(user_id=user_id, tier=Tier.TRIAL, trial_end=trial_end)


def _premium_access(user_id: str = "u_premium") -> UserAccess:
    return UserAccess(user_id=user_id, tier=Tier.PREMIUM)


# ---------------------------------------------------------------------------
# FREE — RunIndex and Readiness are accessible
# ---------------------------------------------------------------------------

class TestFreeRunIndexReadiness:
    """FREE_RUNINDEX_ACCESS = PASS, FREE_READINESS_ACCESS = PASS"""

    def test_free_can_access_run_index_feature(self):
        acc = _free_access()
        assert acc.can("run_index"), "run_index must be FREE"

    def test_free_can_access_dashboard_insight(self):
        acc = _free_access()
        assert acc.can("dashboard_insight"), "dashboard_insight must be FREE"

    def test_free_can_access_basic_stats(self):
        acc = _free_access()
        assert acc.can("basic_stats"), "basic_stats must be FREE"

    def test_free_can_access_workout_list(self):
        acc = _free_access()
        assert acc.can("workout_list"), "workout_list must be FREE"

    def test_free_route_run_index_is_free(self):
        assert get_route_access("/api/run-index") == RouteAccess.FREE

    def test_free_route_stats_is_free(self):
        assert get_route_access("/api/stats") == RouteAccess.FREE

    def test_free_route_dashboard_insight_is_free(self):
        assert get_route_access("/api/dashboard/insight") == RouteAccess.FREE

    def test_free_route_workouts_is_free(self):
        assert get_route_access("/api/workouts") == RouteAccess.FREE


# ---------------------------------------------------------------------------
# FREE — VO2max is DENIED
# ---------------------------------------------------------------------------

class TestFreeVo2maxDenied:
    """FREE_VO2MAX_ACCESS = DENIED, FREE_VO2MAX_HISTORY_ACCESS = DENIED"""

    def test_free_garmin_route_is_premium(self):
        # /api/garmin/ prefix → PREMIUM (includes vo2max-history)
        assert get_route_access("/api/garmin/vo2max-history") == RouteAccess.PREMIUM

    def test_free_garmin_daily_metrics_is_premium(self):
        assert get_route_access("/api/garmin/daily-metrics") == RouteAccess.PREMIUM

    def test_free_has_no_garmin_sync_feature(self):
        acc = _free_access()
        assert not acc.can("garmin_sync")

    def test_free_cannot_access_sync_enabled(self):
        acc = _free_access()
        assert not acc.can("sync_enabled")

    def test_free_api_dict_garmin_sync_false(self):
        acc = _free_access()
        d = acc.to_api_dict()
        assert d["feature_access"].get("garmin_sync") is False


# ---------------------------------------------------------------------------
# FREE — Race Predictions are DENIED
# ---------------------------------------------------------------------------

class TestFreeRacePredictionsDenied:
    """FREE_RACE_PREDICTIONS_ACCESS = DENIED"""

    def test_free_cannot_access_race_predictions_feature(self):
        acc = _free_access()
        assert not acc.can("race_predictions")

    def test_free_route_race_predictions_is_premium(self):
        assert get_route_access("/api/training/race-predictions") == RouteAccess.PREMIUM

    def test_free_api_dict_race_predictions_false(self):
        acc = _free_access()
        d = acc.to_api_dict()
        assert d["feature_access"].get("race_predictions") is False


# ---------------------------------------------------------------------------
# FREE — Progress: paywall, zero premium API calls
# ---------------------------------------------------------------------------

class TestFreeProgressPaywall:
    """
    FREE_PROGRESS_PAYWALL = PASS
    FREE_PROGRESS_PREMIUM_API_CALLS = 0

    These tests verify the backend contract that Progress.jsx relies on:
    - isFree is True for a FREE user
    - The endpoints Progress would call are Premium-gated
    """

    def test_free_is_free_flag(self):
        acc = _free_access()
        assert acc.is_free is True

    def test_free_has_no_premium_access(self):
        acc = _free_access()
        assert acc.has_premium_access is False

    def test_premium_endpoints_called_by_progress_are_premium_gated(self):
        """All Premium API calls that Progress.jsx makes are PREMIUM routes."""
        premium_progress_routes = [
            "/api/training/race-predictions",
            "/api/training/v2/cycle",
            "/api/garmin/vo2max-history",
            "/api/garmin/daily-metrics",
        ]
        for route in premium_progress_routes:
            assert get_route_access(route) == RouteAccess.PREMIUM, (
                f"Route {route} should be PREMIUM — FREE users must not call it"
            )

    def test_free_stats_route_available(self):
        """FREE users can fetch basic stats (non-premium Progress data)."""
        assert get_route_access("/api/stats") == RouteAccess.FREE

    def test_free_run_index_route_available(self):
        """FREE users can fetch run-index (non-premium Progress data)."""
        assert get_route_access("/api/run-index") == RouteAccess.FREE


# ---------------------------------------------------------------------------
# FREE — Training: zero premium API calls
# ---------------------------------------------------------------------------

class TestFreeTrainingPremiumApiCalls:
    """FREE_TRAINING_PREMIUM_API_CALLS = 0"""

    def test_training_plan_route_is_premium(self):
        assert get_route_access("/api/training/plan") == RouteAccess.PREMIUM

    def test_training_v2_week_route_is_premium(self):
        assert get_route_access("/api/training/v2/week") == RouteAccess.PREMIUM

    def test_training_v2_cycle_route_is_premium(self):
        assert get_route_access("/api/training/v2/cycle") == RouteAccess.PREMIUM

    def test_training_today_route_is_premium(self):
        assert get_route_access("/api/training/today") == RouteAccess.PREMIUM

    def test_training_metrics_route_is_premium(self):
        assert get_route_access("/api/training/metrics") == RouteAccess.PREMIUM

    def test_free_cannot_access_training_plan_feature(self):
        acc = _free_access()
        assert not acc.can("training_plan")

    def test_free_cannot_access_full_cycle_feature(self):
        acc = _free_access()
        assert not acc.can("full_cycle")


# ---------------------------------------------------------------------------
# TRIAL — full Premium access
# ---------------------------------------------------------------------------

class TestTrialPremiumAccess:
    """TRIAL_PROGRESS_ACCESS = PASS, TRIAL_TRAINING_ACCESS = PASS, TRIAL_VO2MAX_ACCESS = PASS"""

    def test_trial_has_premium_access(self):
        acc = _trial_access()
        assert acc.has_premium_access is True

    def test_trial_is_not_free(self):
        acc = _trial_access()
        assert acc.is_free is False

    def test_trial_can_training_plan(self):
        acc = _trial_access()
        assert acc.can("training_plan")

    def test_trial_can_race_predictions(self):
        acc = _trial_access()
        assert acc.can("race_predictions")

    def test_trial_can_garmin_sync(self):
        acc = _trial_access()
        assert acc.can("garmin_sync")

    def test_trial_can_full_cycle(self):
        acc = _trial_access()
        assert acc.can("full_cycle")

    def test_trial_can_rag_access(self):
        acc = _trial_access()
        assert acc.can("rag_access")


# ---------------------------------------------------------------------------
# PREMIUM — full Premium access
# ---------------------------------------------------------------------------

class TestPremiumAccess:
    """PREMIUM_PROGRESS_ACCESS = PASS, PREMIUM_TRAINING_ACCESS = PASS"""

    def test_premium_has_premium_access(self):
        acc = _premium_access()
        assert acc.has_premium_access is True

    def test_premium_is_not_free(self):
        acc = _premium_access()
        assert acc.is_free is False

    def test_premium_can_training_plan(self):
        acc = _premium_access()
        assert acc.can("training_plan")

    def test_premium_can_race_predictions(self):
        acc = _premium_access()
        assert acc.can("race_predictions")

    def test_premium_can_garmin_sync(self):
        acc = _premium_access()
        assert acc.can("garmin_sync")

    def test_premium_can_all_premium_features(self):
        acc = _premium_access()
        for feat in PREMIUM_FEATURES:
            assert acc.can(feat), f"PREMIUM should be able to access '{feat}'"


# ---------------------------------------------------------------------------
# TRIAL_EQUALS_PREMIUM — identical feature access
# ---------------------------------------------------------------------------

class TestTrialEqualsPremium:
    """TRIAL_EQUALS_PREMIUM = PASS"""

    def test_trial_and_premium_have_same_has_premium_access(self):
        trial = _trial_access()
        premium = _premium_access()
        assert trial.has_premium_access == premium.has_premium_access

    def test_trial_and_premium_can_same_features(self):
        trial = _trial_access()
        premium = _premium_access()
        all_features = PREMIUM_FEATURES | FREE_FEATURES
        for feat in all_features:
            assert trial.can(feat) == premium.can(feat), (
                f"TRIAL and PREMIUM must have the same access to feature '{feat}'"
            )

    def test_trial_feature_access_dict_equals_premium(self):
        trial = _trial_access()
        premium = _premium_access()
        trial_fa = trial.to_api_dict()["feature_access"]
        premium_fa = premium.to_api_dict()["feature_access"]
        assert trial_fa == premium_fa, "feature_access dicts must be identical for TRIAL and PREMIUM"

    def test_trial_is_unlimited_chat(self):
        acc = _trial_access()
        assert acc.is_unlimited_chat is True

    def test_premium_is_unlimited_chat(self):
        acc = _premium_access()
        assert acc.is_unlimited_chat is True


# ---------------------------------------------------------------------------
# SUBSCRIPTION_FAIL_CLOSED
# ---------------------------------------------------------------------------

class TestSubscriptionFailClosed:
    """SUBSCRIPTION_FAIL_CLOSED = PASS"""

    def test_unknown_status_resolves_to_free(self):
        acc = _resolve_access("u_unknown", {"status": "unknown_garbage"})
        assert acc.is_free is True

    def test_missing_status_resolves_to_free(self):
        acc = _resolve_access("u_missing", {})
        assert acc.is_free is True

    def test_none_status_resolves_to_free(self):
        acc = _resolve_access("u_none", {"status": None})
        assert acc.is_free is True

    def test_expired_trial_resolves_to_free(self):
        trial_end = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
        acc = _resolve_access("u_expired", {"status": "trial", "trial_end": trial_end})
        assert acc.is_free is True

    def test_expired_premium_resolves_to_free(self):
        exp = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
        acc = _resolve_access("u_exp_prem", {"status": "premium", "premium_expires_at": exp})
        assert acc.is_free is True

    def test_unknown_feature_denies_access(self):
        for acc in [_free_access(), _trial_access(), _premium_access()]:
            assert not acc.can("nonexistent_feature_xyz"), (
                "Unknown features must be denied (fail closed)"
            )

    def test_free_is_default_when_no_subscription(self):
        """Without a subscription doc, access resolves to FREE."""
        acc = _resolve_access("u_new", {"status": "free"})
        assert acc.is_free is True
        assert acc.has_premium_access is False

    def test_to_api_dict_is_free_flag_true_for_free(self):
        acc = _free_access()
        d = acc.to_api_dict()
        assert d["is_free"] is True
        assert d["has_premium_access"] is False
        assert d["subscription_status"] == "free"

    def test_to_api_dict_trial_has_premium_access_true(self):
        acc = _trial_access()
        d = acc.to_api_dict()
        assert d["is_free"] is False
        assert d["has_premium_access"] is True
        assert d["subscription_status"] == "trial"

    def test_to_api_dict_premium_has_premium_access_true(self):
        acc = _premium_access()
        d = acc.to_api_dict()
        assert d["is_free"] is False
        assert d["has_premium_access"] is True
        assert d["subscription_status"] == "premium"
