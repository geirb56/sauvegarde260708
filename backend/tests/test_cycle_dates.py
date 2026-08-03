"""
Unit tests for compute_cycle_dates() — cycle temporal alignment.

These tests run entirely offline (no server, no DB) by importing
compute_cycle_dates directly from training_engine.

Design note
-----------
compute_cycle_dates() is a *pure* function: it does NOT reduce total_weeks
internally.  The calling code is responsible for capping total_weeks to the
weeks available before the race (e.g. when the user registers late):

    weeks_available = (event_date - today).days // 7
    total_weeks = max(1, min(standard_weeks, weeks_available))

This ensures current_week advances correctly across repeated calls during an
ongoing cycle instead of resetting to 1.

Scenarios verified:
1. Semi-marathon 12 weeks away → end_date == event_date, total_weeks == 12
2. Marathon caller-reduced to 8 weeks → end_date == event_date, total_weeks == 8
3. No event_date → start_date == today, legacy behaviour preserved
4. Upcoming / active / completed status correctly computed
"""

import datetime
import sys
import os

# Make backend root importable without installing the package
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
from training_engine import compute_cycle_dates


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _today() -> datetime.date:
    return datetime.date.today()


def _days(n: int) -> datetime.timedelta:
    return datetime.timedelta(days=n)


# ===========================================================================
# 1. Semi-marathon in 12 weeks → end_date == event_date
# ===========================================================================

class TestSemiMarathon12Weeks:
    """Scenario: user sets a half-marathon 12 weeks from today."""

    def setup_method(self):
        today = _today()
        self.event_date = today + _days(12 * 7)  # exactly 12 weeks ahead
        self.standard_weeks = 12
        self.result = compute_cycle_dates(
            event_date=self.event_date,
            total_weeks=self.standard_weeks,
            today=today,
        )

    def test_end_date_equals_event_date(self):
        assert self.result["end_date"] == self.event_date

    def test_total_weeks_unchanged(self):
        assert self.result["total_weeks"] == self.standard_weeks

    def test_start_date_is_12_weeks_before_event(self):
        expected_start = self.event_date - _days(12 * 7)
        assert self.result["start_date"] == expected_start

    def test_status_is_active(self):
        # start_date == today, so the cycle begins exactly today → active
        assert self.result["status"] == "active"

    def test_current_week_is_one(self):
        assert self.result["current_week"] == 1

    def test_days_to_race_is_84(self):
        assert self.result["days_to_race"] == 84  # 12 × 7


# ===========================================================================
# 2. Marathon with caller-reduced total_weeks = 8 (time < standard 16w)
# ===========================================================================

class TestMarathonReducedCycle:
    """Scenario: caller has already capped total_weeks=8 (only 8 weeks left)."""

    def setup_method(self):
        today = _today()
        # Caller computed: weeks_available = 8 < 16 → total_weeks = 8
        self.event_date = today + _days(8 * 7)
        self.total_weeks = 8  # caller-reduced value passed in
        self.result = compute_cycle_dates(
            event_date=self.event_date,
            total_weeks=self.total_weeks,
            today=today,
        )

    def test_end_date_equals_event_date(self):
        assert self.result["end_date"] == self.event_date

    def test_total_weeks_is_8(self):
        assert self.result["total_weeks"] == 8

    def test_start_date_is_8_weeks_before_event(self):
        expected_start = self.event_date - _days(8 * 7)
        assert self.result["start_date"] == expected_start

    def test_status_is_active(self):
        assert self.result["status"] == "active"

    def test_current_week_is_one(self):
        assert self.result["current_week"] == 1

    def test_total_weeks_never_exceeds_passed_value(self):
        # Function returns total_weeks unchanged
        assert self.result["total_weeks"] == self.total_weeks


# ===========================================================================
# 3. No event_date → legacy behaviour (start today, standard duration)
# ===========================================================================

class TestNoEventDate:
    """Scenario: user has no event_date → preserve existing behaviour."""

    def setup_method(self):
        today = _today()
        self.today = today
        self.standard_weeks = 12
        self.result = compute_cycle_dates(
            event_date=None,
            total_weeks=self.standard_weeks,
            today=today,
        )

    def test_start_date_is_today(self):
        assert self.result["start_date"] == self.today

    def test_total_weeks_unchanged(self):
        assert self.result["total_weeks"] == self.standard_weeks

    def test_end_date_is_start_plus_standard_weeks(self):
        expected_end = self.today + _days(self.standard_weeks * 7)
        assert self.result["end_date"] == expected_end

    def test_event_date_is_none(self):
        assert self.result["event_date"] is None

    def test_days_to_race_is_none(self):
        assert self.result["days_to_race"] is None

    def test_status_is_active(self):
        # No event_date → always active, cycle starts today
        assert self.result["status"] == "active"

    def test_current_week_is_one(self):
        assert self.result["current_week"] == 1


# ===========================================================================
# 4. Status transitions
# ===========================================================================

class TestStatusUpcoming:
    """Scenario: event_date so far in the future that start_date > today."""

    def setup_method(self):
        today = _today()
        # Standard 12-week cycle, event 20 weeks away
        # → start_date = event - 12w = 8 weeks in the future
        self.event_date = today + _days(20 * 7)
        self.result = compute_cycle_dates(
            event_date=self.event_date,
            total_weeks=12,
            today=today,
        )

    def test_status_is_upcoming(self):
        assert self.result["status"] == "upcoming"

    def test_current_week_is_zero(self):
        assert self.result["current_week"] == 0

    def test_start_date_is_in_the_future(self):
        assert self.result["start_date"] > datetime.date.today()

    def test_end_date_equals_event_date(self):
        assert self.result["end_date"] == self.event_date

    def test_days_to_start_is_positive(self):
        assert self.result["days_to_start"] > 0

    def test_days_to_race_is_positive(self):
        assert self.result["days_to_race"] == 20 * 7


class TestStatusCompleted:
    """Scenario: event_date is in the past → status completed."""

    def setup_method(self):
        today = _today()
        self.event_date = today - _days(7)  # race was 1 week ago
        self.result = compute_cycle_dates(
            event_date=self.event_date,
            total_weeks=12,
            today=today,
        )

    def test_status_is_completed(self):
        assert self.result["status"] == "completed"

    def test_days_to_race_is_negative(self):
        assert self.result["days_to_race"] < 0

    def test_end_date_equals_event_date(self):
        assert self.result["end_date"] == self.event_date


class TestStatusActive:
    """Scenario: today is 3 weeks into a 12-week cycle (week 4).

    The cycle was set up when the race was 15 weeks away.  total_weeks=12 was
    stored in the DB (no reduction needed since 15 > 12).  Now, 3 weeks later,
    the race is 12 weeks away and we pass total_weeks=12 from the DB.
    start_date = event - 12*7 = today - 21 days  →  current_week = 4.
    """

    def setup_method(self):
        today = _today()
        # Race is 9 weeks from now; plan has total_weeks=12 stored in DB.
        # start = today + 63 - 84 = today - 21  →  week 4
        self.event_date = today + _days(9 * 7)
        self.total_weeks = 12
        self.result = compute_cycle_dates(
            event_date=self.event_date,
            total_weeks=self.total_weeks,
            today=today,
        )

    def test_status_is_active(self):
        assert self.result["status"] == "active"

    def test_current_week_is_4(self):
        assert self.result["current_week"] == 4

    def test_current_week_within_bounds(self):
        total = self.result["total_weeks"]
        week = self.result["current_week"]
        assert 1 <= week <= total


# ===========================================================================
# 5. Edge cases
# ===========================================================================

class TestEdgeCases:
    """Edge cases: minimum weeks, exact boundaries."""

    def test_very_short_time_caller_caps_to_one_week(self):
        """Caller caps total_weeks=1; function returns it unchanged."""
        today = _today()
        event_date = today + _days(3)  # only 3 days away
        result = compute_cycle_dates(event_date=event_date, total_weeks=1, today=today)
        assert result["total_weeks"] == 1

    def test_event_today_is_completed(self):
        today = _today()
        result = compute_cycle_dates(event_date=today, total_weeks=12, today=today)
        # today == end_date, cycle is over
        assert result["status"] == "completed"

    def test_current_week_clamped_to_total(self):
        """current_week must never exceed total_weeks."""
        today = _today()
        # Event 1 day away, total_weeks=12 → delta >> total_weeks
        event_date = today + _days(1)
        result = compute_cycle_dates(event_date=event_date, total_weeks=12, today=today)
        assert result["current_week"] <= result["total_weeks"]

    def test_time_available_greater_than_standard_total_weeks_unchanged(self):
        """Function returns total_weeks exactly as passed — no internal change."""
        today = _today()
        event_date = today + _days(30 * 7)  # 30 weeks, standard only 12
        result = compute_cycle_dates(event_date=event_date, total_weeks=12, today=today)
        assert result["total_weeks"] == 12


# ===========================================================================
# 6. effective_start_date — new plan whose theoretical start is already past
# ===========================================================================

class TestEffectiveStartDatePastTheoretical:
    """Scenario 1: new plan, theoretical start_date already passed.

    Race is 5 weeks away, standard cycle is 12 weeks.  Theoretical start
    would be 7 weeks in the past.  Passing effective_start_date=today must
    reset current_week to 1 and keep event_date/total_weeks unchanged.
    """

    def setup_method(self):
        today = _today()
        self.today = today
        self.event_date = today + _days(5 * 7)   # race in 5 weeks
        self.total_weeks = 12                      # standard recommended cycle
        self.result = compute_cycle_dates(
            event_date=self.event_date,
            total_weeks=self.total_weeks,
            today=today,
            effective_start_date=today,
        )

    def test_current_week_is_1(self):
        assert self.result["current_week"] == 1

    def test_status_is_active(self):
        assert self.result["status"] == "active"

    def test_total_weeks_unchanged(self):
        assert self.result["total_weeks"] == 12

    def test_event_date_unchanged(self):
        assert self.result["event_date"] == self.event_date

    def test_end_date_equals_event_date(self):
        assert self.result["end_date"] == self.event_date

    def test_start_date_is_today(self):
        assert self.result["start_date"] == self.today

    def test_days_to_race_unchanged(self):
        # days_to_race must still point at the real race date
        assert self.result["days_to_race"] == 5 * 7


class TestEffectiveStartDateSemiIn5Weeks:
    """Scenario 2: semi-marathon in 5 weeks / standard 12-week cycle.

    This is the canonical bug scenario from the problem statement.
    """

    def setup_method(self):
        today = _today()
        self.today = today
        self.event_date = today + _days(5 * 7)
        self.result = compute_cycle_dates(
            event_date=self.event_date,
            total_weeks=12,
            today=today,
            effective_start_date=today,
        )

    def test_current_week_is_1(self):
        assert self.result["current_week"] == 1

    def test_total_weeks_is_12(self):
        assert self.result["total_weeks"] == 12

    def test_event_date_unchanged(self):
        assert self.result["event_date"] == self.event_date

    def test_days_to_race_unchanged(self):
        assert self.result["days_to_race"] == 5 * 7


class TestEffectiveStartDateFutureStartUnchanged:
    """Scenario 4: future start — no effective_start_date → behaviour unchanged."""

    def test_upcoming_without_effective_start_date(self):
        today = _today()
        event_date = today + _days(20 * 7)
        result = compute_cycle_dates(event_date=event_date, total_weeks=12, today=today)
        assert result["status"] == "upcoming"
        assert result["current_week"] == 0

    def test_upcoming_with_effective_start_date_ignored_when_start_in_future(self):
        """effective_start_date has no effect when theoretical start is in the future."""
        today = _today()
        event_date = today + _days(20 * 7)  # start = today + 8*7 (future)
        effective = today + _days(8 * 7)    # same as theoretical start
        result = compute_cycle_dates(
            event_date=event_date,
            total_weeks=12,
            today=today,
            effective_start_date=effective,
        )
        # theoretical start is in the future → upcoming branch executes first
        assert result["status"] == "upcoming"


class TestEffectiveStartDateExactlyToday:
    """Scenario 5: theoretical start exactly today → week 1 (no effective_start_date needed)."""

    def test_start_today_is_week_1(self):
        today = _today()
        event_date = today + _days(12 * 7)
        result = compute_cycle_dates(event_date=event_date, total_weeks=12, today=today)
        assert result["current_week"] == 1
        assert result["status"] == "active"


class TestEffectiveStartDateRetrocompat:
    """Scenario 6: calls without effective_start_date remain backward-compatible."""

    def test_active_cycle_computes_current_week_normally(self):
        today = _today()
        # 3 weeks into a 12-week cycle
        event_date = today + _days(9 * 7)
        result = compute_cycle_dates(event_date=event_date, total_weeks=12, today=today)
        assert result["current_week"] == 4  # same as TestStatusActive

    def test_upcoming_not_affected(self):
        today = _today()
        event_date = today + _days(20 * 7)
        result = compute_cycle_dates(event_date=event_date, total_weeks=12, today=today)
        assert result["status"] == "upcoming"

    def test_no_event_date_legacy_unchanged(self):
        today = _today()
        result = compute_cycle_dates(event_date=None, total_weeks=12, today=today)
        assert result["status"] == "active"
        assert result["current_week"] == 1
