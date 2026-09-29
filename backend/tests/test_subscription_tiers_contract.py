from __future__ import annotations

import os
import sys
from unittest.mock import AsyncMock

import httpx
import pytest

os.environ.setdefault("JWT_SECRET_KEY", "subscription-tiers-test-secret-32chars")
os.environ.setdefault("JWT_ALGORITHM", "HS256")
os.environ.setdefault("JWT_ACCESS_TOKEN_EXPIRE_MINUTES", "60")
os.environ.setdefault("ENVIRONMENT", "test")
os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "test_db")

_BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _BACKEND_DIR not in sys.path:
    sys.path.insert(0, _BACKEND_DIR)

import server  # noqa: E402
from auth.jwt_utils import create_access_token  # noqa: E402


def _bearer(user_id: str) -> dict[str, str]:
    token = create_access_token(user_id, f"{user_id}@example.test")
    return {"Authorization": "Bearer " + token}


async def _get_tiers(headers: dict[str, str] | None = None) -> httpx.Response:
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=server.app),
        base_url="http://test",
    ) as client:
        return await client.get("/api/subscription/tiers", headers=headers)


@pytest.mark.asyncio
async def test_subscription_tiers_route_returns_only_canonical_monthly_offers():
    response = await _get_tiers()

    assert response.status_code == 200
    tiers = response.json()
    assert [tier["id"] for tier in tiers] == ["free", "trial", "premium"]
    assert {tier["id"] for tier in tiers}.isdisjoint({"starter", "confort", "pro"})

    by_id = {tier["id"]: tier for tier in tiers}
    assert by_id["free"]["price_monthly"] == 0
    assert by_id["free"]["messages_limit"] == 10
    assert by_id["free"]["unlimited"] is False

    assert by_id["trial"]["price_monthly"] == 0
    assert by_id["trial"]["messages_limit"] is None
    assert by_id["trial"]["unlimited"] is True
    assert "30 days" in by_id["trial"]["description"]
    assert "eligible Garmin account" in by_id["trial"]["description"]
    assert "no card" in by_id["trial"]["description"]

    assert by_id["premium"]["price_monthly"] == 4.99
    assert by_id["premium"]["messages_limit"] is None
    assert by_id["premium"]["unlimited"] is True

    for tier in tiers:
        assert "price_annual" not in tier
        assert not any("annual" in key.lower() for key in tier)
    assert all(
        "anti-abuse protections" in by_id[tier_id]["description"]
        for tier_id in ("trial", "premium")
    )


@pytest.mark.asyncio
async def test_subscription_tiers_route_is_independent_of_viewing_user(monkeypatch):
    access_lookup = AsyncMock(side_effect=AssertionError("catalog must not resolve user access"))
    monkeypatch.setattr(server, "get_user_access", access_lookup)

    free_user_response = await _get_tiers(_bearer("free-viewer"))
    premium_user_response = await _get_tiers(_bearer("premium-viewer"))

    assert free_user_response.status_code == premium_user_response.status_code == 200
    assert free_user_response.json() == premium_user_response.json()
    access_lookup.assert_not_awaited()


@pytest.mark.asyncio
async def test_subscription_tiers_route_has_no_database_or_paddle_side_effects(monkeypatch):
    database_accesses: list[str] = []

    class DatabaseGuard:
        def __getattr__(self, name: str):
            database_accesses.append(name)
            raise AssertionError(f"catalog accessed database attribute {name}")

    class PaddleClientGuard:
        def __init__(self, *args, **kwargs):
            raise AssertionError("catalog attempted an outbound Paddle request")

    client = httpx.AsyncClient(
        transport=httpx.ASGITransport(app=server.app),
        base_url="http://test",
    )
    try:
        with monkeypatch.context() as patch_context:
            patch_context.setattr(server, "db", DatabaseGuard())
            patch_context.setattr(server.httpx, "AsyncClient", PaddleClientGuard)
            response = await client.get("/api/subscription/tiers")
    finally:
        await client.aclose()

    assert response.status_code == 200
    assert database_accesses == []


def test_subscription_tier_model_accepts_missing_commercial_message_limit():
    tier = server.SubscriptionTierInfo(
        id="trial",
        name="Trial",
        price_monthly=0,
        messages_limit=None,
        unlimited=True,
        description="30 days of Premium access.",
    )

    assert tier.model_dump()["messages_limit"] is None
    assert "price_annual" not in tier.model_dump()
