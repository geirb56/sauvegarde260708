from __future__ import annotations

from pathlib import Path


SERVER_PATH = Path(__file__).resolve().parents[1] / "server.py"


def test_pr189_server_route_contains_prediction_level_contract_fields():
    code = SERVER_PATH.read_text(encoding="utf-8")
    assert '@api_router.get("/training/race-predictions")' in code
    assert '"predicted_time_s": pred.predicted_time_s' in code
    assert '"extrapolation_ratio": pred.extrapolation_ratio' in code
    assert '"is_strong_extrapolation": (' in code
    assert '"curve_method": pred.curve_method' in code
    assert '"curve_k": pred.curve_k' in code
    assert '"contributors_count": pred.contributors_count' in code


def test_pr189_server_route_contains_curve_level_diagnostics_contract_fields():
    code = SERVER_PATH.read_text(encoding="utf-8")
    assert '"race_curve_diagnostics": {' in code
    for key in [
        '"curve_method": curve_diag.get("curve_method")',
        '"curve_k": curve_diag.get("curve_k")',
        '"contributors_count": curve_diag.get("contributors_count")',
        '"qualified_performance_count": curve_diag.get("qualified_performance_count")',
        '"observed_distance_min_km": curve_diag.get("observed_distance_min_km")',
        '"observed_distance_max_km": curve_diag.get("observed_distance_max_km")',
        '"fit_quality": curve_diag.get("fit_quality")',
        '"k_conflict": curve_diag.get("k_conflict")',
        '"k_fallback_applied": curve_diag.get("k_fallback_applied")',
        '"weighted_recency": curve_diag.get("weighted_recency")',
        '"weighted_quality_confidence": curve_diag.get("weighted_quality_confidence")',
        '"weighted_quality_score": curve_diag.get("weighted_quality_score")',
        '"effective_contributors": curve_diag.get("effective_contributors")',
    ]:
        assert key in code


def test_pr192_server_route_contains_slope_evidence_diagnostics_fields():
    """PR #192 — slope_evidence fields must be propagated in race_curve_diagnostics."""
    code = SERVER_PATH.read_text(encoding="utf-8")
    for key in [
        '"slope_evidence_count": curve_diag.get("slope_evidence_count")',
        '"slope_evidence_distance_min": curve_diag.get("slope_evidence_distance_min")',
        '"slope_evidence_distance_max": curve_diag.get("slope_evidence_distance_max")',
        '"slope_evidence_distance_min_km": curve_diag.get("slope_evidence_distance_min_km")',
        '"slope_evidence_distance_max_km": curve_diag.get("slope_evidence_distance_max_km")',
    ]:
        assert key in code, f"Missing slope_evidence propagation in server.py: {key}"
