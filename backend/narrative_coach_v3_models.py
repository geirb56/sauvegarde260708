"""C355 additive presentation contract; factual V2/V3 models remain unchanged."""

from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field

from workout_intelligence_v3_models import WorkoutIntelligenceV3Response


class NarrativeCoachV3(BaseModel):
    model_config = ConfigDict(extra="forbid")

    headline: str = ""
    analysis: str = ""
    interpretation: str = ""
    recommendation: Optional[str] = None
    limitations: list[str] = Field(default_factory=list)
    evidence_refs: list[str] = Field(default_factory=list)
    language: Literal["fr", "en", "es"] = "en"
    generation_mode: Literal["llm_validated", "deterministic_fallback", "none"] = "none"


class WorkoutIntelligenceV3NarrativeResponse(WorkoutIntelligenceV3Response):
    narrative_coach_v3: NarrativeCoachV3 = Field(default_factory=NarrativeCoachV3)
