"""C232 (correction) — honest session pace-zone resolution (no fabrication).

BLOCKER FIXED: the previous version of this module invented a detailed
interval/segment structure (warmup / N × reps @ threshold pace / recovery /
cooldown for "quality"; a 65/20/15 marathon-pace progression for
"long_easy") purely inside this display layer, from nothing but
`workout_type`. `WorkoutPrescription` (training_v2/workout_generator.py)
explicitly documents that it does NOT decide "quality"'s exact nature and
does NOT include specific paces/intervals — so that structure was never
actually prescribed by the Training Engine. Displaying it was a hidden,
UNPRESCRIBED physiological decision made in the UX layer, not a
"display-only" reformatting of real data.

CORRECTION: this module now does the SMALLEST thing that is still honest:
resolve, for a small number of workout_type categories whose Daniels pace
mapping is unambiguous and literal (not an invented split/quantity), the
single generic pace ZONE applicable to the WHOLE session — never a
repetition count, never a warmup/cooldown split, never a recovery duration,
never a segmented progression.

- "easy" / "recovery": the whole session is run at Easy pace — this is the
  literal definition of the category, not an invented decomposition.
- "long_easy": a long run is, by definition, run at Easy pace end-to-end;
  no marathon-pace segment is prescribed by the engine, so none is shown.
- "quality": the engine explicitly has NOT decided which quality variant
  this is (threshold? interval? fartlek?) — attaching e.g. Threshold pace
  would itself be an invented physiological decision. No pace zone is
  resolved; the UI must show "target pace: unspecified" instead.
- "steady": not part of the Daniels E/M/T/I/R vocabulary — no pace zone.
- "rest" / unknown: no pace zone.

If/when the Training Engine produces a real canonical structure (blocks,
repetitions, pace zone) as part of `WorkoutPrescription` itself — frozen
into the prescription snapshot BEFORE it is ever served — this module (or
its replacement) should read that structure directly instead of re-deriving
anything from `workout_type`. See RUNINDEX_PR232_REPORT.md for the
prescription-canonique vs présentation distinction.
"""

from __future__ import annotations

from typing import Optional

from .training_paces import PaceRange, TrainingPaces

# workout_type categories whose ENTIRE session is, by definition, run at
# Easy pace — not an invented split, just the literal meaning of the
# category name already decided by the Training Engine.
_WHOLE_SESSION_EASY_PACE_TYPES: frozenset[str] = frozenset({"easy", "recovery", "long_easy"})


def resolve_session_pace_zone(
    *,
    workout_type: Optional[str],
    paces: Optional[TrainingPaces],
) -> Optional[PaceRange]:
    """Return the single generic pace zone applicable to the WHOLE session,
    or None when the Training Engine has not decided (or does not expose)
    an unambiguous pace zone for this workout_type.

    Never returns a repetition count, split, warmup/cooldown decomposition,
    or recovery duration — those are not prescribed by the Training Engine
    today and must not be invented here.
    """
    if not workout_type or paces is None:
        return None
    if workout_type in _WHOLE_SESSION_EASY_PACE_TYPES:
        return paces.easy
    # "quality": exact nature undecided by the engine — no pace fabricated.
    # "steady": not in the Daniels E/M/T/I/R vocabulary — no pace zone.
    # "rest" / anything else: no pace zone.
    return None
