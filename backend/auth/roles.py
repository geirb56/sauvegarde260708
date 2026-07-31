"""Helpers for backend user roles."""

from __future__ import annotations

import os


def _admin_emails() -> set[str]:
    raw = os.getenv("ADMIN_EMAILS", "")
    return {
        email.strip().lower()
        for email in raw.split(",")
        if email.strip()
    }


def resolve_user_role(user: dict | None) -> str:
    if not user:
        return "user"

    role = str(user.get("role") or "").strip().lower()
    if role == "admin":
        return "admin"

    email = str(user.get("email") or "").strip().lower()
    if email and email in _admin_emails():
        return "admin"

    return "user"


def is_admin_user(user: dict | None) -> bool:
    return resolve_user_role(user) == "admin"
