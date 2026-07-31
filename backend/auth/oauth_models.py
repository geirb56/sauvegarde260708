"""Pydantic models for OAuth (Google / Apple) authentication."""

from __future__ import annotations

from pydantic import BaseModel, field_validator


class GoogleAuthRequest(BaseModel):
    """Payload sent by the frontend after a successful Google Sign-In.

    The ``id_token`` is the raw Google ID token returned by Google Identity
    Services.  The backend verifies this token directly against Google's
    public keys — it is never trusted at face value.
    """

    id_token: str
    state: str

    @field_validator("id_token")
    @classmethod
    def id_token_not_empty(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("id_token must not be empty")
        return v.strip()

    @field_validator("state")
    @classmethod
    def state_not_empty(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("state must not be empty")
        return v.strip()


class AppleAuthRequest(BaseModel):
    """Payload sent by the frontend after a successful Sign in with Apple.

    The ``id_token`` is the raw Apple identity token returned by Apple's JS SDK.
    The backend verifies this token against Apple's public JWKS endpoint.

    ``email`` is forwarded from the Apple authorization response and is only
    present on the very first authorization; on subsequent logins Apple does
    not return it.  The backend uses Apple's stable ``sub`` claim as the
    primary identity, not the email.
    """

    id_token: str
    state: str
    email: str | None = None  # optional — only present on first Apple sign-in

    @field_validator("id_token")
    @classmethod
    def id_token_not_empty(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("id_token must not be empty")
        return v.strip()

    @field_validator("state")
    @classmethod
    def state_not_empty(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("state must not be empty")
        return v.strip()
