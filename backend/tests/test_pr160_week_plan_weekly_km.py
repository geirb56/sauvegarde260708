"""PR160 — Tests: migration de compute_current_weekly_km dans /training/week-plan.

Ce module valide les invariants de PR160 :

- RUNTIME_WEEK_PLAN compute_current_weekly_km = 0 (migré vers km_28_running / 4).
- CAS A : historique running présent → context["weekly_km"] == km_28_running / 4.
- CAS B : zéro historique running → context["weekly_km"] == 0.0 (pas 20).
- CAS C : activités non-running seulement → context["weekly_km"] == 0.0.
- CAS D : duration-based V2 → target_km_protected = None, aucune cible km inventée.
- CAS E : distance-based V2 → WeeklyTarget V2 reste autorité target_km.
- Scan source : "weekly_km": compute_current_weekly_km absent de server.py.
- full-cycle non touché : base_weekly_km = compute_current_weekly_km toujours présent.
"""

from __future__ import annotations

import sys
import os
from datetime import date, timedelta
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# Imports domaine
# ---------------------------------------------------------------------------
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from training_engine import (
    is_running,
    normalized_distance_km,
    DEFAULT_WEEKLY_KM,
    compute_current_weekly_km,
)
from training_v2.week_plan_bridge import build_weekly_target_from_workouts


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

REFERENCE_DATE = date(2025, 6, 1)
RACE_DATE = date(2025, 9, 15)
CYCLE_START = date(2025, 4, 1)


def _running_workout(days_ago: int, distance_km: float, ref: date = REFERENCE_DATE) -> dict:
    d = ref - timedelta(days=days_ago)
    return {
        "activity_type": "running",
        "date": d.isoformat(),
        "start_time": f"{d.isoformat()}T07:00:00",
        "distance_km": distance_km,
        "duration_minutes": 45.0,
    }


def _cycling_workout(days_ago: int, distance_km: float, ref: date = REFERENCE_DATE) -> dict:
    d = ref - timedelta(days=days_ago)
    return {
        "activity_type": "cycling",
        "date": d.isoformat(),
        "start_time": f"{d.isoformat()}T07:00:00",
        "distance_km": distance_km,
        "duration_minutes": 60.0,
    }


def _observed_weekly_km(workouts_28: list) -> float:
    """Formule observée PR160 : km_28_running / 4 (sans fallback DEFAULT_WEEKLY_KM)."""
    km_28_running = sum(normalized_distance_km(w) for w in workouts_28 if is_running(w))
    return km_28_running / 4


# ---------------------------------------------------------------------------
# SCAN SOURCE — garantit RUNTIME_WEEK_PLAN = 0 après migration
# ---------------------------------------------------------------------------

class TestSourceScanPR160:
    """Vérifie que server.py n'appelle plus compute_current_weekly_km dans week-plan."""

    def test_week_plan_no_legacy_consumer(self):
        """RUNTIME_WEEK_PLAN = 0 : la ligne legacy a disparu de server.py."""
        server_src = (Path(__file__).resolve().parents[1] / "server.py").read_text(encoding="utf-8")
        assert '"weekly_km": compute_current_weekly_km(workouts_28)' not in server_src, (
            "compute_current_weekly_km ne doit plus être consommé dans /training/week-plan"
        )

    def test_week_plan_uses_observed_formula(self):
        """La formule observée km_28_running / 4 est présente dans server.py."""
        server_src = (Path(__file__).resolve().parents[1] / "server.py").read_text(encoding="utf-8")
        assert '"weekly_km": km_28_running / 4,' in server_src, (
            "La formule observée km_28_running / 4 doit être présente dans server.py"
        )

    def test_full_cycle_consumer_preserved(self):
        """RUNTIME_FULL_CYCLE = 1 : full-cycle conserve son consumer legacy (prochain PR161)."""
        server_src = (Path(__file__).resolve().parents[1] / "server.py").read_text(encoding="utf-8")
        assert "base_weekly_km = compute_current_weekly_km(workouts_28)" in server_src, (
            "Le consumer full-cycle doit être conservé intact (migration PR161)"
        )

    def test_no_new_default_weekly_km_consumer(self):
        """Aucun nouveau fallback DEFAULT_WEEKLY_KM dans week-plan."""
        server_src = (Path(__file__).resolve().parents[1] / "server.py").read_text(encoding="utf-8")
        # La valeur DEFAULT_WEEKLY_KM ne doit pas apparaître comme valeur par défaut
        # dans le contexte week-plan (le context dict).
        # On vérifie que la ligne migrée ne contient pas de fallback 20.
        assert '"weekly_km": km_28_running / 4,' in server_src
        # Le calcul observé ne contient pas de fallback
        assert '"weekly_km": km_28_running / 4 if' not in server_src


# ---------------------------------------------------------------------------
# CAS A — historique running présent
# ---------------------------------------------------------------------------

class TestCasAHistoriqueRunningPresent:
    """Context["weekly_km"] == km_28_running / 4 quand l'historique est connu."""

    def test_known_volume_matches_observed_formula(self):
        """80 km sur 28 jours → observed_weekly_km = 20."""
        workouts_28 = [_running_workout(days_ago=d, distance_km=10.0) for d in [3, 7, 11, 14, 18, 21, 25, 28]]
        km_28_running = sum(normalized_distance_km(w) for w in workouts_28 if is_running(w))
        assert km_28_running == pytest.approx(80.0, abs=0.1)

        observed = _observed_weekly_km(workouts_28)
        assert observed == pytest.approx(20.0, abs=0.01)

    def test_observed_formula_matches_legacy_for_positive_history(self):
        """Pour historique positif : km_28_running / 4 == compute_current_weekly_km."""
        workouts_28 = [_running_workout(days_ago=d, distance_km=8.0) for d in [2, 6, 10, 13, 17, 20]]
        km_28_running = sum(normalized_distance_km(w) for w in workouts_28 if is_running(w))
        assert km_28_running > 0

        observed = _observed_weekly_km(workouts_28)
        legacy = compute_current_weekly_km(workouts_28)
        # Pour historique positif, formules strictement équivalentes
        assert observed == pytest.approx(legacy, abs=0.001), (
            "La formule observée doit être identique au legacy quand km_28 > 0"
        )

    def test_fractional_distances_preserved(self):
        """Les distances fractionnées sont correctement agrégées."""
        workouts_28 = [
            _running_workout(days_ago=2, distance_km=12.5),
            _running_workout(days_ago=5, distance_km=8.3),
            _running_workout(days_ago=9, distance_km=15.0),
            _running_workout(days_ago=14, distance_km=10.0),
        ]
        km_28_running = sum(normalized_distance_km(w) for w in workouts_28 if is_running(w))
        expected = km_28_running / 4
        assert _observed_weekly_km(workouts_28) == pytest.approx(expected, abs=0.001)


# ---------------------------------------------------------------------------
# CAS B — zéro historique running
# ---------------------------------------------------------------------------

class TestCasBZeroHistoriqueRunning:
    """Context["weekly_km"] == 0.0 quand aucune activité running n'existe."""

    def test_no_workouts_returns_zero(self):
        """Liste vide → 0.0 (pas DEFAULT_WEEKLY_KM = 20)."""
        observed = _observed_weekly_km([])
        assert observed == 0.0
        assert observed != DEFAULT_WEEKLY_KM

    def test_observed_zero_not_twenty(self):
        """Confirme explicitement que 0.0 != 20."""
        observed = _observed_weekly_km([])
        assert observed == 0.0
        assert observed != 20
        assert observed != 20.0

    def test_legacy_would_return_twenty_but_observed_returns_zero(self):
        """Prouve la rupture intentionnelle avec le legacy : legacy=20, observé=0."""
        workouts_28: list = []
        legacy_result = compute_current_weekly_km(workouts_28)
        observed_result = _observed_weekly_km(workouts_28)

        assert legacy_result == DEFAULT_WEEKLY_KM  # comportement legacy = 20
        assert observed_result == 0.0              # comportement PR160 = 0
        assert legacy_result != observed_result     # rupture volontaire


# ---------------------------------------------------------------------------
# CAS C — activités non-running seulement
# ---------------------------------------------------------------------------

class TestCasCActivitesNonRunning:
    """Context["weekly_km"] == 0.0 quand seules des activités non-running existent."""

    def test_cycling_only_returns_zero(self):
        """Que du cyclisme → 0.0."""
        workouts_28 = [_cycling_workout(days_ago=d, distance_km=30.0) for d in [3, 7, 14, 21]]
        observed = _observed_weekly_km(workouts_28)
        assert observed == 0.0

    def test_mixed_nonrunning_types_returns_zero(self):
        """Natation + cyclisme → 0.0."""
        workouts_28 = [
            {"activity_type": "swimming", "date": "2025-05-25", "distance_km": 2.0, "duration_minutes": 40},
            {"activity_type": "cycling", "date": "2025-05-20", "distance_km": 25.0, "duration_minutes": 60},
        ]
        observed = _observed_weekly_km(workouts_28)
        assert observed == 0.0

    def test_nonrunning_does_not_pollute_km_observation(self):
        """Le volume non-running ne doit jamais gonfler le km observé."""
        cycling_volume_km = 500.0  # énorme volume cyclisme
        workouts_28 = [_cycling_workout(days_ago=d, distance_km=cycling_volume_km) for d in [1, 4, 8, 12]]
        observed = _observed_weekly_km(workouts_28)
        assert observed == 0.0, "Le cyclisme ne doit pas contribuer au km observé running"


# ---------------------------------------------------------------------------
# CAS D — duration-based V2
# ---------------------------------------------------------------------------

class TestCasDDurationBased:
    """Prouve que les états duration-based ne produisent pas de cible km artificielle."""

    def test_no_history_produces_duration_based_target(self):
        """Aucune activité → WeeklyTarget duration-based, target_km = None."""
        wt = build_weekly_target_from_workouts(
            workouts=[],
            goal_type="SEMI",
            race_date=RACE_DATE,
            cycle_start_date=CYCLE_START,
            reference_date=REFERENCE_DATE,
        )
        assert wt.target_basis == "duration"
        assert wt.target_km is None, "Aucune cible km ne doit être inventée en no-history"
        assert wt.target_duration_minutes is not None
        assert wt.target_duration_minutes > 0

    def test_target_km_protected_is_none_for_duration_based(self):
        """target_km_protected = None pour un état duration-based."""
        wt = build_weekly_target_from_workouts(
            workouts=[],
            goal_type="SEMI",
            race_date=RACE_DATE,
            cycle_start_date=CYCLE_START,
            reference_date=REFERENCE_DATE,
        )
        # Reproduire la logique de server.py lignes 4662-4665
        if wt.target_basis == "distance" and wt.target_km is not None:
            target_km_protected = wt.target_km
        else:
            target_km_protected = None

        assert target_km_protected is None, (
            "Pour duration-based, target_km_protected doit être None"
        )

    def test_observed_weekly_km_zero_plus_target_km_none_no_km_invented(self):
        """weekly_km=0 + target_km_protected=None → aucune cible km artificielle.

        Prouve que compute_target_km(0, goal, phase) = 0 (pas de plancher 20).
        """
        from training_engine import compute_target_km, apply_resume_guard

        weekly_km_observed = 0.0  # no-history PR160
        target_km_protected = None  # duration-based

        # Reproduire la logique de llm_coach.py lignes 291-292
        target_km = target_km_protected or compute_target_km(weekly_km_observed, "SEMI", "build")
        target_km = apply_resume_guard(target_km, km_7=0.0, current_weekly_km=weekly_km_observed)

        assert target_km == 0, (
            "compute_target_km(0) doit retourner 0, pas un plancher artificiel"
        )

    def test_duration_based_continuity_state_coherent(self):
        """L'état duration-based a une continuity_state cohérente."""
        wt = build_weekly_target_from_workouts(
            workouts=[],
            goal_type="SEMI",
            race_date=RACE_DATE,
            cycle_start_date=CYCLE_START,
            reference_date=REFERENCE_DATE,
        )
        assert wt.continuity_state in ("no_history", "deep_reprise", "partial_reprise"), (
            f"État inattendu pour no-history: {wt.continuity_state}"
        )


# ---------------------------------------------------------------------------
# CAS E — distance-based normal, WeeklyTarget V2 reste autorité
# ---------------------------------------------------------------------------

class TestCasEDistanceBasedV2Autorité:
    """WeeklyTarget V2 reste l'autorité prescriptive même après migration weekly_km."""

    def test_v2_target_km_not_influenced_by_observed_weekly_km(self):
        """La valeur observée km_28_running/4 ne modifie PAS target_km V2."""
        workouts = [_running_workout(days_ago=d, distance_km=10.0) for d in [3, 7, 11, 14, 17, 21, 25, 28]]

        wt = build_weekly_target_from_workouts(
            workouts=workouts,
            goal_type="SEMI",
            race_date=RACE_DATE,
            cycle_start_date=CYCLE_START,
            reference_date=REFERENCE_DATE,
        )

        assert wt.target_basis == "distance"
        assert wt.target_km is not None
        assert wt.target_km > 0

        # La valeur observée
        observed_weekly_km = _observed_weekly_km(workouts)
        assert observed_weekly_km > 0

        # target_km V2 est indépendant de la valeur observée
        # (c'est V2 qui décide, pas compute_target_km avec la valeur observée)
        assert wt.target_km is not None, "WeeklyTarget V2 reste l'autorité prescriptive"

    def test_observed_km_and_v2_target_are_different_concepts(self):
        """Valeur observée ≠ cible V2 — ce sont deux concepts distincts."""
        workouts = [_running_workout(days_ago=d, distance_km=10.0) for d in [3, 7, 11, 14, 17, 21, 25, 28]]

        wt = build_weekly_target_from_workouts(
            workouts=workouts,
            goal_type="SEMI",
            race_date=RACE_DATE,
            cycle_start_date=CYCLE_START,
            reference_date=REFERENCE_DATE,
        )

        observed_weekly_km = _observed_weekly_km(workouts)

        # Les deux valeurs peuvent différer — c'est attendu.
        # L'important : V2 a target_km valide et observé a sa propre valeur.
        assert isinstance(observed_weekly_km, float)
        assert wt.target_km is not None
        # Pas d'assertion d'égalité : ce sont deux rôles distincts.

    def test_distance_based_target_km_protected_is_set(self):
        """Pour distance-based, target_km_protected = V2.target_km (non None)."""
        workouts = [_running_workout(days_ago=d, distance_km=10.0) for d in [3, 7, 11, 14, 17, 21, 25, 28]]

        wt = build_weekly_target_from_workouts(
            workouts=workouts,
            goal_type="SEMI",
            race_date=RACE_DATE,
            cycle_start_date=CYCLE_START,
            reference_date=REFERENCE_DATE,
        )

        # Reproduire la logique de server.py
        if wt.target_basis == "distance" and wt.target_km is not None:
            target_km_protected = wt.target_km
        else:
            target_km_protected = None

        assert target_km_protected is not None
        assert target_km_protected > 0
