"""training_v2 — Pure business layer for RunIndex v2.

PR05 exposes: TrainingWindow, TrainingHistory, build_training_history.
"""

from .training_history import TrainingHistory, TrainingWindow, build_training_history

__all__ = ["TrainingHistory", "TrainingWindow", "build_training_history"]
