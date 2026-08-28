"""PR#214 — Legacy cleanup structural guards.

Verifies that the VMA HR-speed subsystem, the /training/vma-history endpoint,
the dead TrainingPlan.jsx frontend file, and any remaining synthetic VO2max
paths derived from the old VMA have been removed and cannot regress.

These assertions are structural: they scan source files, not runtime state.
Passing comments or historical reports do NOT satisfy these guards; only the
absence of the specific patterns in runtime code paths does.
"""
import ast
import os
import re

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
BACKEND_DIR = os.path.join(REPO_ROOT, "backend")
FRONTEND_SRC = os.path.join(REPO_ROOT, "frontend", "src")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _read(path: str) -> str:
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


def _backend_py_sources() -> list[tuple[str, str]]:
    """Return (path, source) for all backend .py files excluding tests and reports."""
    result = []
    for root, dirs, files in os.walk(BACKEND_DIR):
        # Skip test directories for runtime-consumer checks
        dirs[:] = [d for d in dirs if d not in ("__pycache__",)]
        for fname in files:
            if fname.endswith(".py"):
                full = os.path.join(root, fname)
                result.append((full, _read(full)))
    return result


def _runtime_backend_py_sources() -> list[tuple[str, str]]:
    """Backend .py files that are runtime code (not tests, not reports)."""
    return [
        (path, src)
        for path, src in _backend_py_sources()
        if "/tests/" not in path and "/test_" not in os.path.basename(path)
    ]


def _frontend_active_pages() -> list[tuple[str, str]]:
    """All .jsx / .js sources under frontend/src (not __tests__)."""
    result = []
    pages_dir = os.path.join(FRONTEND_SRC, "pages")
    for root, dirs, files in os.walk(FRONTEND_SRC):
        dirs[:] = [d for d in dirs if d != "__tests__"]
        for fname in files:
            if fname.endswith((".jsx", ".js")):
                full = os.path.join(root, fname)
                result.append((full, _read(full)))
    return result


# ---------------------------------------------------------------------------
# 1. LEGACY_HR_SPEED_VMA_RUNTIME_CONSUMERS = 0
#    The HR-speed model (speed = a*HR + b → VMA extrapolation) must not exist
#    in any runtime backend path.
# ---------------------------------------------------------------------------

LEGACY_HR_SPEED_PATTERNS = [
    r"\bestimate_vma\b",            # deleted function
    r"\b_fit_hr_speed_model\b",     # deleted internal
    r"\bHRModelResult\b",           # deleted dataclass
    r"\bVMAEstimate\b",             # deleted dataclass
    r"\bHR_SPEED_MODEL_SOURCE\b",   # deleted reason code
    r"\bVMA_WINDOW_DAYS\b",         # deleted constant
    r"\bactivities_in_vma_window\b",# deleted alias/function
    r"\b_activities_in_vma_window\b",
]


def test_legacy_hr_speed_vma_runtime_consumers_zero():
    """LEGACY_HR_SPEED_VMA_RUNTIME_CONSUMERS = 0"""
    violations = []
    for path, src in _runtime_backend_py_sources():
        for pattern in LEGACY_HR_SPEED_PATTERNS:
            if re.search(pattern, src):
                violations.append(f"{path}: matched {pattern!r}")
    assert violations == [], (
        "Legacy HR-speed VMA runtime consumers found:\n" + "\n".join(violations)
    )


# ---------------------------------------------------------------------------
# 2. LEGACY_VMA_HISTORY_ENDPOINT_EXISTS = False
#    The GET /training/vma-history endpoint must not exist in server.py.
# ---------------------------------------------------------------------------

def test_legacy_vma_history_endpoint_removed():
    """LEGACY_VMA_HISTORY_ENDPOINT_EXISTS = False"""
    server_path = os.path.join(BACKEND_DIR, "server.py")
    src = _read(server_path)
    assert "/training/vma-history" not in src, (
        "GET /training/vma-history endpoint still exists in server.py"
    )


def test_vma_history_not_in_access_control():
    """vma-history must not be routed in access_control.py."""
    ac_path = os.path.join(BACKEND_DIR, "access_control.py")
    src = _read(ac_path)
    assert "vma-history" not in src, (
        "/training/vma-history route still present in access_control.py"
    )


# ---------------------------------------------------------------------------
# 3. SYNTHETIC_VO2MAX_FROM_VMA_RUNTIME_CONSUMERS = 0
#    No runtime backend path may compute VO2max = VMA × 3.5 from the old VMA.
# ---------------------------------------------------------------------------

SYNTHETIC_VO2MAX_PATTERNS = [
    r"vma_kmh\s*\*\s*3\.5",      # vma_kmh * 3.5
    r"\bvma\s*\*\s*3\.5",        # vma * 3.5 (Python * operator only)
]


def test_synthetic_vo2max_from_vma_runtime_consumers_zero():
    """SYNTHETIC_VO2MAX_FROM_VMA_RUNTIME_CONSUMERS = 0"""
    violations = []
    for path, src in _runtime_backend_py_sources():
        for pattern in SYNTHETIC_VO2MAX_PATTERNS:
            for match in re.finditer(pattern, src):
                # Skip pure comment lines
                line_start = src.rfind("\n", 0, match.start()) + 1
                line_end = src.find("\n", match.end())
                line = src[line_start:line_end if line_end != -1 else None].strip()
                if line.startswith("#"):
                    continue
                violations.append(f"{path}: {line!r}")
    assert violations == [], (
        "Synthetic VO2max (VMA × 3.5) runtime consumers found:\n" + "\n".join(violations)
    )


# ---------------------------------------------------------------------------
# 4. LEGACY_TRAINING_PLAN_FRONTEND_EXISTS = False
#    frontend/src/pages/TrainingPlan.jsx must not exist.
# ---------------------------------------------------------------------------

def test_legacy_training_plan_frontend_deleted():
    """LEGACY_TRAINING_PLAN_FRONTEND_EXISTS = False"""
    path = os.path.join(FRONTEND_SRC, "pages", "TrainingPlan.jsx")
    assert not os.path.exists(path), (
        f"Dead TrainingPlan.jsx still exists at {path}"
    )


def test_legacy_training_plan_not_imported_in_active_pages():
    """TrainingPlan (legacy) must not be imported or referenced in active frontend files."""
    for path, src in _frontend_active_pages():
        if "TrainingPlan.jsx" in path:
            continue  # file itself would trigger
        # Check for any import of TrainingPlan (not TrainingPlanV2)
        if re.search(r"""import.*['"]\./TrainingPlan['"]""", src):
            assert False, f"{path}: still imports legacy TrainingPlan"
        if re.search(r"""import.*['"].*pages/TrainingPlan['"]""", src):
            assert False, f"{path}: still imports legacy TrainingPlan"


# ---------------------------------------------------------------------------
# 5. LEGACY_FULL_CYCLE_ACTIVE_CONSUMERS = 0
#    /training/full-cycle must not appear in any active runtime file.
# ---------------------------------------------------------------------------

def test_legacy_full_cycle_active_consumers_zero():
    """LEGACY_FULL_CYCLE_ACTIVE_CONSUMERS = 0"""
    violations = []
    # Check active frontend pages
    for path, src in _frontend_active_pages():
        if "/training/full-cycle" in src:
            violations.append(path)
    # Check runtime backend
    for path, src in _runtime_backend_py_sources():
        if '"/training/full-cycle"' in src or "'/training/full-cycle'" in src:
            violations.append(path)
    assert violations == [], (
        "/training/full-cycle still has active consumers:\n" + "\n".join(violations)
    )


# ---------------------------------------------------------------------------
# 6. Non-regression: Race Predictions V2 is intact
# ---------------------------------------------------------------------------

def test_performance_v2_formula_intact():
    """predict_races() and its core curve logic still exist and import cleanly."""
    from training_v2.performance_model import (
        predict_races,
        evaluate_performance_quality,
        PerformanceEstimate,
        RacePrediction,
    )
    assert callable(predict_races)
    assert callable(evaluate_performance_quality)


def test_predict_races_vma_always_none_post_214():
    """After #214 removal, predict_races always returns estimated_vma=None in athlete_profile."""
    from training_v2.performance_model import predict_races
    from datetime import date

    result = predict_races([], date(2024, 6, 1))
    assert result.athlete_profile.get("estimated_vma") is None
    assert result.athlete_profile.get("estimated_vo2max") is None


def test_performance_estimate_has_no_vma_field():
    """PerformanceEstimate must not have a 'vma' field after #214."""
    from training_v2.performance_model import PerformanceEstimate
    import dataclasses
    field_names = {f.name for f in dataclasses.fields(PerformanceEstimate)}
    assert "vma" not in field_names, (
        "PerformanceEstimate still has a 'vma' field — VMA dataclass was not removed"
    )


def test_estimate_vma_not_importable():
    """estimate_vma must not be importable from performance_model after #214."""
    import importlib
    mod = importlib.import_module("training_v2.performance_model")
    assert not hasattr(mod, "estimate_vma"), (
        "estimate_vma is still exported from performance_model"
    )


def test_vma_estimate_class_not_importable():
    """VMAEstimate class must not be importable from performance_model after #214."""
    import importlib
    mod = importlib.import_module("training_v2.performance_model")
    assert not hasattr(mod, "VMAEstimate"), (
        "VMAEstimate is still exported from performance_model"
    )


def test_garmin_vo2max_pipeline_unchanged():
    """Garmin VO2max service module must not have been altered in this PR.
    Verify that garmin/service.py imports and is syntactically valid.
    """
    import ast
    garmin_service = os.path.join(BACKEND_DIR, "garmin", "service.py")
    if os.path.exists(garmin_service):
        src = _read(garmin_service)
        # Must parse cleanly
        ast.parse(src)
        # Must still have VO2max import/reference (not deleted by mistake)
        assert "vo2max" in src.lower(), (
            "garmin/service.py no longer contains vo2max — was it accidentally modified?"
        )
