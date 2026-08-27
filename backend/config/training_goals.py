"""Single source of truth for GOAL_CONFIG — training goal display parameters.

PR145: Extracted from training_engine.py to eliminate legacy runtime dependency.
This module is the canonical owner of GOAL_CONFIG for all runtime consumers.
"""

GOAL_CONFIG = {
    "5K": {
        "cycle_weeks": 6,
        "long_run_ratio": 0.25,
        "intensity_pct": 20,
        "description": "5 kilometers"
    },
    "10K": {
        "cycle_weeks": 8,
        "long_run_ratio": 0.30,
        "intensity_pct": 18,
        "description": "10 kilometers"
    },
    "SEMI": {
        "cycle_weeks": 12,
        "long_run_ratio": 0.35,
        "intensity_pct": 15,
        "description": "Half-marathon"
    },
    "MARATHON": {
        "cycle_weeks": 16,
        "long_run_ratio": 0.40,
        "intensity_pct": 12,
        "description": "Marathon"
    },
    "ULTRA": {
        "cycle_weeks": 20,
        "long_run_ratio": 0.45,
        "intensity_pct": 10,
        "description": "Ultra-trail"
    },
    # PR204: MAINTENANCE — values derived from canonical existing sources.
    # cycle_weeks=12: periodization.py CONTINUOUS_CYCLE_LENGTH_WEEKS=12
    #                 and coach_service.py GOAL_METADATA["MAINTENANCE"]["base_weeks"]=12
    # long_run_ratio=0.30: same as 10K (conservative base training, no race-specific ramp)
    # intensity_pct=15: build phase in training_engine.get_phase_description (lines 678, 715)
    # These fields are used only in the /training/goals display listing and the legacy
    # generate_dynamic_training_plan; the V2 engine (build_weekly_plan_from_workouts) does
    # not consume them for MAINTENANCE.
    "MAINTENANCE": {
        "cycle_weeks": 12,    # canonical: CONTINUOUS_CYCLE_LENGTH_WEEKS (periodization.py:135)
        "long_run_ratio": 0.30,  # canonical: 10K entry above (moderate base, no race ramp)
        "intensity_pct": 15,  # canonical: build phase (training_engine.py:678,715)
        "description": "Maintenance"
    }
}
