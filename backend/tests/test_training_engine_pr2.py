"""Regression tests for RunIndex PR2 — 4 corrections du plan d'entraînement.

Scope (per PR2):
  #1 Sortie longue: compute_long_run_km is the single source of truth and
     must NOT be silently capped again by 0.5 * target_km downstream.
  #2 VMA > 14 km/h: no arbitrary cap in the plan generation pipeline —
     an athlete with VMA > 14 km/h must keep that VMA through the plan.
  #3 Fallback VMA (speed_avg / 0.70): kept for now but flagged low
     confidence (see test_vma_confidence_flags_fallback_as_low).
  #4 Volume: compute_target_km must NOT jump straight to config["min"] —
     progression must be ≤ +10% of current volume (before phase multiplier).

Pure unit tests: no HTTP, no DB.
"""

import os
import sys

# Make the backend package importable when tests are run from the repo root.
_HERE = os.path.dirname(os.path.abspath(__file__))
_BACKEND = os.path.dirname(_HERE)
if _BACKEND not in sys.path:
    sys.path.insert(0, _BACKEND)

import inspect

import pytest

from training_engine import (
    PHASE_VOLUME_MULTIPLIERS,
    VOLUME_GOAL_CONFIG,
    compute_long_run_km,
    compute_target_km,
    vma_pace,
)


# ---------------------------------------------------------------------------
# #4 Volume — no brutal jump to config["min"], ≤ +10% progression
# ---------------------------------------------------------------------------


class TestComputeTargetKmProgression:
    """PR2 #4: current volume is the reference; progression ≤ +10%."""

    def test_15km_marathon_does_not_jump_to_config_min(self):
        # MARATHON min is 40 km/week — the plan must not impose 40 km on an
        # athlete currently running 15 km/week.
        target = compute_target_km(15, "MARATHON", "build")
        assert target < 40, (
            f"15 km/week athlete targeting marathon must NOT jump to config['min']=40. "
            f"Got target_km={target}."
        )
        # +10% max of 15 = 16.5 → round to 16 or 17 in build phase (multiplier 1.0)
        assert target <= round(15 * 1.10), (
            f"Progression must be ≤ +10% of current volume. Got {target} vs cap {round(15*1.10)}."
        )

    def test_25km_semi_does_not_jump_to_config_min(self):
        # SEMI min is 30 km/week — 25 km athlete must not jump to 30+.
        target = compute_target_km(25, "SEMI", "build")
        assert target < 30, (
            f"25 km/week athlete targeting semi must NOT jump to config['min']=30. "
            f"Got target_km={target}."
        )
        assert target <= round(25 * 1.10)

    def test_progression_never_exceeds_10_percent_build(self):
        # Build phase multiplier is 1.0 → the +10% cap must hold as-is.
        for goal in ("5K", "10K", "SEMI", "MARATHON", "ULTRA"):
            for current in (5, 10, 15, 20, 25, 30, 45, 60):
                target = compute_target_km(current, goal, "build")
                cap = round(min(VOLUME_GOAL_CONFIG[goal]["max"], current * 1.10))
                assert target <= cap, (
                    f"Build phase must not exceed +10% cap for goal={goal} current={current}: "
                    f"got {target}, cap {cap}."
                )

    def test_volume_close_to_min_does_not_snap_to_min(self):
        # Athlete already close to config["min"] must NOT get instantly bumped
        # to config["min"]; progression stays ≤ +10%.
        target = compute_target_km(29, "SEMI", "build")
        assert target <= round(29 * 1.10)

    def test_volume_close_to_max_is_capped_at_max(self):
        # Athlete near the ceiling: build phase must not go over config["max"].
        target = compute_target_km(118, "MARATHON", "build")
        assert target <= VOLUME_GOAL_CONFIG["MARATHON"]["max"]

    def test_zero_current_volume_returns_zero(self):
        # A brand-new athlete (0 km history) must not be shoved to config["min"].
        assert compute_target_km(0, "MARATHON", "build") == 0

    def test_phase_multiplier_applied_after_10_percent(self):
        # taper multiplier is 0.5 → 20 km/week SEMI in taper ≈ round(22*0.5)=11
        target = compute_target_km(20, "SEMI", "taper")
        expected = round(min(VOLUME_GOAL_CONFIG["SEMI"]["max"], 20 * 1.10) * PHASE_VOLUME_MULTIPLIERS["taper"])
        assert target == expected

    def test_no_max_current_config_min_pattern_remains(self):
        """Guard against the offending pattern reappearing in compute_target_km."""
        src = inspect.getsource(compute_target_km)
        assert "max(current_weekly_km, config[\"min\"])" not in src
        assert "max(current_weekly_km, config['min'])" not in src


# ---------------------------------------------------------------------------
# #1 Sortie longue — compute_long_run_km reste la source de vérité
# ---------------------------------------------------------------------------


class TestLongRunNotOverwritten:
    """PR2 #1: no second cap (e.g., ``long_run <= 0.5 * target_km``) shall
    silently overwrite compute_long_run_km.
    """

    def test_no_half_target_cap_in_llm_coach(self):
        """The forbidden pattern ``long_run <= 0.5 * target_km`` (or its
        equivalents like ``min(long_run, 0.5*target_km)``) must not appear
        anywhere in the plan-generation pipeline.
        """
        import llm_coach
        import coach_service
        for mod in (llm_coach, coach_service):
            src = inspect.getsource(mod)
            forbidden_patterns = [
                "long_run <= 0.5 * target_km",
                "min(long_run, 0.5 * target_km)",
                "min(target_long_run, 0.5 * target_km)",
                "long_run = min(long_run, 0.5",
                "target_long_run = min(target_long_run, 0.5",
            ]
            for pat in forbidden_patterns:
                assert pat not in src, (
                    f"Forbidden second-cap pattern detected in {mod.__name__}: {pat!r}."
                )

    def test_long_run_from_source_of_truth(self):
        # For a mid-range volume the long run must equal exactly what
        # compute_long_run_km returns — no further shrinking.
        cfg = VOLUME_GOAL_CONFIG["MARATHON"]
        target = round((cfg["min"] + cfg["max"]) / 2)
        long_run = compute_long_run_km(target, "MARATHON")
        # Bounded by long_min / long_max
        assert cfg["long_min"] <= long_run <= cfg["long_max"]

    def test_long_run_respects_bounds_for_all_goals(self):
        for goal, cfg in VOLUME_GOAL_CONFIG.items():
            for target in (cfg["min"], (cfg["min"] + cfg["max"]) // 2, cfg["max"]):
                lr = compute_long_run_km(target, goal)
                assert cfg["long_min"] <= lr <= cfg["long_max"], (
                    f"long_run out of bounds for goal={goal} target={target}: got {lr}."
                )


# ---------------------------------------------------------------------------
# #2 VMA > 14 km/h — pas de cap arbitraire dans le pipeline plan
# ---------------------------------------------------------------------------


class TestVMAAbove14NotCapped:
    """PR2 #2: an athlete with VMA > 14 km/h must NOT be capped to 14."""

    @pytest.mark.parametrize("vma", [14.5, 16.0, 18.0, 20.0])
    def test_vma_pace_reflects_actual_vma(self, vma):
        # vma_pace is the shared derivation used by the plan for all its
        # displayed target paces. It must scale with the real VMA — a hidden
        # cap at 14 would make all these paces collapse to the same value.
        pace_ref_14 = vma_pace(14.0, 0.85)
        pace_high = vma_pace(vma, 0.85)
        assert pace_high != pace_ref_14, (
            f"vma_pace for VMA={vma} equals the VMA=14 pace — a cap is likely present."
        )

    def test_no_hard_vma_cap_in_plan_pipeline(self):
        """Guard against reintroducing ``vma = 14`` / ``min(vma, 14)`` /
        ``vma * 3.5 > 70: vma = 14`` in the plan generation code.
        """
        import coach_service
        import llm_coach
        import training_engine
        for mod in (coach_service, llm_coach, training_engine):
            src = inspect.getsource(mod)
            # Explicit patterns from the PR2 audit
            forbidden = [
                "vma = 14",
                "vma=14",
                "estimated_vma = 14",
                "estimated_vma=14",
                "min(vma, 14)",
                "min(estimated_vma, 14)",
            ]
            for pat in forbidden:
                assert pat not in src, (
                    f"Forbidden arbitrary VMA cap {pat!r} detected in {mod.__name__}."
                )


# ---------------------------------------------------------------------------
# #3 VMA fallback speed_avg/0.70 — kept, but marked low confidence
# ---------------------------------------------------------------------------


class TestVMAFallbackConfidence:
    """PR2 #3: the fallback estimator ``speed_avg / 0.70`` is kept but must
    NOT be advertised as a reliable VMA. Confidence must be ``low``.
    """

    def test_fallback_still_exists(self):
        # We deliberately keep the fallback to avoid a wider refactor in PR2.
        import coach_service
        src = inspect.getsource(coach_service)
        assert "avg_speed / 0.70" in src, (
            "PR2 should preserve the /0.70 fallback (no refactor) — pattern missing."
        )

    def test_fallback_confidence_is_low(self):
        # Read the confidence map straight from the source to make sure the
        # 'average' branch (i.e., the /0.70 fallback) is flagged 'low'.
        import coach_service
        src = inspect.getsource(coach_service)
        # The exact assignment we expect after PR2.
        assert '"average": "low"' in src, (
            "PR2 #3: /0.70 fallback must be marked as low-confidence VMA."
        )
