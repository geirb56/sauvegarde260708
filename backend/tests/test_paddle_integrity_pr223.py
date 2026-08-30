from __future__ import annotations

import hashlib
import hmac
import json
import os
import sys
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Optional
from unittest.mock import AsyncMock, patch

import httpx
import pytest

os.environ.setdefault("JWT_SECRET_KEY", "test-pr223-secret-32chars-long!!")
os.environ.setdefault("JWT_SECRET", "test-pr223-secret-32chars-long!!")
os.environ.setdefault("JWT_ALGORITHM", "HS256")
os.environ.setdefault("JWT_ACCESS_TOKEN_EXPIRE_MINUTES", "60")
os.environ.setdefault("ENVIRONMENT", "test")
os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "test_db")

_BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _BACKEND_DIR not in sys.path:
    sys.path.insert(0, _BACKEND_DIR)

if "config" in sys.modules:
    _config_mod = sys.modules["config"]
    _config_file = getattr(_config_mod, "__file__", "") or ""
    if "__path__" not in dir(_config_mod) or _BACKEND_DIR not in _config_file:
        for _key in [k for k in sys.modules if k == "config" or k.startswith("config.")]:
            del sys.modules[_key]

import server  # noqa: E402
from auth.jwt_utils import create_access_token  # noqa: E402

pytestmark = pytest.mark.asyncio

_USER_ID = "pr223-user"
_SECRET = "pr223-webhook-secret"
_REAL_ASYNC_CLIENT = httpx.AsyncClient


class _UpdateResult:
    matched_count = 1
    modified_count = 1


class _Collection:
    def __init__(self, docs: Optional[list[dict]] = None) -> None:
        self._docs = list(docs or [])

    @staticmethod
    def _matches(doc: dict, query: dict) -> bool:
        return all(doc.get(k) == v for k, v in query.items() if not isinstance(v, dict))

    async def find_one(self, query: dict, projection: Optional[dict] = None) -> Optional[dict]:
        for doc in self._docs:
            if self._matches(doc, query):
                if projection:
                    return {k: v for k, v in doc.items() if projection.get(k, 1)}
                return dict(doc)
        return None

    async def insert_one(self, doc: dict) -> None:
        self._docs.append(dict(doc))

    async def update_one(self, query: dict, update: dict, upsert: bool = False) -> _UpdateResult:
        for doc in self._docs:
            if self._matches(doc, query):
                doc.update(update.get("$set", {}))
                return _UpdateResult()
        if upsert:
            new_doc = dict(query)
            new_doc.update(update.get("$set", {}))
            self._docs.append(new_doc)
        return _UpdateResult()

    async def count_documents(self, query: dict) -> int:
        return sum(1 for doc in self._docs if self._matches(doc, query))


class _FakeDB:
    def __init__(self) -> None:
        self.subscriptions = _Collection()
        self.payment_transactions = _Collection()
        self.paddle_events = _Collection()

    def __getattr__(self, name: str) -> _Collection:
        col = _Collection()
        object.__setattr__(self, name, col)
        return col


class _FakePaddleResponse:
    def __init__(self, status_code: int, payload: dict) -> None:
        self.status_code = status_code
        self._payload = payload
        self.text = json.dumps(payload)

    def json(self) -> dict:
        return self._payload


class _FakePaddleClient:
    def __init__(self, response: _FakePaddleResponse, calls: list[dict]) -> None:
        self._response = response
        self._calls = calls

    async def __aenter__(self) -> "_FakePaddleClient":
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        return None

    async def post(self, url: str, json: dict, headers: dict, timeout: float) -> _FakePaddleResponse:
        self._calls.append(
            {"url": url, "json": json, "headers": headers, "timeout": timeout}
        )
        return self._response


def _bearer(user_id: str = _USER_ID, email: str = "pr223@example.com") -> dict:
    return {"Authorization": "Bearer " + create_access_token(user_id, email)}


def _override_user() -> dict:
    return {"id": _USER_ID, "email": "pr223@example.com", "authenticated": True}


def _make_sig(secret: str, ts: str, body: bytes) -> str:
    payload = f"{ts}:{body.decode('utf-8')}".encode("utf-8")
    digest = hmac.new(secret.encode("utf-8"), payload, hashlib.sha256).hexdigest()
    return f"ts={ts};h1={digest}"


async def _call(
    fake_db: _FakeDB,
    method: str,
    path: str,
    *,
    headers: Optional[dict] = None,
    json_body: Optional[dict] = None,
    patches: Optional[list[Any]] = None,
    raise_app_exceptions: bool = True,
) -> httpx.Response:
    patches = list(patches or [])
    started = []
    server.app.dependency_overrides[server.auth_user] = _override_user
    try:
        for item in [patch.object(server, "db", fake_db), *patches]:
            item.start()
            started.append(item)
        async with _REAL_ASYNC_CLIENT(
            transport=httpx.ASGITransport(
                app=server.app,
                raise_app_exceptions=raise_app_exceptions,
            ),
            base_url="http://test",
        ) as client:
            fn = getattr(client, method)
            kwargs: dict[str, Any] = {}
            if headers:
                kwargs["headers"] = headers
            if json_body is not None:
                kwargs["json"] = json_body
            return await fn(path, **kwargs)
    finally:
        server.app.dependency_overrides.clear()
        for item in reversed(started):
            item.stop()


async def test_checkout_uses_canonical_server_price_id():
    fake_db = _FakeDB()
    paddle_calls: list[dict] = []
    response = _FakePaddleResponse(201, {"data": {"id": "txn_123"}})

    patches = [
        patch.object(server, "PADDLE_API_KEY", "pdl_api_key"),
        patch.object(server, "PADDLE_PRICE_ID", "pri_server"),
        patch.object(server, "PADDLE_CLIENT_TOKEN", "client_token"),
        patch.object(server, "PADDLE_ENVIRONMENT", "sandbox"),
        patch.object(
            server.httpx,
            "AsyncClient",
            lambda *args, **kwargs: _FakePaddleClient(response, paddle_calls),
        ),
    ]
    res = await _call(
        fake_db,
        "post",
        "/api/subscription/paddle/checkout",
        headers=_bearer(),
        json_body={},
        patches=patches,
    )

    assert res.status_code == 200, res.text
    assert paddle_calls[0]["json"]["items"] == [{"price_id": "pri_server", "quantity": 1}]
    assert fake_db.payment_transactions._docs[0]["price_id"] == "pri_server"
    assert res.json()["price_id"] == "pri_server"


async def test_checkout_rejects_client_price_override():
    fake_db = _FakeDB()

    res = await _call(
        fake_db,
        "post",
        "/api/subscription/paddle/checkout",
        headers=_bearer(),
        json_body={"price_id": "pri_attacker"},
        patches=[
            patch.object(server, "PADDLE_API_KEY", "pdl_api_key"),
            patch.object(server, "PADDLE_PRICE_ID", "pri_server"),
        ],
    )

    assert res.status_code == 400, res.text
    assert await fake_db.payment_transactions.count_documents({}) == 0


async def test_checkout_fails_closed_without_server_price_id():
    fake_db = _FakeDB()

    res = await _call(
        fake_db,
        "post",
        "/api/subscription/paddle/checkout",
        headers=_bearer(),
        json_body={},
        patches=[
            patch.object(server, "PADDLE_API_KEY", "pdl_api_key"),
            patch.object(server, "PADDLE_PRICE_ID", ""),
        ],
    )

    assert res.status_code == 503, res.text
    assert await fake_db.payment_transactions.count_documents({}) == 0


async def test_invalid_webhook_signature_does_not_mutate_subscription():
    fake_db = _FakeDB()
    body = json.dumps(
        {
            "event_id": "evt_invalid_sig",
            "event_type": "subscription.activated",
            "data": {
                "id": "sub_123",
                "customer_id": "cus_123",
                "next_billed_at": (datetime.now(timezone.utc) + timedelta(days=30)).isoformat(),
                "custom_data": {"user_id": _USER_ID},
            },
        }
    ).encode()

    activate_mock = AsyncMock()
    res = await _call(
        fake_db,
        "post",
        "/api/webhook/paddle",
        headers={"Paddle-Signature": "ts=1;h1=bad"},
        patches=[
            patch.object(server, "PADDLE_WEBHOOK_SECRET", _SECRET),
            patch("subscription_manager.activate_premium", activate_mock),
        ],
        raise_app_exceptions=False,
    )

    assert res.status_code == 400, res.text
    assert activate_mock.await_count == 0
    assert await fake_db.paddle_events.count_documents({}) == 0


async def test_processed_webhook_is_idempotent():
    fake_db = _FakeDB()
    fake_db.paddle_events._docs.append(
        {"event_id": "evt_processed", "event_type": "subscription.activated", "status": "processed"}
    )
    body = json.dumps(
        {
            "event_id": "evt_processed",
            "event_type": "subscription.activated",
            "data": {
                "id": "sub_123",
                "customer_id": "cus_123",
                "next_billed_at": (datetime.now(timezone.utc) + timedelta(days=30)).isoformat(),
                "custom_data": {"user_id": _USER_ID},
            },
        }
    ).encode()
    activate_mock = AsyncMock()

    res = await _call(
        fake_db,
        "post",
        "/api/webhook/paddle",
        headers={"Paddle-Signature": _make_sig(_SECRET, str(int(time.time())), body)},
        patches=[
            patch.object(server, "PADDLE_WEBHOOK_SECRET", _SECRET),
            patch("subscription_manager.activate_premium", activate_mock),
        ],
    )

    assert res.status_code == 200, res.text
    assert res.json()["status"] == "duplicate"
    assert activate_mock.await_count == 0


async def test_failed_webhook_mutation_stays_retryable_and_unprocessed():
    fake_db = _FakeDB()
    event = {
        "event_id": "evt_retryable",
        "event_type": "subscription.activated",
        "data": {
            "id": "sub_123",
            "customer_id": "cus_123",
            "next_billed_at": (datetime.now(timezone.utc) + timedelta(days=30)).isoformat(),
            "custom_data": {"user_id": _USER_ID},
        },
    }
    body = json.dumps(event).encode()
    activate_mock = AsyncMock(side_effect=RuntimeError("db write failed"))

    res = await _call(
        fake_db,
        "post",
        "/api/webhook/paddle",
        headers={"Paddle-Signature": _make_sig(_SECRET, str(int(time.time())), body)},
        patches=[
            patch.object(server, "PADDLE_WEBHOOK_SECRET", _SECRET),
            patch("subscription_manager.activate_premium", activate_mock),
        ],
        raise_app_exceptions=False,
    )

    assert res.status_code == 500, res.text
    stored = await fake_db.paddle_events.find_one({"event_id": "evt_retryable"})
    assert stored is not None
    assert stored["status"] == "failed"
    assert "processed_at" not in stored


async def test_webhook_retry_replays_after_failure_then_marks_processed():
    fake_db = _FakeDB()
    event = {
        "event_id": "evt_retry_then_success",
        "event_type": "subscription.activated",
        "data": {
            "id": "sub_123",
            "customer_id": "cus_123",
            "next_billed_at": (datetime.now(timezone.utc) + timedelta(days=30)).isoformat(),
            "custom_data": {"user_id": _USER_ID},
        },
    }
    body = json.dumps(event).encode()
    sig = _make_sig(_SECRET, str(int(time.time())), body)
    activate_mock = AsyncMock(side_effect=[RuntimeError("first failure"), {"status": "premium"}])

    first = await _call(
        fake_db,
        "post",
        "/api/webhook/paddle",
        headers={"Paddle-Signature": sig},
        patches=[
            patch.object(server, "PADDLE_WEBHOOK_SECRET", _SECRET),
            patch("subscription_manager.activate_premium", activate_mock),
        ],
        raise_app_exceptions=False,
    )
    second = await _call(
        fake_db,
        "post",
        "/api/webhook/paddle",
        headers={"Paddle-Signature": sig},
        patches=[
            patch.object(server, "PADDLE_WEBHOOK_SECRET", _SECRET),
            patch("subscription_manager.activate_premium", activate_mock),
        ],
    )

    assert first.status_code == 500, first.text
    assert second.status_code == 200, second.text
    assert activate_mock.await_count == 2
    stored = await fake_db.paddle_events.find_one({"event_id": "evt_retry_then_success"})
    assert stored["status"] == "processed"
    assert stored.get("processed_at")


async def test_successful_webhook_marks_processed_after_business_mutation():
    fake_db = _FakeDB()
    event = {
        "event_id": "evt_success",
        "event_type": "subscription.activated",
        "data": {
            "id": "sub_123",
            "customer_id": "cus_123",
            "next_billed_at": (datetime.now(timezone.utc) + timedelta(days=30)).isoformat(),
            "custom_data": {"user_id": _USER_ID},
        },
    }
    body = json.dumps(event).encode()
    activate_mock = AsyncMock(return_value={"status": "premium"})

    res = await _call(
        fake_db,
        "post",
        "/api/webhook/paddle",
        headers={"Paddle-Signature": _make_sig(_SECRET, str(int(time.time())), body)},
        patches=[
            patch.object(server, "PADDLE_WEBHOOK_SECRET", _SECRET),
            patch("subscription_manager.activate_premium", activate_mock),
        ],
    )

    assert res.status_code == 200, res.text
    stored = await fake_db.paddle_events.find_one({"event_id": "evt_success"})
    assert activate_mock.await_count == 1
    assert stored["status"] == "processed"


async def test_transaction_completed_does_not_grant_premium_without_expiry():
    fake_db = _FakeDB()
    fake_db.payment_transactions._docs.append({"transaction_id": "txn_done", "status": "pending"})
    body = json.dumps(
        {
            "event_id": "evt_transaction_completed",
            "event_type": "transaction.completed",
            "data": {
                "id": "txn_done",
                "subscription_id": "sub_123",
                "customer_id": "cus_123",
                "custom_data": {"user_id": _USER_ID},
            },
        }
    ).encode()
    activate_mock = AsyncMock()

    res = await _call(
        fake_db,
        "post",
        "/api/webhook/paddle",
        headers={"Paddle-Signature": _make_sig(_SECRET, str(int(time.time())), body)},
        patches=[
            patch.object(server, "PADDLE_WEBHOOK_SECRET", _SECRET),
            patch("subscription_manager.activate_premium", activate_mock),
        ],
    )

    assert res.status_code == 200, res.text
    assert activate_mock.await_count == 0
    txn = await fake_db.payment_transactions.find_one({"transaction_id": "txn_done"})
    assert txn["status"] == "completed"
