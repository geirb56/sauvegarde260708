from __future__ import annotations

import coach_service


def test_weekly_review_chain_is_removed_from_public_api():
    assert not hasattr(coach_service, "weekly_review")
    assert "weekly_review" not in getattr(coach_service, "__all__", [])


def test_metrics_and_cache_contracts_exclude_weekly_fields():
    metrics = coach_service.get_metrics()
    assert "weekly_requests" not in metrics

    cleared = coach_service.clear_cache()
    assert "cleared_weekly" not in cleared

    cache_stats = coach_service.get_cache_stats()
    assert "weekly_cache_size" not in cache_stats
