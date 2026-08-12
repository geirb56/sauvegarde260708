"""training_v2 — Pure business layer for RunIndex v2.

PR05 (PlanGoal) exposes: PlanGoal, GoalType, build_plan_goal.
PR05 (History) exposes:  DomainActivity, TrainingWindow, TrainingHistory, build_training_history.
PR06 (Load)    exposes:  TrainingLoadSnapshot, build_training_load.
PR06 (Period.) exposes:  PeriodizationSnapshot, PeriodizationPhase,
                         PeriodizationMode, build_periodization.
PR07 exposes:            RunnerProfile, build_runner_profile.
PR04 exposes:            TrainingState, build_training_state.
R1   exposes:            ReadinessSufficiency, ReadinessSufficiencyInput,
                         SufficiencyLevel, ReasonCode, PhysioSignal, PhysioBaseline,
                         SleepRecord, build_readiness_sufficiency.
R1.7B exposes:           TrainingIntensityProfile, build_training_intensity_profile.
"""

from .domain_activity import DomainActivity
from .domain_capabilities import DomainCapabilities
from .periodization import (
    PeriodizationMode,
    PeriodizationPhase,
    PeriodizationSnapshot,
    build_periodization,
)
from .plan_goal import GoalType, PlanGoal, build_plan_goal
from .readiness_sufficiency import (
    PhysioBaseline,
    PhysioSignal,
    ReasonCode,
    ReadinessSufficiency,
    ReadinessSufficiencyInput,
    SleepRecord,
    SufficiencyLevel,
    build_readiness_sufficiency,
)
from .runner_profile import RunnerProfile, build_runner_profile
from .training_history import TrainingHistory, TrainingWindow, build_training_history
from .training_intensity import TrainingIntensityProfile, build_training_intensity_profile
from .training_load import TrainingLoadSnapshot, build_training_load
from .training_state import TrainingState, build_training_state

__all__ = [
    "DomainActivity",
    "DomainCapabilities",
    "GoalType",
    "PlanGoal",
    "build_plan_goal",
    "PeriodizationMode",
    "PeriodizationPhase",
    "PeriodizationSnapshot",
    "build_periodization",
    "PhysioBaseline",
    "PhysioSignal",
    "ReasonCode",
    "ReadinessSufficiency",
    "ReadinessSufficiencyInput",
    "SleepRecord",
    "SufficiencyLevel",
    "build_readiness_sufficiency",
    "RunnerProfile",
    "build_runner_profile",
    "TrainingHistory",
    "TrainingWindow",
    "build_training_history",
    "TrainingIntensityProfile",
    "build_training_intensity_profile",
    "TrainingLoadSnapshot",
    "build_training_load",
    "TrainingState",
    "build_training_state",
]
