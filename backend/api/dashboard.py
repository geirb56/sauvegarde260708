"""
Dashboard API route — HTTP layer.

Exposes GET /api/dashboard (prefix /api is added by server.py include_router).
"""

from __future__ import annotations

from fastapi import APIRouter, Request

from services.dashboard_service import get_dashboard

dashboard_router = APIRouter()


@dashboard_router.get("/dashboard")
async def dashboard_endpoint(request: Request):
    """Return readiness score, ACWR, workout recommendation, and last runs."""
    db = request.app.state.db
    # Optionally scope by user_id query parameter (unauthenticated default: None)
    user_id: str | None = request.query_params.get("user_id")
    return await get_dashboard(db, user_id=user_id)
