"""C400 — automatic session comment written by the C396 Coach.

C388/Workout Analysis V2 stay the source of facts; C396 only supplies the voice.
The generated text is never a source of truth. It passes a conservative,
deterministic *heuristic* guard (NOT a proof of factual accuracy): any claim the
guard cannot tie to the selected session's facts makes the comment fall back to
the C388 deterministic narrative.

Cache and in-flight dedupe are process-local and read/write no database.
No provider is reached from workers: this module is only called from a route.
"""

import asyncio
import copy
import hashlib
import json
import logging
import os
import re
import time
from collections import OrderedDict
from typing import Any, Optional

from pydantic import BaseModel

import llm_coach

logger = logging.getLogger(__name__)

COACH_COMMENT_VERSION = "c403-session-comment-v4"
COMMENT_SOURCE = "coach_c396"
VALIDATION_LEVEL = "heuristic_guard"  # explicitly not "factually validated"
COMMENT_TIMEOUT_SEC = 20
SUCCESS_TTL_SEC = 6 * 3600
FAILURE_TTL_SEC = 60
CACHE_MAX = 512
MIN_CHARS, MAX_CHARS = 40, 900


class CoachSessionCommentValidation(BaseModel):
    level: str = VALIDATION_LEVEL
    passed: bool = False
    rejected_checks: list[str] = []


class CoachSessionCommentResponse(BaseModel):
    """Distinct from the C388 narrative: never replaces headline/analysis/interpretation."""
    workout_id: str
    language: str
    status: str  # generated | fallback | unavailable | disabled
    text: Optional[str] = None
    cached: bool = False
    source: str = COMMENT_SOURCE
    coach_version: str = COACH_COMMENT_VERSION
    model: Optional[str] = None
    validation: CoachSessionCommentValidation = CoachSessionCommentValidation()
    fallback: str = "deterministic_c388"


def comment_enabled() -> bool:
    """Off by default: activation is an explicit product decision (see C400 report)."""
    return os.environ.get("C400_SESSION_COMMENT_ENABLED", "").strip().lower() in {"1", "true", "yes"}



# ------------------------------------------------------------ context selection

HISTORY_MAX_SESSIONS = 5
MIN_HISTORY_SESSIONS = 3  # below this, no habit/volume figure is derived
_HISTORY_FIELDS = ("date", "type", "distance_km", "duration_minutes", "avg_pace_display",
                   "avg_speed_kmh", "avg_heart_rate", "max_heart_rate", "elevation_gain_m")
_RACE_GOALS = {"5K", "10K", "SEMI", "HALF_MARATHON", "MARATHON", "ULTRA"}
_KNOWN_GOALS = _RACE_GOALS | {"MAINTENANCE"}


def _provably_prior(sessions: list, detail: dict, llm_context: dict) -> list:
    """Keep only sessions whose antecedence to the analysed one is demonstrated (C403).

    The shared context deliberately keeps same-day sessions when the selected session has
    only a date ("date_inclusive"); here, a bare date proves nothing about order, so a
    same-day session is kept only when both timestamps are known and strictly ordered.
    Unparseable or undated sessions are dropped.
    """
    from coach_context_v2 import _provable_order, _parse_iso_date

    raw = detail.get("start_time") or detail.get("date") or llm_context.get("selected_workout_history_cutoff")
    if _parse_iso_date(raw) is None:
        return []
    kept, seen = [], set()
    for item in sessions:
        if _provable_order(item.get("date"), raw) != "before":
            continue
        key = str(item.get("id") or "") or (item.get("date"), item.get("distance_km"), item.get("duration_minutes"))
        if key in seen:
            continue
        seen.add(key)
        kept.append(item)
    return kept


def _date_part(value: Any) -> Optional[str]:
    text = str(value or "")[:10]
    return text or None


def _history_block(prior: list, shown: list, coverage: dict, llm_context: dict) -> dict:
    """C408-C: counts and criteria of the history shown to the Coach, produced at the source.

    The listed sessions are a bounded selection; the statistics of runner_profile use every
    eligible session. eligible_count adds the sessions the shared context already dropped
    upstream (its own cap) to the provably prior ones, so truncated never hides exclusions.
    """
    available, included = coverage.get("available_count"), coverage.get("included_count")
    counted = isinstance(available, int) and isinstance(included, int) and not isinstance(available, bool)
    upstream_excluded = max(0, available - included) if counted else 0
    strict = coverage.get("strictly_prior_available_count")
    if isinstance(strict, int) and not isinstance(strict, bool):
        # Counted upstream before the cap with the same strict antecedence rule as `prior`.
        eligible = max(len(prior), strict)
        counted = True
    else:
        eligible = len(prior) + upstream_excluded
    population_truncated = bool(coverage.get("truncated"))
    block: dict = {
        "scope": "sessions provably before the analysed session; same-day sessions are kept only "
                 "when their timestamp proves they started earlier",
        "observation_window_days": coverage.get("window_days"),
        "eligible_count": eligible,
        "included_count": len(shown),
        "truncated": eligible > len(shown) or population_truncated,
        "window": {
            "start_date_inclusive": coverage.get("start_date_inclusive"),
            "end": "analysed session start (exclusive)"
                   if llm_context.get("selected_workout_history_cutoff_precision") == "strict_timestamp_exclusive"
                   else "analysed session date",
        },
        "cutoff_precision": llm_context.get("selected_workout_history_cutoff_precision"),
        "eligibility": "same athlete, any recorded activity strictly before the analysed session, "
                       "inside the window; undated or unparseable sessions are dropped",
        "selection": f"the {HISTORY_MAX_SESSIONS} most recent eligible sessions, listed most recent first; "
                     "nothing else is implied about their similarity to the analysed session",
        "sessions": [{k: w[k] for k in _HISTORY_FIELDS if w.get(k) is not None} for w in shown],
        "trend": "not_established",
    }
    if population_truncated and not counted:
        block["eligible_count_is_lower_bound"] = True
    return block


def build_comment_context(llm_context: dict) -> dict:
    """C402: what the automatic comment may see, in five labelled categories.

    Selected from the shared Coach context, never a copy of it. Dropped on purpose:
    Training V2 week/today, current phase, readiness, load, performance and paces (they
    describe today, not the session), free-text titles (not evidence) and ids.
    Historical context is strictly the sessions before the selected one (the shared
    context already applies that cut-off); the declared goal is the CURRENT one, labelled
    as such, because no goal history exists.
    """
    detail = copy.deepcopy(llm_context.get("workout_detail") or {})
    out: dict = {"language": llm_context.get("language")}
    if not detail:
        return out
    detail.pop("name", None)
    workout = ((detail.get("analysis") or {}).get("workout"))
    if isinstance(workout, dict):
        workout.pop("name", None)
    permissions = copy.deepcopy(llm_context.get("selected_workout_permissions") or {})
    out["workout_detail"] = detail  # A. analysed session
    out["selected_workout_permissions"] = permissions
    for key in ("observed_lap_pattern", "validated_workout_observations", "selected_workout_history_cutoff",
                "selected_workout_history_cutoff_precision"):
        if key in llm_context:
            out[key] = copy.deepcopy(llm_context[key])

    coverage = llm_context.get("recent_workouts_coverage") or {}
    prior = _provably_prior(
        [w for w in (llm_context.get("recent_workouts") or []) if isinstance(w, dict)],
        detail, llm_context)
    prior.sort(key=lambda w: str(w.get("date") or ""), reverse=True)
    shown = prior[:HISTORY_MAX_SESSIONS]
    out["history_as_of_session"] = _history_block(prior, shown, coverage, llm_context)  # B
    profile: dict = {"experience": "not_provided"}  # C. only what is observed
    population_truncated = bool(coverage.get("truncated"))
    if len(prior) >= MIN_HISTORY_SESSIONS and not population_truncated:
        kms = [float(w["distance_km"]) for w in prior
               if isinstance(w.get("distance_km"), (int, float)) and not isinstance(w["distance_km"], bool)]
        observed = {"sessions_count": len(prior)}
        profile["population"] = {
            "scope": "every eligible earlier session in the window, not only the sessions listed in "
                     "history_as_of_session.sessions",
            "sessions_count": len(prior),
            "period_start": _date_part(prior[-1].get("date")),
            "period_end": _date_part(prior[0].get("date")),
        }
        # A missing distance is unknown, never zero: figures cover only the sessions that
        # record one, and only when there are enough of them to be a habit figure.
        if len(kms) >= MIN_HISTORY_SESSIONS:
            if len(kms) != len(prior):  # absent means every session records a distance
                observed["sessions_with_distance_count"] = len(kms)
            observed["total_km"] = round(sum(kms), 1)
            observed["avg_km_per_session"] = round(sum(kms) / len(kms), 1)
        profile["observed_training"] = observed
    out["runner_profile"] = profile
    goal = llm_context.get("goal") or {}
    goal_type = str(goal.get("goal_type") or "").upper()
    if goal_type in _KNOWN_GOALS:  # D. current declared goal, general relevance only
        out["declared_goal"] = {
            "goal_type": goal_type,
            "status": "current_declared_goal",
            "historical_goal_status": "unknown",  # no goal history is stored: neither confirmed nor excluded
            "is_race_goal": goal_type in _RACE_GOALS,
            "usage": "general relevance only; it does not show the session was designed for it "
                     "or that this goal applied on the session date",
        }
    out["reliable_physiology"] = {  # E. nothing beyond the established permissions
        "intensity_interpretation_allowed": permissions.get("intensity_interpretation_allowed") is True,
        "lt1_lt2_vo2max_fcmax": "not_provided",
    }
    return out


# Keys that only carry a database/Garmin/plan identifier. They stay in the backend (access control,
# retrieval, traceability go through the request and the V3 loader, not through the prompt) and are
# not repeated in the LLM prompt, where they give no sporting information.
_ID_KEYS = {"workout_ids", "workout_id", "garmin_activity_id", "activity_id", "external_id",
            "prescription_id", "user_id"}


def strip_technical_ids(value: Any, selected_id: str = "") -> Any:
    """Remove identifier-only fields; observation/source links use source_path and codes, not ids."""
    if isinstance(value, dict):
        return {k: strip_technical_ids(v, selected_id) for k, v in value.items()
                if k not in _ID_KEYS and not (k == "id" and selected_id and str(v) == selected_id)}
    if isinstance(value, list):
        return [strip_technical_ids(v, selected_id) for v in value]
    return value


def build_session_chat_context(llm_context: dict) -> dict:
    """C408-B: selected context for a question about a selected historical workout.

    Same selection as the automatic comment (no today plan, readiness, load, predictions,
    paces or free-text title), plus the C408 coaching frame (V3 evaluations, recorded
    historical prescription, limits) and the coach-access flag.
    """
    out = build_comment_context(llm_context)
    for key in ("session_coaching_frame", "coach_workout_analysis_allowed", "validated_workout_observations"):
        if key in llm_context:
            out[key] = copy.deepcopy(llm_context[key])
    return strip_technical_ids(out, selected_id=str((llm_context.get("workout_detail") or {}).get("id") or ""))


def _analysis_observations(analysis: dict) -> list:
    """Observations in priority order, each fact once: synthesis, then Coach Language, then factual V2."""
    out: list = []
    seen: set = set()
    replaced: set = set()

    def add(source: str, item: Any) -> None:
        if not isinstance(item, dict) or not item.get("code") or not item.get("text") or item["code"] in seen:
            return
        seen.add(item["code"])
        replaced.update(item.get("replaces_factual_codes") or [])
        out.append({"code": item["code"], "source": source, "text": item["text"]})

    synthesis = analysis.get("session_synthesis")
    if isinstance(synthesis, dict) and synthesis.get("status") == "available":
        for item in [synthesis.get("primary")] + list(synthesis.get("supporting") or []):
            add("v2_synthesis", item)
    language = analysis.get("coach_language")
    for item in (language.get("conclusions") if isinstance(language, dict) else None) or []:
        add("v2_coach_language", item)
    meaning = analysis.get("meaning") if isinstance(analysis.get("meaning"), dict) else {}
    for item in meaning.get("factual_observations") or []:
        if isinstance(item, dict) and item.get("code") not in replaced:
            add("v2_factual", item)
    return out


def _session_block(detail: dict, structured: bool) -> dict:
    """Identity and measures of the session; whole-session averages only when no structure replaces them."""
    from coach_context_v2 import _usable_hr

    block = {
        "date": detail.get("date"), "type": detail.get("type"),
        "distance_km": detail.get("distance_km"), "duration_minutes": detail.get("duration_minutes"),
        "max_hr_bpm": _usable_hr(detail.get("max_hr")), "elevation_gain_m": detail.get("elevation_gain_m"),
    }
    if not structured:  # an average over warm-up, repetitions and recoveries says little about what was run
        block.update({"avg_pace": detail.get("avg_pace_display"), "avg_hr_bpm": _usable_hr(detail.get("avg_hr"))})
    block["first_km_splits"] = detail.get("km_splits")
    block["hr_zone_distribution"] = detail.get("zones")
    return {k: v for k, v in block.items() if v not in (None, [], {})}


def _pacing_observation(pacing: Any) -> Optional[dict]:
    """Split pacing from V2. The server projects paces to ``*_display`` strings (numeric keys removed);
    the numeric ``*_min_km`` fields are only a fallback for an unprojected context."""
    from coach_context_v2 import _format_pace_delta_min_km, _format_pace_min_km

    if not isinstance(pacing, dict) or not pacing.get("available"):
        return None

    def pace(display_key: str, numeric_key: str, fmt) -> Optional[str]:
        if pacing.get(display_key):
            return pacing[display_key]
        return fmt(pacing[numeric_key]) if pacing.get(numeric_key) is not None else None

    item = {
        "code": "split_pacing", "source": "v2_pacing",
        "fastest_split": pace("fastest_split_display", "fastest_split_min_km", _format_pace_min_km),
        "slowest_split": pace("slowest_split_display", "slowest_split_min_km", _format_pace_min_km),
        "pace_drop": pace("pace_drop_display", "pace_drop_min_km", _format_pace_delta_min_km),
        "negative_split": pacing.get("negative_split"),
    }
    return item if any(v is not None for k, v in item.items() if k not in {"code", "source"}) else None


def _limitation_items(analysis: dict, frame: dict, recorded_present: bool) -> list:
    """Every uncertainty expressed by V2, V3 and the evidence contract, as (code, text) for consolidation."""
    items: list = []
    for source in (analysis.get("limitations"),
                   ((analysis.get("session_synthesis") or {}).get("limitations")
                    if isinstance(analysis.get("session_synthesis"), dict) else None)):
        items += [(i.get("code"), i.get("text")) for i in source or [] if isinstance(i, dict)]
    phases = analysis.get("phase_analysis") if isinstance(analysis.get("phase_analysis"), dict) else {}
    if recorded_present and phases.get("limitations"):
        items.append(("limitations.phase_quality", None))
    v3 = frame.get("v3_assessment") if isinstance(frame.get("v3_assessment"), dict) else {}
    classification = v3.get("classification") or {}
    relative = classification.get("relative_effort") or {}
    comparison = v3.get("historical_comparison") or {}
    coach = v3.get("coach_assessment") or {}
    items += [(code, None) for code in (classification.get("limitations") or []) + (
        (v3.get("intensity") or {}).get("limitations") or [])]
    items += [(i.get("code"), i.get("text")) for i in coach.get("limitations") or [] if isinstance(i, dict)]
    for provenance in (relative.get("provenance"), comparison.get("provenance")):
        items += [(code, None) for code in ((provenance or {}).get("known_limits") or [])]
    contract = frame.get("evidence_contract") or {}
    not_demonstrated = contract.get("not_demonstrated") or {}
    for key in ("hr_rise_is_not_external_intensity", "relative_hr_is_not_easy_effort"):
        if key in not_demonstrated:  # these change how a conclusion may be worded; the others are permissions
            items.append((key, not_demonstrated[key]))
    return items


def build_conversation_context(llm_context: dict) -> dict:
    """C421: context of a chat question about a selected workout, rebuilt for a conversation.

    Same sources as build_session_chat_context (kept as is) but projected, not copied: sporting
    information by priority (recorded structure, inferred structure, observations, validated
    comparisons, athlete context) followed by the conclusions allowed, the limits that can still
    change a conclusion (each uncertainty once) and the scientific permissions. Nothing is
    recomputed; V2/V3 outputs elsewhere are untouched.
    """
    from coach_context_v2 import (
        compact_allowed_conclusions, compact_inferred_structure, compact_recorded_prescription,
        compact_recorded_structure, compact_validated_comparisons, comparison_limit_topics,
        consolidate_limitations,
    )

    frame_source = llm_context.get("session_coaching_frame")
    access = llm_context.get("coach_workout_analysis_allowed")
    raw_validated = llm_context.get("validated_workout_observations")
    llm_context = build_comment_context(llm_context)  # C400 selection (history, goal, permissions); unchanged
    detail = llm_context.get("workout_detail")
    out: dict = {"language": llm_context.get("language"), "coach_workout_analysis_allowed": access}
    if not isinstance(detail, dict) or not detail:
        narrative = _narrative_observations(raw_validated, False, False)  # V3 observations exist without a detail
        if narrative:
            out["key_observations"] = narrative
        return {k: v for k, v in out.items() if v is not None}
    analysis = detail.get("analysis") if isinstance(detail.get("analysis"), dict) else {}
    frame = frame_source if isinstance(frame_source, dict) else {}

    recorded = compact_recorded_structure(analysis.get("phase_analysis"))
    recorded_present = recorded["status"] == "recorded_by_garmin"
    if recorded_present:  # recorded phases outrank any inference from laps
        inferred = {"status": "not_used_recorded_structure_available"}
    else:
        inferred = compact_inferred_structure(llm_context.get("observed_lap_pattern"))
    inferred_present = inferred.get("status") == "pattern_observed"
    structured = recorded_present or inferred_present

    v3 = frame.get("v3_assessment") if isinstance(frame.get("v3_assessment"), dict) else {}
    probable_type = (v3.get("classification") or {}).get("probable_type", "unknown")
    comparisons = compact_validated_comparisons(frame, analysis)
    prescription = compact_recorded_prescription(frame)
    prescription_usable = prescription.get("status") == "recorded_before_session"
    observations = _analysis_observations(analysis)
    pacing = _pacing_observation(analysis.get("pacing"))
    if pacing:
        observations.append(pacing)
    validated = llm_context.get("validated_workout_observations")
    observations += _narrative_observations(validated, bool(comparisons), prescription_usable)
    if not prescription_usable:
        observations = [o for o in observations if "prescription" not in str(o.get("code"))]

    history = llm_context.get("history_as_of_session") or {}
    window = history.get("window") or {}
    athlete: dict = {"history_before_session": {
        "eligible_count": history.get("eligible_count"), "included_count": history.get("included_count"),
        "truncated": history.get("truncated"), "window_start": window.get("start_date_inclusive"),
        "observation_window_days": history.get("observation_window_days"),
        "cutoff_precision": llm_context.get("selected_workout_history_cutoff_precision"),
        "sessions_most_recent_first": history.get("sessions") or [],
        "note": "only sessions provably before this one; similarity to it is not implied; no trend established",
    }}
    profile = llm_context.get("runner_profile") or {}
    if profile.get("observed_training"):
        athlete["observed_training_before_session"] = {**profile["observed_training"],
                                                      **(profile.get("population") or {})}
        athlete["observed_training_before_session"].pop("scope", None)
    goal = llm_context.get("declared_goal")
    if isinstance(goal, dict):
        athlete["declared_goal"] = {
            "goal_type": goal.get("goal_type"), "is_race_goal": goal.get("is_race_goal"),
            "status": "current_declared_goal", "valid_at_session_date": "unknown",
            "usage": "general relevance only; not proof that the session was designed for it",
        }
    athlete["recorded_prescription"] = prescription

    limitations = consolidate_limitations(
        _limitation_items(analysis, frame, recorded_present),
        structure_present=structured, comparisons_present=bool(comparisons),
        session_type_unknown=probable_type == "unknown",
        structure_has_hr='"avg_hr_bpm"' in json.dumps([recorded, inferred]),
        attached_topics=comparison_limit_topics(comparisons),
    )
    permissions = copy.deepcopy(llm_context.get("selected_workout_permissions") or {})
    reliable = llm_context.get("reliable_physiology") or {}
    scientific = {
        "selected_workout_permissions": permissions,
        "physiological_references": reliable.get("lt1_lt2_vo2max_fcmax", "not_provided"),
        "not_measured": ["recovery_state", "sensations_or_perceived_effort"],
    }
    out.update({
        "session": _session_block(detail, structured),
        "recorded_structure": recorded,
        "inferred_structure": inferred,
        "key_observations": observations,
        "validated_comparisons": comparisons,
        "athlete_context": athlete,
        "allowed_conclusions": compact_allowed_conclusions(frame, prescription_usable=prescription_usable),
        "material_limitations": limitations,
        "scientific_permissions": scientific,
    })
    return strip_technical_ids(_prune(out), selected_id=str(detail.get("id") or ""))


def _narrative_observations(validated: Any, with_interpretation: bool, prescription_usable: bool) -> list:
    """V3 narrative headline/analysis (and interpretation when comparisons exist). Its own limitations go through
    material_limitations; a sentence about a prescription is dropped unless it was recorded before the session."""
    out: list = []
    if not isinstance(validated, dict):
        return out
    for key in ("headline", "analysis", "interpretation"):
        if key == "interpretation" and not with_interpretation:
            continue
        text = validated.get(key)
        if text and not prescription_usable:
            text = _without_prescription_sentences(text)
        if text:
            out.append({"code": f"narrative.{key}", "source": "v3_narrative", "text": text})
    return out


def _without_prescription_sentences(text: str) -> str:
    """Drop the sentences that speak of a prescription (FR/EN/ES stem 'prescri'), keep the rest."""
    sentences = re.split(r"(?<=[.!?])\s+", text.strip())
    return " ".join(s for s in sentences if "prescri" not in s.lower())


def _prune(value: Any) -> Any:
    """Drop None values; empty containers named by the contract stay, so the shape is stable."""
    if isinstance(value, dict):
        return {k: _prune(v) for k, v in value.items() if v is not None}
    if isinstance(value, list):
        return [_prune(v) for v in value]
    return value


def build_comparison_chat_context(turn: dict, language: str) -> dict:
    """C418: read-only context of a C409 comparison turn, built only from its computed contract.

    No Training V2 payload, readiness, load or prediction: a comparison never uses the athlete's
    current state as evidence of the state on the sessions' dates. C409 stays the authority for values.
    """
    contract = copy.deepcopy(turn["contract"])
    return {
        "language": language,
        "coach_workout_analysis_allowed": True,
        "comparison_request": {
            "nature": contract.get("kind"),
            "focus": turn.get("focus"),
            "explanation_requested": bool(turn.get("why")),
        },
        "comparison_contract": contract,
        # Deterministic C409 rendering: reference for the already computed gaps, not a reply.
        "comparison_computed_summary": turn.get("text"),
        "comparison_notes": [
            "Values, gaps and missing data come from RunIndex; explain them without recomputing.",
            "comparison_computed_summary holds the gaps already computed by RunIndex: reuse its figures, never restate it as a report.",
            "Only allowed_interpretations are supported; undemonstrated_conclusions must not be concluded.",
        ],
    }


# ------------------------------------------------------------------ fact scope

def _walk(value: Any, path: tuple, out: list) -> None:
    if isinstance(value, dict):
        for key, item in value.items():
            _walk(item, path + (str(key).lower(),), out)
    elif isinstance(value, (list, tuple)):
        for item in value:
            _walk(item, path, out)
    elif isinstance(value, bool) or value is None:
        return
    elif isinstance(value, (int, float, str)):
        out.append((path, value))


def _sub_population(comparison: dict, name: str):
    block = (((comparison.get("provenance") or {}).get("sub_populations")) or {}).get(name)
    return block.get("activity_count") if isinstance(block, dict) else None


def _frame_facts(context: dict) -> tuple[dict, dict]:
    """(session measures, comparison references) from the C408 frame, copied from V3 (not recomputed).

    Session measures: this activity's own HR figures and the size of its reference populations.
    Comparison references: historical quartiles/median and signed differences. They are values of
    OTHER sessions or derived gaps, so they never join the pool that grounds "your average HR was X".
    """
    frame = context.get("session_coaching_frame")
    if not isinstance(frame, dict) or not isinstance(frame.get("v3_assessment"), dict):
        return {}, {}
    v3 = frame["v3_assessment"]
    relative = ((v3.get("classification") or {}).get("relative_effort")) or {}
    comparison = v3.get("historical_comparison") or {}
    session = {
        "relative_hr": {k: relative.get(k) for k in ("current_hr_bpm", "reference_count")},
        "comparison_count": comparison.get("reference_count"),
        # Metric-specific V3 populations (pace at comparable HR / HR at comparable pace); "pace" stays out of the key so the count is not read as a pace.
        "comparison_count_metric_a": _sub_population(comparison, "pace_at_comparable_hr"),
        "comparison_count_metric_b": _sub_population(comparison, "hr_at_comparable_pace"),
        "session_max_hr_bpm": (v3.get("intensity") or {}).get("session_max_hr_bpm"),
    }
    references: dict = {
        "relative_hr": {k: relative.get(k) for k in ("hr_q1_bpm", "hr_median_bpm", "hr_q3_bpm")},
    }
    for key in ("pace_difference_sec_per_km_at_comparable_hr", "hr_difference_bpm_at_comparable_pace"):
        if comparison.get(key) is not None:
            references[key] = comparison[key]
    return session, references


def v3_comparison_available(context: dict) -> bool:
    """True when V3 itself supplies a usable comparison (relative HR or comparable-effort), whatever V2 says."""
    frame = context.get("session_coaching_frame")
    v3 = frame.get("v3_assessment") if isinstance(frame, dict) else None
    if not isinstance(v3, dict):
        return False
    relative = (v3.get("classification") or {}).get("relative_effort") or {}
    comparison = v3.get("historical_comparison") or {}
    return relative.get("status") == "used" or (
        comparison.get("status") == "available" and comparison.get("comparability") in {"strong", "moderate"})


def frame_dates(context: dict) -> list:
    """Period boundaries of the V3 populations: citing them is grounded, not an invented date."""
    frame = context.get("session_coaching_frame")
    dates: list = []
    if isinstance(frame, dict) and isinstance(frame.get("v3_assessment"), dict):
        v3 = frame["v3_assessment"]
        for block in (((v3.get("classification") or {}).get("relative_effort") or {}).get("provenance"),
                      (v3.get("historical_comparison") or {}).get("provenance")):
            for key in ("period_start", "period_end"):
                parsed = _parse_date((block or {}).get(key))
                if parsed is not None:
                    dates.append(parsed)
    for key in ("period_start", "period_end"):
        parsed = _parse_date((context.get("runner_profile") or {}).get("population", {}).get(key))
        if parsed is not None:
            dates.append(parsed)
    return dates


def split_session_facts(context: dict) -> tuple[list, list]:
    """(session facts, comparison facts) as flattened (key path, leaf) pairs.

    Only workout_detail and validated_workout_observations describe the selected
    session. recent_workouts, Training V2, readiness, load and performance are
    deliberately excluded: they are context, not facts about this workout.
    """
    detail = dict(context.get("workout_detail") or {})
    analysis = dict(detail.get("analysis") or {})
    comparison = analysis.pop("comparison", None)
    detail["analysis"] = analysis
    session: list = []
    _walk(detail, (), session)
    _walk(context.get("validated_workout_observations") or {}, ("observations",), session)
    _walk(context.get("observed_lap_pattern") or {}, ("observations", "lap_pattern"), session)
    frame_session, frame_references = _frame_facts(context)
    _walk(frame_session, ("observations", "frame"), session)
    compared: list = []
    _walk(comparison or {}, ("comparison",), compared)
    _walk(frame_references, ("comparison", "frame"), compared)
    return session, compared


def split_history_facts(context: dict) -> dict:
    """Facts about sessions BEFORE the selected one, kept per session (C402).

    {"sessions": [facts of session 1, ...], "dates": [date of session 1, ...], "aggregate":
    derived habit figures}. The date stays out of the facts on purpose (its clock time would
    look like a pace) and is kept apart, so a cited date can be tied to its own session.
    """
    sessions: list = []
    dates: list = []
    for item in (context.get("history_as_of_session") or {}).get("sessions") or []:
        facts: list = []
        _walk({k: v for k, v in item.items() if k != "date"}, ("history",), facts)
        sessions.append(facts)
        dates.append(_parse_date(item.get("date")))
    aggregate: list = []
    _walk((context.get("runner_profile") or {}).get("observed_training") or {}, ("history", "observed"), aggregate)
    return {"sessions": sessions, "dates": dates, "aggregate": aggregate}


_NUMBER_IN_TEXT = re.compile(r"(?<![\w:.,])\d+(?:[.,]\d+)?")
_TOKEN = re.compile(r"(?<![\d:])(\d{1,2}):(\d{2})(?::(\d{2}))?(?![\d:])")
# "2h02", "2 h 02", "2 h 2 min", "2 heures et 2 minutes", "2 hours 2 minutes", "2 horas 2 minutos", "2,03 h".
_HM = re.compile(
    r"(?<![\w:.,])(\d{1,2}(?:[.,]\d+)?)\s*(?:heures?|hours?|horas?|hrs?|h)(?![^\W\d_])"
    r"(?:\s*(?:et|and|y)\s+|\s*)"
    r"(?:(\d{1,2})(?!\d|\s*(?:km|bpm|%|:|secondes?|seconds?|segundos?|secs?|s(?![^\W\d_])))(?![.,]\d)(?:\s*(?:minutes?|minutos?|mins?|mn)(?![^\W\d_]))?)?", re.I)


def hm_minutes(match: "re.Match") -> float:
    """Minutes expressed by an _HM match."""
    return float(match.group(1).replace(",", ".")) * 60 + int(match.group(2) or 0)


def _is(path: tuple, *needles: str) -> bool:
    return any(n in part for part in path for n in needles)


def _has_none(path: tuple, *needles: str) -> bool:
    return not _is(path, *needles)


_GAP_KEYS = ("difference", "delta", "diff", "gap", "drop", "change", "dispersion")


def _build_pools(facts: list) -> dict:
    pools: dict[str, set] = {k: set() for k in
                             ("km", "bpm", "min", "sec", "m", "kmh", "pct", "delta", "count", "any")}
    token_seconds: set[float] = set()
    for path, value in facts:
        if isinstance(value, str):
            for h, m, s in re.findall(r"(?<![\d:])(\d{1,2}):(\d{2})(?::(\d{2}))?(?![\d:])", value):
                token_seconds.add(int(h) * 60 + int(m) if not s else int(h) * 3600 + int(m) * 60 + int(s))
            for tok in _NUMBER_IN_TEXT.findall(value):
                pools["any"].add(float(tok.replace(",", ".")))
            if _is(path, *_GAP_KEYS):
                # "-0:18/km" is a gap of 18 s/km: cite-able in seconds, never as 0 or 18 minutes
                for h, m, s in re.findall(r"(?<![\d:])(\d{1,2}):(\d{2})(?::(\d{2}))?(?![\d:])", value):
                    seconds = int(h) * 60 + int(m) if not s else int(h) * 3600 + int(m) * 60 + int(s)
                    pools["delta"].add(seconds)
                    pools["sec"].add(seconds)
            continue
        v = float(value)
        if v != v or abs(v) == float("inf"):
            continue
        pools["any"].add(v)
        if _is(path, "bpm") and _is(path, *_GAP_KEYS):
            # a signed HR gap is cited in bpm, even when its key names the pace it was matched at
            pools["bpm"].add(abs(v))
            continue
        pace_like = _is(path, "pace", "per_km", "min_km", "sec_km")
        if pace_like:
            seconds = v if _is(path, "second", "sec_") and not _is(path, "min_km") else v * 60
            token_seconds.add(round(seconds))
            # An "N s/km" figure is grounded in seconds: a value stored in minutes/km only
            # counts as such when it is a gap, and is converted (0.3 min/km is 18 s/km, not 0.3).
            if (_is(path, "second", "sec_") and not _is(path, "min_km")) or _is(path, *_GAP_KEYS):
                pools["delta"].add(abs(seconds))
                pools["sec"].add(abs(seconds))
            continue
        if _is(path, "count"):
            # A tally ("sessions_with_distance_count") is a number of sessions, never a distance.
            pools["count"].add(v)
            continue
        if _is(path, "speed", "kmh"):
            pools["kmh"].add(v)
        elif _is(path, "distance") or (_is(path, "_km") and _has_none(path, "split")):
            pools["km"].add(v)
            pools["m"].add(v * 1000)
        elif _is(path, "hr", "heart"):
            pools["bpm"].add(v)
        elif _is(path, "elevation", "gain") or any(part.endswith("_m") for part in path):
            pools["m"].add(v)
        elif _is(path, "duration", "elapsed", "moving", "minute", "second", "_sec", "_min", "time"):
            pools["min"].update({v, v / 60})
            pools["sec"].update({v, v * 60})
            token_seconds.update({round(v * 60), round(v)})
        elif _is(path, "pct", "percent", "ratio", "share"):
            pools["pct"].update({v, v * 100})
        elif _is(path, "count", "effort", "recover", "repet", "reference", "sample", "number", "total"):
            pools["count"].add(v)
        if _is(path, "difference", "delta", "diff", "gap"):
            pools["delta"].add(abs(v))
    pools["tokens"] = token_seconds  # type: ignore[assignment]
    return pools


_UNIT_POOL = [
    (re.compile(r"^(km/h|kmh|km/hr)", re.I), "kmh"),
    (re.compile(r"^(s/km|sec/km|secs/km)", re.I), "delta"),
    (re.compile(r"^(bpm|ppm|battements|beats|pulsaciones|lpm)", re.I), "bpm"),
    (re.compile(r"^km\b|^kilom", re.I), "km"),
    (re.compile(r"^(m|mètres|metres|meters|metros|mt)\b", re.I), "m"),
    (re.compile(r"^(min|mins|minutes|minutos)\b", re.I), "min"),
    (re.compile(r"^(s|sec|secs|secondes|seconds|segundos)\b", re.I), "sec"),
    (re.compile(r"^%"), "pct"),
    (re.compile(r"^(répétitions|repetitions|repeticiones|reps|efforts|esfuerzos|intervalles|intervals|"
                r"intervalos|séries|fois|times|veces|récupérations|recoveries|recuperaciones|"
                r"séances|sessions|sesiones)\b", re.I), "count"),
]


def _match(value: float, decimals: int, candidates: set) -> bool:
    tol = 0.5 * 10 ** -decimals + 1e-9
    return any(abs(value - c) <= tol for c in candidates)


_NUMBER_WORDS = re.compile(
    r"\b(un|une|deux|trois|quatre|cinq|six|sept|huit|neuf|dix|onze|douze|"
    r"one|two|three|four|five|seven|eight|nine|ten|eleven|twelve|"
    r"uno|dos|tres|cuatro|cinco|seis|siete|ocho|nueve|diez)\s+"
    r"(km|kilom[eè]tres?|kilometers?|kil[óo]metros?|répétitions?|repetitions?|repeticiones|fois|times|veces|"
    r"efforts?|esfuerzos|séries|reps|minutes?|minutos|bpm|intervalles|intervals|intervalos)\b", re.I)
_WORD_VALUE = {
    "un": 1, "une": 1, "one": 1, "uno": 1, "deux": 2, "two": 2, "dos": 2, "trois": 3, "three": 3, "tres": 3,
    "quatre": 4, "four": 4, "cuatro": 4, "cinq": 5, "five": 5, "cinco": 5, "six": 6, "seis": 6, "sept": 7,
    "seven": 7, "siete": 7, "huit": 8, "eight": 8, "ocho": 8, "neuf": 9, "nine": 9, "nueve": 9, "dix": 10,
    "ten": 10, "diez": 10, "onze": 11, "eleven": 11, "douze": 12, "twelve": 12,
}
# "une fois", "one time": an idiom about occurrence, not a measured quantity.
_ONCE = re.compile(r"^(?:fois|times|veces)\b", re.I)

_MONTHS = {
    1: ("janvier", "january", "enero"), 2: ("février", "february", "febrero"),
    3: ("mars", "march", "marzo"), 4: ("avril", "april", "abril"), 5: ("mai", "may", "mayo"),
    6: ("juin", "june", "junio"), 7: ("juillet", "july", "julio"), 8: ("août", "august", "agosto"),
    9: ("septembre", "september", "septiembre", "setiembre"), 10: ("octobre", "october", "octubre"),
    11: ("novembre", "november", "noviembre"), 12: ("décembre", "december", "diciembre"),
}
_MONTH_NAMES = {name: m for m, names in _MONTHS.items() for name in names}
_DATE_TEXT = re.compile(
    r"\b(\d{1,2})(?:er|st|nd|rd|th)?\s+(?:de\s+)?(" + "|".join(sorted(_MONTH_NAMES, key=len, reverse=True))
    + r")\b|\b(" + "|".join(sorted(_MONTH_NAMES, key=len, reverse=True)) + r")\s+(\d{1,2})\b", re.I)
_ISO_DATE = re.compile(r"\b\d{4}-\d{2}-\d{2}\b")

# ------------------------------------------------------------------ claim guards

_NEGATION = re.compile(
    r"\b(pas|ne|n'|aucun|aucune|sans|ni|not|no|cannot|can't|without|nor|sin|ningún|ninguna|"
    r"tampoco|nunca|jamais|never)\b|n'", re.I)
_BULLET = re.compile(r"^\s*(?:[-*•]|\d+[.)]|#{1,6})\s", re.M)
_COMPARISON = re.compile(
    r"(compar|\bvs\b|versus|par rapport|plus (?:rapide|lent|vite)\w* que|moins (?:rapide|vite)\w* que|"
    r"(?:faster|slower|higher|lower|better|worse) than|than (?:usual|your|before|similar|earlier)|"
    r"en comparaci|\bcontre\b|\bfrente a\b|"
    r"d'habitude|habituellement|usual(?:ly)?|habitual|normalmente|"
    r"que d'ordinaire|que la moyenne|than average|average of your|más (?:rápid|lent)\w* que|"
    r"menos (?:rápid|lent)\w* que)", re.I)
# The C388 notion of "similar sessions": a baseline only the C388 permission can open, never history alone.
_SIMILAR_BASELINE = re.compile(
    r"(s[ée]ances? (?:similaires?|comparables?)|similar (?:sessions?|workouts?|runs?)|"
    r"sesiones? (?:similares?|comparables?))", re.I)
# Names a prior session without comparing it: a description of history (C403). Comparing
# remains _COMPARISON, which needs the C388 permission.
_HISTORY_REF = re.compile(
    r"\b(earlier|previous|prior|last (?:run|session|workout)|before this|history|"
    r"pr[ée]c[ée]dent\w*|ant[ée]rieur\w*|avant (?:cette|celle)|derni[èe]re (?:sortie|s[ée]ance)|historique|"
    r"anterior\w*|antes de (?:esta|este)|[úu]ltima (?:salida|sesi[óo]n)|historial)\b", re.I)
_THRESHOLD_TERM = re.compile(r"\bLT[12]\b|\bseuil|threshold|umbral", re.I)
_UNSUPPORTED_PHYSIO = re.compile(
    r"(\bLT[12]\b|VO2\s?max|\bVMA\b|\bFC\s?max\b|\bHR\s?max\b|max(?:imum)?\s+heart\s+rate|"
    r"fr[ée]quence cardiaque maximale|frecuencia card[ií]aca m[aá]xima|\bseuil|threshold|umbral|"
    r"\bzones?\s*\d|\bzona\s*\d|\bZ[1-5]\b|anaerobic|ana[ée]robie|anaer[óo]bic|lactate|lactato)", re.I)
# "Récupération" alone is a phase of an interval session (a fact), not an intensity label;
# only a recovery run/session is. "le plus dur" is an idiom.
_INTENSITY = re.compile(
    r"(\b(?:easy|hard|facile|difficile|intense|intensit[ée]|intensity|intensidad|f[áa]cil|"
    r"tempo|endurance fondamentale|aerobic|a[ée]robie|a[ée]robic[oa]|"
    r"effort (?:mod[ée]r[ée]|soutenu|[ée]lev[ée])|moderate effort|hard effort|"
    r"zone de confort|comfort zone|zona de confort|comfortable (?:pace|effort|range|aerobic)|"
    r"(?:rythme|allure) (?:confortable|mod[ée]r[ée]e?)|ritmo c[óo]modo|effortless|conversational)\b|"
    r"\b(?<!plus )dur(?:e|es)?\b|"
    r"\b(?:recovery (?:run|session|jog|day)|(?:sortie|s[ée]ance|footing|jogging) de r[ée]cup[ée]ration|"
    r"(?:salida|sesi[óo]n|carrera) de recuperaci[óo]n)\b)", re.I)
_EFFICIENCY = re.compile(
    r"(efficien|efficac|[ée]conomie de course|running economy|econom[ií]a de carrera|rendement)", re.I)
_CAUSAL = re.compile(
    r"\b(because|due to|thanks to|as a result of|parce que|[àa] cause|en raison|gr[âa]ce [àa]|"
    r"porque|debido a|gracias a)\b", re.I)
_PROGRESS = re.compile(
    r"(progr[eè]s|improv|am[ée]lior|regress|decline|d[ée]clin|mejor[aóe]\w*|empeor|retroces|fitness|"
    r"gagn[ée] en|gained|ganado en|stronger|fitter|better shape|right track|paying off|momentum|"
    r"plus fort|plus en forme|meilleure forme|bon chemin|bonne voie|dynamique positive|"
    r"m[áa]s fuerte|mejor forma|buen camino|dando frutos|da frutos)", re.I)
# Claims about what the session did to the athlete's capacities, or whether it "worked".
_ENDURANCE = re.compile(
    r"(?:\b(?:build|built|builds|boost|boosted|develop|developed|strengthen\w*|improv\w*|"
    r"construi\w*|renforc\w*|d[ée]velopp\w*|am[ée]lior\w*|desarroll\w*|fortalec\w*|mejor\w*)\s+"
    r"(?:\w+\s+){0,2}(?:endurance|stamina|resistencia|souffle|cardio|aerobic base|base a[ée]robie)\b|"
    r"\b(?:endurance|stamina|resistencia)\s+(?:(?:is|are|has|est|a|es|ha)\s+)?(?:\w+\s+){0,2}"
    r"(?:higher|better|improved|stronger|meilleure|sup[ée]rieure|mejor|mayor)\b|"
    r"\b(?:higher|better|improved|stronger|meilleure|sup[ée]rieure|mejor|mayor)\s+(?:endurance|stamina|resistencia)\b)", re.I)
_EFFECTIVENESS = re.compile(
    r"(?:\b(?:effective|useful|valuable|productive|beneficial|efficace|utile|b[ée]n[ée]fique|"
    r"[úu]til|eficaz|productiv[ao]|beneficios[ao])\b[^.!?]{0,40}\b(?:session|workout|training|run|s[ée]ance|"
    r"sortie|entra[iî]nement|sesi[óo]n|salida|pr[ée]paration|preparation|preparaci[óo]n)\b|"
    r"\b(?:session|workout|s[ée]ance|sortie|sesi[óo]n|salida)\b[^.!?]{0,30}\b(?:effective|useful|valuable|"
    r"productive|efficace|utile|[úu]til|eficaz)\b|"
    r"\b(?:perfect for|ideal for|parfait pour|id[ée]al pour|ideal para|perfecto para)\b|"
    r"\b(?:training|plan|entra[iî]nement|entrenamiento)\b[^.!?]{0,20}\b(?:works?|worked|working|"
    r"fonctionne|marche|funciona)\b)", re.I)
_SUCCESS = re.compile(
    r"(\b(?:success(?:ful)?|nailed|crushed|aced|r[ée]ussi[es]?|[ée]chec|failed|logr[ao]d[ao]|[ée]xito|"
    r"mission accomplie|objectif atteint|goal (?:achieved|reached|met)|target (?:hit|met|reached)|"
    r"parfaitement tenu|tenu tous|held (?:every|all)|hit every|cumpli\w+ (?:todos|cada))\b)", re.I)
# Describing the session as a cause/effect of the goal (it may only be relevant to it).
_GOAL_DESIGN = re.compile(
    r"(design|built|planned|prepared specifically|specifically|on purpose|con[çc]ue?s?|pr[ée]vue?s?|"
    r"sp[ée]cifiquement|exprès|dise[ñn]ad[ao]|espec[ií]ficamente|a prop[óo]sito)", re.I)
# The goal history is unknown: no sentence may place the goal at the session date or before.
_GOAL_PAST = re.compile(
    r"(at the time|back then|previous goal|earlier goal|old goal|used to be|was already|"
    r"[àa] l'[ée]poque|[àa] ce moment-l[àa]|ancien objectif|objectif pr[ée]c[ée]dent|alors|"
    r"en aquel momento|en esa [ée]poca|objetivo anterior|antiguo objetivo|entonces|"
    r"(?:were|was) (?:already )?(?:prepar|train|target|aim|work|build|focus)\w*ing|"
    r"pr[ée]parais|entra[iî]nais|preparabas|entrenabas)", re.I)
# Weaker past cues describe the performed session as readily as an intention: they count only in
# the clause that also names the goal ("you were running at 5:32, relevant to your current
# marathon goal" describes the run, it does not date the goal).
_GOAL_PAST_CLAUSE = re.compile(
    r"((?:were|was) (?:already )?\w+ing|that day|already|d[ée]j[àa]|ce jour-l[àa]|ese d[íi]a)", re.I)
# Compound names are folded to one token first, so "ultra-marathon", "demi-marathon" or
# "media maratón" are never read as an ordinary marathon.
_GOAL_COMPOUND = [
    (re.compile(r"\bultra[- ]?marat(?:hon|[óo]n)\w*", re.I), " ULTRAGOAL "),
    (re.compile(r"\b(?:semi|demi|half|medio|media)[- ]?marat(?:hon|[óo]n)\w*", re.I), " SEMIGOAL "),
]
_GOAL_TERMS = {
    "marathon": re.compile(r"\bmarat(?:hon|[óo]n)", re.I),
    "semi": re.compile(r"SEMIGOAL|\bsemi\b", re.I),
    "ultra": re.compile(r"ULTRAGOAL|\bultra", re.I),
    "5k": re.compile(r"\b5\s?k\b", re.I),
    "10k": re.compile(r"\b10\s?k\b", re.I),
}
_GOAL_KIND = {"MARATHON": "marathon", "SEMI": "semi", "HALF_MARATHON": "semi", "ULTRA": "ultra",
              "5K": "5k", "10K": "10k"}
_SENSATION = re.compile(
    r"(you felt|you were (?:tired|exhausted|strong)|tu as ressenti|tu te sentais|tu as d[ûu]|ressenti|"
    r"te sentiste|te sent[ií]as|has sentido|fatigu|tired|exhaust|[ée]puis|cansad|agotad|your body|tu corps|"
    r"tu cuerpo|sensations?)", re.I)
_PRESCRIPTION = re.compile(
    r"(prochaine?s? (?:s[ée]ance|sortie|course)|next (?:session|workout|run)|tomorrow|demain|"
    r"pr[óo]xim[ao] (?:sesi[óo]n|entrenamiento|salida)|"
    r"(?<!\besta )(?<!\besa )(?<!\bla )(?<!\buna )(?<!\bcada )(?<!\btoda la )ma[ñn]ana\b|"
    r"je te conseille|i recommend|te recomiendo|you should (?:run|do|try|take)|tu devrais|deber[ií]as|"
    r"tu peux (?:enchaîner|prévoir)|try to|essaie de|intenta)", re.I)
_CONTEXT_LEAK = re.compile(
    r"(readiness|race day|jour de course|d[ée]but de cycle|training plan|plan d'entra|"
    r"pr[ée]paration (?:course|à)|semaine \d+ sur \d+|week \d+ of \d+)", re.I)
_GOAL_WORD = re.compile(r"(objectif|\bgoal\b|objetivo|marathon|maratón|\bsemi\b|half[- ]marathon|\bultra)", re.I)
_MINIMIZER = re.compile(
    r"(slightly|barely|only (?:a )?(?:little|bit)|hardly|marginal|a bit|just a little|"
    r"l[ée]g[èe]rement|[àa] peine|un peu|quasi|presque (?:identique|pareil)|"
    r"ligeramente|apenas|casi (?:igual|id[ée]ntic)|un poco)", re.I)
# Abstention: the sentence says the position/intensity cannot be determined. Only these
# sentences may mention thresholds, zones or intensity without structured authorization.
_ABSTAIN = re.compile(
    r"(impossible|pas possible|ne peut|ne peuvent|ne permet|ne permettent|indisponible|"
    r"(?:pas|non) disponible|cannot|can't|can not|unable|not available|unavailable|not possible|"
    r"do(?:es)? not (?:allow|let|make it possible)|no es posible|no se puede|no puedo|no podemos|"
    r"imposible|no disponible|no permite|no permiten|"
    r"ne peux pas|ne sais pas|je ne sais|rien n'indique|ne montre pas|n'indique pas|nothing (?:shows|indicates)|"
    r"don't know|do not know|no s[ée]|no indica|no muestra)", re.I)
_ABSTAIN_SUBJECT = re.compile(
    r"(d[ée]termin|savoir|\bdire\b|affirmer|conclure|[ée]valuer|situer|position|determine|"
    r"tell|say|assess|conclude|know|locate|evaluate|determinar|saber|decir|afirmar|concluir|evaluar|situar)",
    re.I)
# A claim is a non-claim only when a specific "does not show / cannot conclude" cue sits just
# before it in the same clause. A negation elsewhere in the sentence authorizes nothing, and a
# bare "cannot" does not: "cannot deny that you improved" affirms the claim. The negated verb
# must be one of evidence or inference.
_NON_CLAIM_CUE = re.compile(
    r"(?:(?:does not|doesn't|do not|don't|cannot|can't|can not|could not|couldn't|unable to|not able to)\s+"
    r"(?:(?!fail\b|hesitate\b|forget\b)\w+\s+){0,2}?"
    r"(?:show|demonstrate|prove|establish|indicate|confirm|support|conclude|determine|tell|say|assess|know)\b|"
    r"(?:is|are) not (?:a |any )?(?:proof|evidence|sign|indication) of|no (?:proof|evidence|sign) of|"
    r"not (?:a |any )?(?:proof|evidence|sign|indication) of|"
    r"ne (?:montre|prouve|d[ée]montre|permet|indique)(?:nt)? pas|"
    r"n'(?:a|ont) pas (?:montr[ée]|d[ée]montr[ée]|prouv[ée])|n'(?:indique|indiquent) pas|"
    r"ne (?:peut|peuvent|pouvons|peux) pas (?:conclure|affirmer|dire|d[ée]montrer|d[ée]terminer|prouver|savoir|[ée]tablir)|"
    r"pas (?:une )?(?:preuve|trace) de|"
    r"no (?:muestra|demuestra|indica|permite|prueba)(?:n)?|no es (?:una )?prueba de|"
    r"no (?:se puede|podemos|puedo) (?:concluir|afirmar|decir|demostrar|determinar|probar|saber))"
    r"(?:\W+\w+){0,6}\W*$", re.I)
_INTERNAL = re.compile(
    r"(Training V2|Workout Analysis|Coach Context|selected_workout_permissions|canonical|C388|C396)", re.I)

_STOPWORDS = {
    "fr": {"le", "la", "les", "des", "et", "une", "est", "sur", "pour", "avec", "tu", "ta", "ton", "tes", "du",
           "un", "dans", "qui", "pas", "plus", "très", "ce", "cette", "au", "aux", "vous", "sont", "été",
           "par", "ça", "mais", "ou", "où", "il", "elle", "sortie", "séance"},
    "en": {"the", "and", "of", "was", "with", "for", "that", "this", "your", "you", "is", "on", "at",
           "it", "to", "but", "very", "more", "from", "as", "by", "were", "which", "run", "session"},
    "es": {"el", "los", "las", "del", "una", "un", "es", "con", "para", "por", "muy", "más", "tu", "tus",
           "se", "lo", "su", "al", "fue", "sido", "pero", "sobre", "salida", "sesión", "ritmo", "y", "o"},
}


def _words(text: str) -> list[str]:
    return re.findall(r"[a-zà-ÿ']+", text.lower())


def _language_ok(text: str, language: str) -> bool:
    words = _words(text)
    scores = {code: sum(1 for w in words if w in sw) for code, sw in _STOPWORDS.items()}
    target = language if language in scores else "fr"
    return scores[target] >= 2 and all(scores[target] > v for c, v in scores.items() if c != target)


def _only_negated(sentence: str, claim: "re.Pattern") -> bool:
    """True when the sentence has the claim and every occurrence is explicitly disclaimed."""
    matches = list(claim.finditer(sentence))
    if not matches:
        return False
    for m in matches:
        start = max((b.end() for b in _CLAUSE_BREAK.finditer(sentence, 0, m.start())), default=0)
        if not _NON_CLAIM_CUE.search(sentence[start:m.start()]):
            return False
    return True


def _sentences(text: str) -> list[str]:
    return [s for s in re.split(r"(?<=[.!?])\s+", text) if s.strip()]


def _parse_date(value: Any):
    from datetime import datetime
    if not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).date()
    except ValueError:
        return None


def _mentioned_dates(sentence: str) -> list:
    """Exact dates written in a sentence: ("md", (day, month)) or ("iso", "YYYY-MM-DD")."""
    found: list = []
    for match in _DATE_TEXT.finditer(sentence):
        found.append(("md", (int(match.group(1) or match.group(4)),
                             _MONTH_NAMES[(match.group(2) or match.group(3)).lower()])))
    found.extend(("iso", d) for d in _ISO_DATE.findall(sentence))
    return found


def _date_is(mention: tuple, day: Any) -> bool:
    if day is None:
        return False
    return mention[1] == ((day.day, day.month) if mention[0] == "md" else day.isoformat())


def _segments(sentence: str) -> list[str]:
    """Pieces of a sentence split at comparison wording and clause breaks (a comma right after a
    date does not cut: "On 8 January, you ran ..." keeps the date with what follows)."""
    date_ends = {m.end() for m in _DATE_TEXT.finditer(sentence)} | {m.end() for m in _ISO_DATE.finditer(sentence)}
    cuts = {0, len(sentence)}
    for rx in (_COMPARISON, _SIMILAR_BASELINE):
        cuts.update(m.start() for m in rx.finditer(sentence))
    cuts.update(m.end() for m in _CLAUSE_BREAK.finditer(sentence)
                if not any(e <= m.start() and not sentence[e:m.start()].strip() for e in date_ends))
    points = sorted(cuts)
    return [sentence[i:j] for i, j in zip(points, points[1:]) if sentence[i:j].strip()]


def _figure_checks(masked: str):
    """Every numeric figure of a sentence as (kind, check(pools) -> bool, reason if ungrounded)."""
    for match in _TOKEN.finditer(masked):
        h, m, s = match.groups()
        seconds = int(h) * 3600 + int(m) * 60 + int(s) if s else int(h) * 60 + int(m)
        yield "figure", (lambda pools, seconds=seconds: any(abs(seconds - t) <= 1 for t in pools["tokens"])), \
            "ungrounded_pace_or_time"
    masked = _TOKEN.sub(" ", masked)

    for match in _HM.finditer(masked):
        minutes = hm_minutes(match)
        yield "hm", (lambda pools, minutes=minutes: any(abs(minutes - c) <= 1 for c in pools["min"])), \
            "ungrounded_duration"
    masked = _HM.sub(" ", masked)

    for match in _NUMBER_WORDS.finditer(masked):
        unit = match.group(2)
        value = float(_WORD_VALUE[match.group(1).lower()])
        if value == 1 and _ONCE.match(unit):
            continue
        pool = next((name for rx, name in _UNIT_POOL if rx.match(unit)), "any")
        yield "figure", (lambda pools, pool=pool, value=value: _match(value, 0, pools[pool])), "ungrounded_number"
    masked = _NUMBER_WORDS.sub(" ", masked)

    for match in _NUMBER_IN_TEXT.finditer(masked):
        raw = match.group(0)
        value = float(raw.replace(",", "."))
        decimals = len(re.split(r"[.,]", raw)[1]) if re.search(r"[.,]", raw) else 0
        rest = masked[match.end():match.end() + 18].lstrip()
        pool = next((name for rx, name in _UNIT_POOL if rx.match(rest)), None) or "any"
        yield "figure", (lambda pools, pool=pool, value=value, decimals=decimals:
                         _match(value, decimals, pools[pool])), "ungrounded_number"


def _check_numbers(sentence: str, session: dict, compared: dict, history: dict, comparison_ok: bool,
                   reasons: set, selected_date: Any = None) -> None:
    """Order of provenance: the selected session, then C388's validated comparison, then one
    prior session. Values grounded only in prior sessions must all belong to the SAME prior
    session (or to the observed-habit aggregate): "8 km at 5:30" is rejected when 8 km and
    5:30 come from two different sessions. A sentence citing two prior sessions is rejected
    too: the text does not say which value goes with which session, and we do not guess.
    """
    has_comparison_wording = bool(_COMPARISON.search(sentence) or _SIMILAR_BASELINE.search(sentence))
    masked = _ISO_DATE.sub(" ", _DATE_TEXT.sub(" ", sentence))
    history_hits: list = []  # one matcher per value grounded only in prior sessions
    # A date that is a prior session's (not the selected one) anchors the sentence to it.
    dated = [m for m in _mentioned_dates(sentence)
             if not _date_is(m, selected_date)
             and any(_date_is(m, o.get("date")) for o in history["owners"])]
    anchored = [o for o in history["owners"] if any(_date_is(m, o.get("date")) for m in dated)]
    history_framed = has_comparison_wording or bool(dated) or bool(_HISTORY_REF.search(sentence))
    # A date proves which session is meant, never a measurement: kept apart from the figures.
    date_hits = [(lambda pools, mention=mention: _date_is(mention, pools.get("date"))) for mention in dated]
    if has_comparison_wording and dated:
        # Comparing wording must not unlock figures next to a prior date: inside the segment that
        # carries the date, every figure belongs to the dated session (the other side of the
        # comparison is a different segment and may cite the selected session).
        for segment in _segments(sentence):
            in_segment = _mentioned_dates(segment)
            owners = [o for o in history["owners"]
                      if any(m in in_segment and _date_is(m, o.get("date")) for m in dated)]
            if not owners:
                continue
            plain = _ISO_DATE.sub(" ", _DATE_TEXT.sub(" ", segment))
            if any(not all(check(o) for o in owners) for _, check, _r in _figure_checks(plain)):
                reasons.add("history_misattribution")
    dual_hits: list = []  # grounded in C388's baseline AND in some prior session
    baseline_hits = 0  # grounded only in C388's aggregate comparison baseline

    def settle(session_ok: bool, compared_ok: bool, owner_ok, reason: str = "ungrounded_number") -> None:
        if anchored and not has_comparison_wording:
            # "On 8 January you ran X": every figure must belong to that very session; the
            # selected session's own figures must not be attributed to a prior date.
            if any(owner_ok(o) for o in anchored):
                history_hits.append(owner_ok)
            elif session_ok or compared_ok or any(owner_ok(o) for o in history["owners"]):
                reasons.add("history_misattribution")
            else:
                reasons.add(reason)
            return
        if session_ok:
            return
        if comparison_ok and compared_ok:
            if not has_comparison_wording:
                reasons.add("comparison_value_as_session")
            if any(owner_ok(o) for o in history["owners"]):
                dual_hits.append(owner_ok)
            else:
                nonlocal baseline_hits
                baseline_hits += 1
            return
        if any(owner_ok(o) for o in history["owners"]):
            if not history_framed:
                reasons.add("comparison_value_as_session")
            history_hits.append(owner_ok)
            return
        reasons.add(reason)

    for kind, check, reason in _figure_checks(masked):
        if kind == "hm":
            if not check(session):
                reasons.add(reason)
        else:
            settle(check(session), check(compared), check, reason)

    # Baseline-only and dual values are the C388 baseline unless the sentence also cites a value
    # that only a prior session has: then they must all belong to that one session.
    if (history_hits or date_hits) and (baseline_hits or not any(
            all(hit(owner) for hit in history_hits + date_hits + dual_hits) for owner in history["owners"])):
        reasons.add("history_misattribution")
    return bool(history_hits or dual_hits)


# Materiality threshold per metric: pace in seconds/km, the other metrics in percent.
GAP_PACE_SEC_PER_KM = 10
GAP_PERCENT = 10
_METRIC_KEYS = (("pace", ("pace", "speed")), ("distance", ("distance",)), ("duration", ("duration",)),
                ("heart_rate", ("heart", "hr")))
# Explicit metric names (and unambiguous adjectives) identify a metric; "longer"/"shorter" and
# their translations are ambiguous (distance or duration) and only count when no clause names one.
_METRIC_WORDS = {
    "pace": re.compile(r"(pace|allure|ritmo|speed|vitesse|velocidad|faster|slower|plus (?:rapide|lent|vite)|"
                       r"m[áa]s (?:r[áa]pid|lent)|rapide|\bvite\b|r[áa]pid)", re.I),
    "distance": re.compile(r"(distance|distancia|kilom[eè]tres?|kil[óo]metros?)", re.I),
    "duration": re.compile(r"(duration|dur[ée]e|duraci[óo]n|elapsed|moving time)", re.I),
    "heart_rate": re.compile(r"(heart|cardiaque|card[ií]aca|\bFC\b|\bHR\b|bpm|pulsaciones)", re.I),
}
_AMBIGUOUS_LENGTH = re.compile(r"(longer|shorter|farther|longue?s?\b|plus (?:long|court)|"
                               r"m[áa]s (?:larg|cort)|larg[ao]|cort[ao])", re.I)
def _material_gaps(comparison_facts: list) -> set:
    """Metrics on which the compared sessions differ materially (C403).

    Pace gaps are measured in s/km (>=10): from a "-0:18/km" display string (what the shared
    context really carries), from *_sec_per_km values, or from *_min_km values converted to
    seconds. Distance, duration and heart rate use percent_change (>=10 %). Signed values are
    compared by magnitude. A value whose unit cannot be established is ignored, not guessed.
    """
    gaps: set = set()
    for path, value in comparison_facts:
        metric = next((name for name, keys in _METRIC_KEYS if _is(path, *keys)), None)
        if metric is None:
            continue
        if isinstance(value, str):
            if metric == "pace" and _is(path, *_GAP_KEYS):
                for h, m, sec in re.findall(r"(?<![\d:])(\d{1,2}):(\d{2})(?::(\d{2}))?(?![\d:])", value):
                    seconds = int(h) * 60 + int(m) if not sec else int(h) * 3600 + int(m) * 60 + int(sec)
                    if seconds >= GAP_PACE_SEC_PER_KM:
                        gaps.add("pace")
            continue
        if isinstance(value, bool) or not isinstance(value, (int, float)) or value != value:
            continue
        if _is(path, "percent_change"):
            if abs(value) >= GAP_PERCENT:
                gaps.add(metric)
        elif metric == "pace" and _is(path, *_GAP_KEYS):
            if _is(path, "sec_"):
                seconds = abs(value)
            elif _is(path, "min_km", "min_per_km"):
                seconds = abs(value) * 60
            else:
                continue
            if seconds >= GAP_PACE_SEC_PER_KM:
                gaps.add("pace")
    return gaps


def _significant_gaps(comparison_facts: list) -> bool:
    return bool(_material_gaps(comparison_facts))


_CLAUSE_BREAK = re.compile(r"[;]|,?\s+\b(?:and|but|while|whereas|et|mais|tandis que|y|pero|mientras)\b|,", re.I)


def _metrics_named(text: str) -> set:
    named = {m for m, rx in _METRIC_WORDS.items() if rx.search(text)}
    if not named and _AMBIGUOUS_LENGTH.search(text):
        return {"distance", "duration"}
    return named


def _minimized_material_gap(sentence: str, gaps: set) -> bool:
    """A minimizer ("slightly") counts only against the metric its own clause describes; an
    explicit metric name wins over an ambiguous adjective, and an unidentified metric stays
    conservative."""
    if not gaps or not (_COMPARISON.search(sentence) or _SIMILAR_BASELINE.search(sentence)):
        return False
    sentence_metrics = _metrics_named(sentence)
    for clause in _CLAUSE_BREAK.split(sentence):
        if not clause or not _MINIMIZER.search(clause):
            continue
        metrics = _metrics_named(clause) or sentence_metrics
        if not metrics or metrics & gaps:
            return True
    return False


def validate_session_comment(text: Any, context: dict, language: str) -> tuple[bool, list[str]]:
    """Conservative heuristic guard; rejects whatever it cannot tie to session facts.

    Passing means "no checked claim contradicted the selected session's facts",
    never "the text is true".
    """
    if not isinstance(text, str) or not text.strip():
        return False, ["empty"]
    text = text.strip()
    reasons: set[str] = set()
    if not MIN_CHARS <= len(text) <= MAX_CHARS:
        reasons.add("length")
    if _BULLET.search(text):
        reasons.add("format")
    if not _language_ok(text, language):
        reasons.add("language")
    if _INTERNAL.search(text):
        reasons.add("internal_terms")

    permissions = context.get("selected_workout_permissions") or {}
    session_facts, comparison_facts = split_session_facts(context)
    comparison_ok = bool(permissions.get("similar_comparison_available")) or v3_comparison_available(context)
    history_facts = split_history_facts(context)
    owners = [{**_build_pools(f), "date": d} for f, d in zip(history_facts["sessions"], history_facts["dates"])]
    if history_facts["aggregate"]:
        owners.append({**_build_pools(history_facts["aggregate"]), "date": None})
    history = {"owners": owners}
    # Describing a prior session needs no permission; comparing with it needs C388's.
    session = _build_pools(session_facts)
    compared = _build_pools(comparison_facts if comparison_ok else [])
    goal = context.get("declared_goal") or {}
    goal_kind = _GOAL_KIND.get(str(goal.get("goal_type") or "").upper())
    gaps = _material_gaps(comparison_facts) if comparison_ok else set()
    def abstains(sentence: str) -> bool:
        return bool(_ABSTAIN.search(sentence) and _ABSTAIN_SUBJECT.search(sentence))

    # Fact/limitation text never authorizes a claim: the substring "LT1" in a C388
    # limitation does not prove the session was below LT1. Only abstention wording or an
    # explicit structured permission lets such terms through.
    frame = context.get("session_coaching_frame")
    v3_intensity = ((frame.get("v3_assessment") or {}).get("intensity") or {}) if isinstance(frame, dict) \
        and isinstance(frame.get("v3_assessment"), dict) else {}
    v3_thresholds = bool(v3_intensity.get("thresholds_available")) and v3_intensity.get(
        "position_vs_declared_thresholds") in {"below_LT1", "between_LT1_LT2", "above_LT2"}
    intensity_ok = permissions.get("intensity_interpretation_allowed") is True or v3_thresholds
    progress_ok = permissions.get("progress_regression_allowed") is True and comparison_ok
    for sentence in _sentences(text):
        abstention = abstains(sentence)
        if not abstention:
            physio = [m.group(0) for m in _UNSUPPORTED_PHYSIO.finditer(sentence)]
            # Personal thresholds are citable only when V3 holds them (their position is
            # then checked by the evidence guard); every other physiological term stays refused.
            if physio and not (v3_thresholds and all(_THRESHOLD_TERM.search(t) for t in physio)):
                reasons.add("unsupported_physiology")
            if not intensity_ok and _INTENSITY.search(sentence):
                reasons.add("intensity_not_allowed")
        if _SENSATION.search(sentence):
            reasons.add("invented_sensation")
        if _PRESCRIPTION.search(sentence):
            reasons.add("prescription")
        if _CONTEXT_LEAK.search(sentence):
            reasons.add("context_as_session_fact")
        if _GOAL_WORD.search(sentence):
            if not goal:
                reasons.add("context_as_session_fact")
            else:
                folded = sentence
                for rx, token in _GOAL_COMPOUND:
                    folded = rx.sub(token, folded)
                named = [k for k, rx in _GOAL_TERMS.items() if rx.search(folded)]
                if any(k != goal_kind for k in named) or (not goal.get("is_race_goal") and named):
                    reasons.add("goal_mismatch")
                if _GOAL_DESIGN.search(sentence):
                    reasons.add("goal_design_claim")
                if _GOAL_PAST.search(sentence) or any(
                        _GOAL_PAST_CLAUSE.search(c) and _GOAL_WORD.search(c)
                        for c in _CLAUSE_BREAK.split(sentence) if c):
                    reasons.add("goal_history_claim")
        if _ENDURANCE.search(sentence) and not _only_negated(sentence, _ENDURANCE):
            reasons.add("endurance_claim")
        if _SUCCESS.search(sentence):
            reasons.add("success_claim")
        if _minimized_material_gap(sentence, gaps):
            reasons.add("minimized_gap")
        if _PROGRESS.search(sentence) and not progress_ok and not _only_negated(sentence, _PROGRESS):
            reasons.add("progress_claim")
    if permissions.get("physiological_efficiency_allowed") is not True and _EFFICIENCY.search(text):
        reasons.add("efficiency_not_allowed")
    if permissions.get("physiological_efficiency_allowed") is not True and _EFFECTIVENESS.search(text):
        reasons.add("effectiveness_not_allowed")
    if permissions.get("causal_explanation_allowed") is not True and _CAUSAL.search(text):
        reasons.add("causal_not_allowed")

    selected_date = _parse_date(
        (context.get("workout_detail") or {}).get("start_time")
        or (context.get("workout_detail") or {}).get("date"))
    history_dates = history_facts["dates"] + frame_dates(context)
    for mention in _mentioned_dates(text):
        if not (_date_is(mention, selected_date) or any(_date_is(mention, d) for d in history_dates)):
            reasons.add("ungrounded_date")

    for sentence in _sentences(text):
        compares = bool(_COMPARISON.search(sentence))
        similar = bool(_SIMILAR_BASELINE.search(sentence))
        cites_history = _check_numbers(sentence, session, compared, history, comparison_ok, reasons, selected_date)
        # Without the C388 permission only a comparison anchored on a cited prior-session
        # measurement is tolerated (a date is not one); a "similar sessions" baseline is never
        # opened by history alone.
        if not comparison_ok and (similar or compares and not cites_history) and not abstains(sentence):
            reasons.add("comparison_not_available")
    return not reasons, sorted(reasons)


# ------------------------------------------------------------- cache / dedupe

_CACHE: "OrderedDict[str, tuple[float, str, dict]]" = OrderedDict()
_INFLIGHT: dict[str, "asyncio.Future[dict]"] = {}


def reset_state() -> None:
    _CACHE.clear()
    _INFLIGHT.clear()


def cache_key(*, user_id: str, workout_id: str, language: str, context: Any) -> str:
    """Exact fingerprint of what is sent to C396: any context change is a new key.

    Also scoped to user, workout, language, Coach comment version and model.
    """
    payload = json.dumps(
        {"u": user_id, "w": workout_id, "l": language, "v": COACH_COMMENT_VERSION,
         "m": llm_coach.LLM_MODEL, "c": context},
        sort_keys=True, ensure_ascii=False, default=str, separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _cache_get(key: str, user_id: str) -> Optional[dict]:
    entry = _CACHE.get(key)
    if entry is None:
        return None
    expires, owner, value = entry
    if expires < time.monotonic() or owner != user_id:
        _CACHE.pop(key, None)
        return None
    _CACHE.move_to_end(key)
    return dict(value)


def _cache_put(key: str, user_id: str, value: dict, ttl: float) -> None:
    _CACHE[key] = (time.monotonic() + ttl, user_id, dict(value))
    _CACHE.move_to_end(key)
    while len(_CACHE) > CACHE_MAX:
        _CACHE.popitem(last=False)


def _result(status: str, text: Optional[str] = None, reasons: Optional[list[str]] = None) -> dict:
    return {
        "status": status, "text": text, "source": COMMENT_SOURCE,
        "coach_version": COACH_COMMENT_VERSION, "model": llm_coach.LLM_MODEL,
        "validation": {"level": VALIDATION_LEVEL, "passed": status == "generated",
                       "rejected_checks": reasons or []},
    }


async def _generate(context: dict, language: str, user_id: str) -> dict:
    try:
        text, success, _meta = await asyncio.wait_for(
            llm_coach.generate_session_comment(context, user_id=user_id),
            timeout=COMMENT_TIMEOUT_SEC,
        )
    except asyncio.CancelledError:
        raise
    except Exception:
        logger.warning("[C400] session comment generation failed")
        return _result("fallback", reasons=["error"])
    if not success or not text:
        return _result("fallback", reasons=["llm_unavailable"])
    ok, reasons = validate_session_comment(text, context, language)
    return _result("generated", text.strip()) if ok else _result("fallback", reasons=reasons)


async def get_session_comment(
    *, key: str, user_id: str, language: str, context: dict,
) -> tuple[dict, bool]:
    """Return (result, cached). Concurrent identical requests share one LLM call."""
    cached = _cache_get(key, user_id)
    if cached is not None:
        return cached, True
    task = _INFLIGHT.get(key)
    if task is None:
        async def run() -> dict:
            result = await _generate(context, language, user_id)
            _cache_put(key, user_id, result,
                       SUCCESS_TTL_SEC if result["status"] == "generated" else FAILURE_TTL_SEC)
            return result

        task = asyncio.ensure_future(run())
        _INFLIGHT[key] = task
        task.add_done_callback(lambda _t, k=key: _INFLIGHT.pop(k, None))
    return dict(await asyncio.shield(task)), False


def _flight_key(user_id: str, workout_id: str, language: str) -> str:
    return "flight:" + hashlib.sha256(
        json.dumps([COACH_COMMENT_VERSION, user_id, workout_id, language]).encode()
    ).hexdigest()


async def get_session_comment_bounded(
    *, user_id: str, workout_id: str, language: str, load_context,
) -> tuple[dict, bool]:
    """Whole pipeline under one deadline: load_context -> cache key -> LLM -> validation.

    load_context is an async callable returning the LLM context, or None when no
    comment can be produced (unavailable); it may raise (e.g. LookupError for an
    unowned workout), which propagates and is never cached. Concurrent requests of the
    same user/workout/language share one task; on deadline the task is cancelled and
    dropped from _INFLIGHT, and a short-lived failure entry allows a retry after
    FAILURE_TTL_SEC.
    """
    flight = _flight_key(user_id, workout_id, language)
    failed = _cache_get(flight, user_id)
    if failed is not None:
        return failed, True
    task = _INFLIGHT.get(flight)
    if task is None:
        async def pipeline() -> tuple[dict, bool]:
            context = await load_context()
            if context is None:
                return _result("unavailable"), False
            key = cache_key(user_id=user_id, workout_id=workout_id, language=language, context=context)
            hit = _cache_get(key, user_id)
            if hit is not None:
                return hit, True
            result = await _generate(context, language, user_id)
            _cache_put(key, user_id, result,
                       SUCCESS_TTL_SEC if result["status"] == "generated" else FAILURE_TTL_SEC)
            return result, False

        async def run() -> tuple[dict, bool]:
            try:
                return await asyncio.wait_for(pipeline(), timeout=COMMENT_TIMEOUT_SEC)
            except asyncio.TimeoutError:
                logger.warning("[C400] session comment deadline exceeded")
                result = _result("fallback", reasons=["timeout"])
                _cache_put(flight, user_id, result, FAILURE_TTL_SEC)
                return result, False

        task = asyncio.ensure_future(run())
        _INFLIGHT[flight] = task
        task.add_done_callback(lambda _t, k=flight: _INFLIGHT.pop(k, None))
    result, cached = await asyncio.shield(task)
    return dict(result), cached
