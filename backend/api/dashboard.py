"""
Dashboard API route — HTTP layer.

Exposes GET /api/dashboard (prefix /api is added by server.py include_router).
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request

from auth.dependencies import get_current_user
from services.dashboard_service import get_dashboard

dashboard_router = APIRouter()


@dashboard_router.get("/dashboard")
async def dashboard_endpoint(request: Request, user: dict = Depends(get_current_user)):
    """Return readiness score, ACWR, workout recommendation, and last runs."""
    db = request.app.state.db
    user_id: str = user["id"]
    return await get_dashboard(db, user_id=user_id)
