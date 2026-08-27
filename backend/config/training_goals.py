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
    # PR204: MAINTENANCE — cycle_weeks=12 derived from canonical constant
    # CONTINUOUS_CYCLE_LENGTH_WEEKS (periodization.py:135) and
    # coach_service.py GOAL_METADATA["MAINTENANCE"]["base_weeks"]=12.
    #
    # long_run_ratio and intensity_pct are NOT applicable to MAINTENANCE:
    #   - these fields are consumed only by GET /training/goals (display listing)
    #   - they are never used in plan generation for MAINTENANCE (V2 engine does not read them)
    #   - no canonical MAINTENANCE-specific ratio or intensity exists in this codebase
    # Values are set to None; the /training/goals handler omits None fields from its response.
    "MAINTENANCE": {
        "cycle_weeks": 12,        # canonical: CONTINUOUS_CYCLE_LENGTH_WEEKS (periodization.py:135)
        "long_run_ratio": None,   # not applicable — no canonical MAINTENANCE ratio in codebase
        "intensity_pct": None,    # not applicable — no canonical MAINTENANCE intensity in codebase
        "description": "Maintenance"
    }
}
