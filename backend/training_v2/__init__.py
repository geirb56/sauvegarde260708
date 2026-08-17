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
R2A exposes:             PhysioSubscore, SleepSubscore, LoadSubscore,
                         ReadinessSubscores, build_physio_subscore,
                         build_sleep_subscore, build_load_subscore,
                         build_readiness_subscores.
R2B exposes:             ReadinessResult, ReadinessConfidence,
                         build_readiness_result.
PR130 exposes:           WeeklyTarget, build_weekly_target.
                         PriorRunningWindow (TrainingHistory extension).
PR131 exposes:           WorkoutPrescription, WeeklyPlan, build_weekly_plan.
PR132 exposes:           RecentTrainingResponse, WorkoutExecutionFacts,
                         build_recent_training_response, analyze_workout_execution.
PR133 exposes:           DailyAdaptationAction, DailyAdaptationResult,
                         build_daily_adaptation.
PR134 exposes:           WeeklyReconciliationAction, WeeklyReconciliationResult,
                         build_weekly_reconciliation.
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
from .readiness_subscores import (
    LoadSubscore,
    PhysioSubscore,
    ReadinessSubscores,
    SleepSubscore,
    build_load_subscore,
    build_physio_subscore,
    build_readiness_subscores,
    build_sleep_subscore,
)
from .readiness import (
    ReadinessConfidence,
    ReadinessResult,
    build_readiness_result,
)
from .readiness_decision import (
    ReadinessBand,
    ReadinessDecision,
    build_readiness_decision,
)
from .runner_profile import RunnerProfile, build_runner_profile
from .training_history import (
    PriorRunningWindow,
    TrainingHistory,
    TrainingWindow,
    build_training_history,
)
from .training_intensity import TrainingIntensityProfile, build_training_intensity_profile
from .training_load import TrainingLoadSnapshot, build_training_load
from .training_state import TrainingState, build_training_state
from .weekly_target import WeeklyTarget, build_weekly_target
from .workout_generator import WeeklyPlan, WorkoutPrescription, build_weekly_plan
from .training_response import (
    RecentTrainingResponse,
    WorkoutExecutionFacts,
    build_recent_training_response,
    analyze_workout_execution,
)
from .daily_adaptation import (
    DailyAdaptationAction,
    DailyAdaptationResult,
    build_daily_adaptation,
)
from .weekly_reconciliation import (
    WeeklyReconciliationAction,
    WeeklyReconciliationResult,
    build_weekly_reconciliation,
)

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
    "ReadinessSubscores",
    "SleepRecord",
    "SleepSubscore",
    "SufficiencyLevel",
    "PhysioSubscore",
    "LoadSubscore",
    "build_readiness_sufficiency",
    "build_physio_subscore",
    "build_sleep_subscore",
    "build_load_subscore",
    "build_readiness_subscores",
    "ReadinessConfidence",
    "ReadinessResult",
    "build_readiness_result",
    "ReadinessBand",
    "ReadinessDecision",
    "build_readiness_decision",
    "RunnerProfile",
    "build_runner_profile",
    "PriorRunningWindow",
    "TrainingHistory",
    "TrainingWindow",
    "build_training_history",
    "TrainingIntensityProfile",
    "build_training_intensity_profile",
    "TrainingLoadSnapshot",
    "build_training_load",
    "TrainingState",
    "build_training_state",
    "WeeklyTarget",
    "build_weekly_target",
    "WeeklyPlan",
    "WorkoutPrescription",
    "build_weekly_plan",
    "RecentTrainingResponse",
    "WorkoutExecutionFacts",
    "build_recent_training_response",
    "analyze_workout_execution",
    "DailyAdaptationAction",
    "DailyAdaptationResult",
    "build_daily_adaptation",
    "WeeklyReconciliationAction",
    "WeeklyReconciliationResult",
    "build_weekly_reconciliation",
]
