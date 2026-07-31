from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel

from access_control import Tier, get_user_access
from auth.dependencies import require_admin
from auth.roles import is_admin_user, resolve_user_role


admin_router = APIRouter(prefix="/admin", tags=["admin"])


class AdminUserItem(BaseModel):
    id: str
    email: str
    role: str
    is_admin: bool
    status: str
    trial_active: bool
    trial_used: bool
    trial_days_remaining: Optional[int] = None
    garmin_connected: bool
    created_at: Optional[str] = None
    last_login_at: Optional[str] = None


class AdminUsersResponse(BaseModel):
    users: list[AdminUserItem]
    total: int


def _serialize_datetime(value) -> Optional[str]:
    if value is None:
        return None
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return str(value)


@admin_router.get("/users", response_model=AdminUsersResponse)
async def list_admin_users(
    request: Request,
    _admin: dict = Depends(require_admin),
):
    db = request.app.state.db

    user_docs = await db.users.find(
        {},
        {
            "_id": 0,
            "id": 1,
            "email": 1,
            "role": 1,
            "created_at": 1,
            "last_login_at": 1,
        },
    ).sort("created_at", -1).to_list(500)

    subscriptions = await db.subscriptions.find(
        {},
        {
            "_id": 0,
            "user_id": 1,
            "status": 1,
            "trial_used": 1,
        },
    ).to_list(1000)
    subscriptions_by_user = {
        subscription["user_id"]: subscription for subscription in subscriptions
    }

    garmin_connections = await db.garmin_connections.find(
        {"connected": True},
        {"_id": 0, "user_id": 1},
    ).to_list(1000)
    garmin_user_ids = {
        connection["user_id"] for connection in garmin_connections if connection.get("user_id")
    }

    items: list[AdminUserItem] = []
    for user_doc in user_docs:
        user_access = await get_user_access(db, user_doc["id"])
        subscription = subscriptions_by_user.get(user_doc["id"], {})
        status = user_access.tier.value
        if status not in {Tier.FREE.value, Tier.TRIAL.value, Tier.PREMIUM.value}:
            status = Tier.FREE.value

        items.append(
            AdminUserItem(
                id=user_doc["id"],
                email=user_doc["email"],
                role=resolve_user_role(user_doc),
                is_admin=is_admin_user(user_doc),
                status=status,
                trial_active=user_access.is_trial,
                trial_used=bool(subscription.get("trial_used")),
                trial_days_remaining=user_access.trial_days_remaining,
                garmin_connected=user_doc["id"] in garmin_user_ids,
                created_at=_serialize_datetime(user_doc.get("created_at")),
                last_login_at=_serialize_datetime(user_doc.get("last_login_at")),
            )
        )

    return AdminUsersResponse(users=items, total=len(items))
