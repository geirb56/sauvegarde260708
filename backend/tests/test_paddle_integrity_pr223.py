from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import os
import sys
import time
import types
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
from auth.mongo_errors import DuplicateKeyError  # noqa: E402
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
        self._docs = [dict(doc) for doc in (docs or [])]
        self.index_calls: list[dict[str, Any]] = []
        self._unique_indexes: set[str] = set()

    @staticmethod
    def _matches(doc: dict, query: dict) -> bool:
        return all(doc.get(k) == v for k, v in query.items() if not isinstance(v, dict))

    def _copy(self, doc: Optional[dict]) -> Optional[dict]:
        return None if doc is None else dict(doc)

    def _after_token(self):
        return getattr(server.ReturnDocument, "AFTER", object())

    def _check_uniques(self, candidate: dict, *, ignore: Optional[dict] = None) -> None:
        for field in self._unique_indexes:
            value = candidate.get(field)
            if value is None:
                continue
            for existing in self._docs:
                if existing is ignore:
                    continue
                if existing.get(field) == value:
                    raise DuplicateKeyError(f"duplicate key for {field}={value}")

    def _apply_update(self, doc: dict, update: dict, *, inserting: bool) -> None:
        for op, fields in update.items():
            if op == "$set":
                doc.update(fields)
            elif op == "$setOnInsert" and inserting:
                doc.update(fields)
            elif op == "$unset":
                for key in fields:
                    doc.pop(key, None)

    async def find_one(self, query: dict, projection: Optional[dict] = None) -> Optional[dict]:
        for doc in self._docs:
            if self._matches(doc, query):
                copy = dict(doc)
                if projection:
                    return {k: v for k, v in copy.items() if projection.get(k, 1)}
                return copy
        return None

    async def insert_one(self, doc: dict) -> None:
        new_doc = dict(doc)
        self._check_uniques(new_doc)
        self._docs.append(new_doc)

    async def update_one(self, query: dict, update: dict, upsert: bool = False) -> _UpdateResult:
        for doc in self._docs:
            if self._matches(doc, query):
                candidate = dict(doc)
                self._apply_update(candidate, update, inserting=False)
                self._check_uniques(candidate, ignore=doc)
                doc.clear()
                doc.update(candidate)
                return _UpdateResult()
        if upsert:
            new_doc = {k: v for k, v in query.items() if not isinstance(v, dict)}
            self._apply_update(new_doc, update, inserting=True)
            self._check_uniques(new_doc)
            self._docs.append(new_doc)
        return _UpdateResult()

    async def find_one_and_update(
        self,
        query: dict,
        update: dict,
        upsert: bool = False,
        return_document=None,
    ) -> Optional[dict]:
        for doc in self._docs:
            if self._matches(doc, query):
                before = dict(doc)
                candidate = dict(doc)
                self._apply_update(candidate, update, inserting=False)
                self._check_uniques(candidate, ignore=doc)
                doc.clear()
                doc.update(candidate)
                if return_document == self._after_token():
                    return self._copy(doc)
                return before

        if upsert:
            new_doc = {k: v for k, v in query.items() if not isinstance(v, dict)}
            self._apply_update(new_doc, update, inserting=True)
            self._check_uniques(new_doc)
            self._docs.append(new_doc)
            if return_document == self._after_token():
                return self._copy(new_doc)
            return None

        return None

    async def count_documents(self, query: dict) -> int:
        return sum(1 for doc in self._docs if self._matches(doc, query))

    async def create_index(self, key, **kwargs):
        self.index_calls.append({"key": key, **kwargs})
        if kwargs.get("unique") and isinstance(key, str):
            self._unique_indexes.add(key)
        return key


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
        self._calls.append({"url": url, "json": json, "headers": headers, "timeout": timeout})
        return self._response


def _bearer(user_id: str = _USER_ID, email: str = "pr223@example.com") -> dict:
    return {"Authorization": "Bearer " + create_access_token(user_id, email)}


def _override_user() -> dict:
    return {"id": _USER_ID, "email": "pr223@example.com", "authenticated": True}


def _make_sig(secret: str, ts: str, body: bytes) -> str:
    payload = f"{ts}:{body.decode('utf-8')}".encode("utf-8")
    digest = hmac.new(secret.encode("utf-8"), payload, hashlib.sha256).hexdigest()
    return f"ts={ts};h1={digest}"


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat()


def _event_body(
    *,
    event_id: str,
    event_type: str,
    occurred_at: Optional[datetime] = None,
    data: Optional[dict] = None,
) -> bytes:
    payload = {
        "event_id": event_id,
        "event_type": event_type,
        "occurred_at": _iso(occurred_at or datetime.now(timezone.utc)),
        "data": data or {},
    }
    return json.dumps(payload).encode()


def _subscription_data(
    *,
    status: Optional[str] = None,
    period_end: Optional[datetime] = None,
    next_billed_at: Optional[str] = None,
    scheduled_change: Optional[str] = None,
    subscription_id: str = "sub_123",
    customer_id: str = "cus_123",
    user_id: str = _USER_ID,
) -> dict:
    data: dict[str, Any] = {
        "id": subscription_id,
        "customer_id": customer_id,
        "custom_data": {"user_id": user_id},
    }
    if status is not None:
        data["status"] = status
    if period_end is not None:
        data["current_billing_period"] = {"ends_at": _iso(period_end)}
    if next_billed_at is not None:
        data["next_billed_at"] = next_billed_at
    if scheduled_change is not None:
        data["scheduled_change"] = scheduled_change
    return data


async def _call(
    fake_db: _FakeDB,
    method: str,
    path: str,
    *,
    headers: Optional[dict] = None,
    json_body: Optional[dict] = None,
    content: Optional[bytes] = None,
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
            transport=httpx.ASGITransport(app=server.app, raise_app_exceptions=raise_app_exceptions),
            base_url="http://test",
        ) as client:
            fn = getattr(client, method)
            kwargs: dict[str, Any] = {}
            if headers:
                kwargs["headers"] = headers
            if json_body is not None:
                kwargs["json"] = json_body
            if content is not None:
                kwargs["content"] = content
            return await fn(path, **kwargs)
    finally:
        server.app.dependency_overrides.clear()
        for item in reversed(started):
            item.stop()


async def _post_webhook(
    fake_db: _FakeDB,
    body: bytes,
    *,
    patches: Optional[list[Any]] = None,
    raise_app_exceptions: bool = True,
) -> httpx.Response:
    return await _call(
        fake_db,
        "post",
        "/api/webhook/paddle",
        headers={"Paddle-Signature": _make_sig(_SECRET, str(int(time.time())), body)},
        content=body,
        patches=[patch.object(server, "PADDLE_WEBHOOK_SECRET", _SECRET), *(patches or [])],
        raise_app_exceptions=raise_app_exceptions,
    )


def _seed_subscription(
    fake_db: _FakeDB,
    *,
    status: str = "premium",
    premium_expires_at: Optional[datetime] = None,
    paddle_last_event_at: Optional[datetime] = None,
    paddle_subscription_id: str = "sub_existing",
) -> None:
    doc: dict[str, Any] = {
        "user_id": _USER_ID,
        "status": status,
        "paddle_subscription_id": paddle_subscription_id,
    }
    if premium_expires_at is not None:
        doc["premium_expires_at"] = _iso(premium_expires_at)
    if paddle_last_event_at is not None:
        doc["paddle_last_event_at"] = _iso(paddle_last_event_at)
    fake_db.subscriptions._docs.append(doc)


async def test_checkout_uses_canonical_server_price_id():
    fake_db = _FakeDB()
    paddle_calls: list[dict] = []
    response = _FakePaddleResponse(201, {"data": {"id": "txn_123"}})

    res = await _call(
        fake_db,
        "post",
        "/api/subscription/paddle/checkout",
        headers=_bearer(),
        json_body={},
        patches=[
            patch.object(server, "PADDLE_API_KEY", "pdl_api_key"),
            patch.object(server, "PADDLE_PRICE_ID", "pri_server"),
            patch.object(server, "PADDLE_CLIENT_TOKEN", "client_token"),
            patch.object(server, "PADDLE_ENVIRONMENT", "sandbox"),
            patch.object(server.httpx, "AsyncClient", lambda *args, **kwargs: _FakePaddleClient(response, paddle_calls)),
        ],
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
    body = _event_body(
        event_id="evt_invalid_sig",
        event_type="subscription.activated",
        data=_subscription_data(period_end=datetime.now(timezone.utc) + timedelta(days=30)),
    )
    activate_mock = AsyncMock()

    res = await _call(
        fake_db,
        "post",
        "/api/webhook/paddle",
        headers={"Paddle-Signature": "ts=1;h1=bad"},
        content=body,
        patches=[
            patch.object(server, "PADDLE_WEBHOOK_SECRET", _SECRET),
            patch("subscription_manager.activate_premium", activate_mock),
        ],
        raise_app_exceptions=False,
    )

    assert res.status_code == 400, res.text
    assert activate_mock.await_count == 0
    assert await fake_db.paddle_events.count_documents({}) == 0


async def test_subscription_canceled_handler_executes_with_canonical_name():
    fake_db = _FakeDB()
    future = datetime.now(timezone.utc) + timedelta(days=10)
    _seed_subscription(fake_db, premium_expires_at=future + timedelta(days=10))
    body = _event_body(
        event_id="evt_canceled_name",
        event_type="subscription.canceled",
        occurred_at=datetime.now(timezone.utc),
        data=_subscription_data(period_end=future),
    )

    res = await _post_webhook(fake_db, body)

    assert res.status_code == 200, res.text
    subscription = await fake_db.subscriptions.find_one({"user_id": _USER_ID})
    assert subscription["status"] == "premium"
    assert subscription["premium_expires_at"] == _iso(future)
    assert subscription.get("cancelled_at") is not None


async def test_subscription_updated_status_canceled_applies_cancellation():
    fake_db = _FakeDB()
    _seed_subscription(fake_db, premium_expires_at=datetime.now(timezone.utc) + timedelta(days=30))
    past = datetime.now(timezone.utc) - timedelta(hours=1)
    body = _event_body(
        event_id="evt_updated_canceled",
        event_type="subscription.updated",
        occurred_at=datetime.now(timezone.utc),
        data=_subscription_data(status="canceled", period_end=past),
    )

    res = await _post_webhook(fake_db, body)

    assert res.status_code == 200, res.text
    subscription = await fake_db.subscriptions.find_one({"user_id": _USER_ID})
    assert subscription["status"] == "free"
    assert subscription["premium_expires_at"] == _iso(past)


async def test_activated_uses_current_billing_period_end():
    fake_db = _FakeDB()
    future = datetime.now(timezone.utc) + timedelta(days=30)
    body = _event_body(
        event_id="evt_activated_period_end",
        event_type="subscription.activated",
        occurred_at=datetime.now(timezone.utc),
        data=_subscription_data(period_end=future),
    )

    res = await _post_webhook(fake_db, body)

    assert res.status_code == 200, res.text
    subscription = await fake_db.subscriptions.find_one({"user_id": _USER_ID})
    assert subscription["status"] == "premium"
    assert subscription["premium_expires_at"] == _iso(future)
    assert subscription.get("paddle_last_event_at") is not None


async def test_updated_active_uses_current_billing_period_end():
    fake_db = _FakeDB()
    future = datetime.now(timezone.utc) + timedelta(days=45)
    body = _event_body(
        event_id="evt_updated_period_end",
        event_type="subscription.updated",
        occurred_at=datetime.now(timezone.utc),
        data=_subscription_data(status="active", period_end=future),
    )

    res = await _post_webhook(fake_db, body)

    assert res.status_code == 200, res.text
    subscription = await fake_db.subscriptions.find_one({"user_id": _USER_ID})
    assert subscription["status"] == "premium"
    assert subscription["premium_expires_at"] == _iso(future)


async def test_scheduled_cancel_with_null_next_billed_at_stays_premium_until_period_end():
    fake_db = _FakeDB()
    future = datetime.now(timezone.utc) + timedelta(days=12)
    body = _event_body(
        event_id="evt_scheduled_cancel",
        event_type="subscription.updated",
        occurred_at=datetime.now(timezone.utc),
        data=_subscription_data(
            status="active",
            period_end=future,
            next_billed_at=None,
            scheduled_change="cancel",
        ),
    )

    res = await _post_webhook(fake_db, body)

    assert res.status_code == 200, res.text
    subscription = await fake_db.subscriptions.find_one({"user_id": _USER_ID})
    assert subscription["status"] == "premium"
    assert subscription["premium_expires_at"] == _iso(future)


async def test_missing_current_period_end_fails_closed():
    fake_db = _FakeDB()
    body = _event_body(
        event_id="evt_missing_period_end",
        event_type="subscription.activated",
        occurred_at=datetime.now(timezone.utc),
        data=_subscription_data(),
    )

    res = await _post_webhook(fake_db, body, raise_app_exceptions=False)

    assert res.status_code == 500, res.text
    event_doc = await fake_db.paddle_events.find_one({"event_id": "evt_missing_period_end"})
    assert event_doc["status"] == "failed"
    assert "current_billing_period.ends_at" in event_doc["last_error"]


async def test_invalid_current_period_end_fails_closed():
    fake_db = _FakeDB()
    body = _event_body(
        event_id="evt_invalid_period_end",
        event_type="subscription.updated",
        occurred_at=datetime.now(timezone.utc),
        data={
            **_subscription_data(status="active"),
            "current_billing_period": {"ends_at": "not-a-date"},
        },
    )

    res = await _post_webhook(fake_db, body, raise_app_exceptions=False)

    assert res.status_code == 500, res.text
    event_doc = await fake_db.paddle_events.find_one({"event_id": "evt_invalid_period_end"})
    assert event_doc["status"] == "failed"


async def test_legacy_event_without_status_is_recovered_and_processed():
    fake_db = _FakeDB()
    fake_db.paddle_events._docs.append(
        {"event_id": "evt_legacy_no_status", "event_type": "subscription.activated"}
    )
    body = _event_body(
        event_id="evt_legacy_no_status",
        event_type="subscription.activated",
        occurred_at=datetime.now(timezone.utc),
        data=_subscription_data(period_end=datetime.now(timezone.utc) + timedelta(days=30)),
    )
    activate_mock = AsyncMock(return_value={"status": "premium"})

    res = await _post_webhook(
        fake_db,
        body,
        patches=[patch("subscription_manager.activate_premium", activate_mock)],
    )

    assert res.status_code == 200, res.text
    assert activate_mock.await_count == 1
    event_doc = await fake_db.paddle_events.find_one({"event_id": "evt_legacy_no_status"})
    assert event_doc["status"] == "processed"


async def test_processing_recent_claim_is_not_reclaimed():
    fake_db = _FakeDB()
    fake_db.paddle_events._docs.append(
        {
            "event_id": "evt_processing_recent",
            "event_type": "subscription.activated",
            "status": "processing",
            "claimed_at": datetime.now(timezone.utc).isoformat(),
        }
    )
    body = _event_body(
        event_id="evt_processing_recent",
        event_type="subscription.activated",
        occurred_at=datetime.now(timezone.utc),
        data=_subscription_data(period_end=datetime.now(timezone.utc) + timedelta(days=30)),
    )
    activate_mock = AsyncMock()

    res = await _post_webhook(
        fake_db,
        body,
        patches=[patch("subscription_manager.activate_premium", activate_mock)],
    )

    assert res.status_code == 200, res.text
    assert res.json()["status"] == "processing"
    assert activate_mock.await_count == 0


async def test_processing_stale_claim_is_reclaimed():
    fake_db = _FakeDB()
    stale_at = datetime.now(timezone.utc) - timedelta(seconds=server.PADDLE_EVENT_PROCESSING_LEASE_SECONDS + 5)
    fake_db.paddle_events._docs.append(
        {
            "event_id": "evt_processing_stale",
            "event_type": "subscription.activated",
            "status": "processing",
            "claimed_at": stale_at.isoformat(),
        }
    )
    body = _event_body(
        event_id="evt_processing_stale",
        event_type="subscription.activated",
        occurred_at=datetime.now(timezone.utc),
        data=_subscription_data(period_end=datetime.now(timezone.utc) + timedelta(days=30)),
    )
    activate_mock = AsyncMock(return_value={"status": "premium"})

    res = await _post_webhook(
        fake_db,
        body,
        patches=[patch("subscription_manager.activate_premium", activate_mock)],
    )

    assert res.status_code == 200, res.text
    assert activate_mock.await_count == 1
    event_doc = await fake_db.paddle_events.find_one({"event_id": "evt_processing_stale"})
    assert event_doc["status"] == "processed"


async def test_processing_invalid_claimed_at_is_reclaimed_fail_safe():
    fake_db = _FakeDB()
    fake_db.paddle_events._docs.append(
        {
            "event_id": "evt_processing_invalid_claimed_at",
            "event_type": "subscription.activated",
            "status": "processing",
            "claimed_at": "not-a-date",
        }
    )
    body = _event_body(
        event_id="evt_processing_invalid_claimed_at",
        event_type="subscription.activated",
        occurred_at=datetime.now(timezone.utc),
        data=_subscription_data(period_end=datetime.now(timezone.utc) + timedelta(days=30)),
    )
    activate_mock = AsyncMock(return_value={"status": "premium"})

    res = await _post_webhook(
        fake_db,
        body,
        patches=[patch("subscription_manager.activate_premium", activate_mock)],
    )

    assert res.status_code == 200, res.text
    assert activate_mock.await_count == 1


async def test_processing_missing_claimed_at_is_reclaimed_fail_safe():
    fake_db = _FakeDB()
    fake_db.paddle_events._docs.append(
        {
            "event_id": "evt_processing_missing_claimed_at",
            "event_type": "subscription.activated",
            "status": "processing",
        }
    )
    body = _event_body(
        event_id="evt_processing_missing_claimed_at",
        event_type="subscription.activated",
        occurred_at=datetime.now(timezone.utc),
        data=_subscription_data(period_end=datetime.now(timezone.utc) + timedelta(days=30)),
    )
    activate_mock = AsyncMock(return_value={"status": "premium"})

    res = await _post_webhook(
        fake_db,
        body,
        patches=[patch("subscription_manager.activate_premium", activate_mock)],
    )

    assert res.status_code == 200, res.text
    assert activate_mock.await_count == 1


async def test_two_simultaneous_deliveries_execute_mutation_once():
    fake_db = _FakeDB()
    release = asyncio.Event()
    entered = asyncio.Event()

    async def _activate(*args, **kwargs):
        entered.set()
        await release.wait()
        return {"status": "premium"}

    activate_mock = AsyncMock(side_effect=_activate)
    future = datetime.now(timezone.utc) + timedelta(days=30)
    body = _event_body(
        event_id="evt_concurrent_once",
        event_type="subscription.activated",
        occurred_at=datetime.now(timezone.utc),
        data=_subscription_data(period_end=future),
    )

    first_task = asyncio.create_task(
        _post_webhook(fake_db, body, patches=[patch("subscription_manager.activate_premium", activate_mock)])
    )
    await entered.wait()
    second_res = await _post_webhook(
        fake_db,
        body,
        patches=[patch("subscription_manager.activate_premium", activate_mock)],
    )
    release.set()
    first_res = await first_task

    assert first_res.status_code == 200, first_res.text
    assert second_res.status_code == 200, second_res.text
    assert second_res.json()["status"] == "processing"
    assert activate_mock.await_count == 1


async def test_two_simultaneous_stale_reclaims_execute_mutation_once():
    fake_db = _FakeDB()
    stale_at = datetime.now(timezone.utc) - timedelta(seconds=server.PADDLE_EVENT_PROCESSING_LEASE_SECONDS + 5)
    fake_db.paddle_events._docs.append(
        {
            "event_id": "evt_stale_reclaim_once",
            "event_type": "subscription.activated",
            "status": "processing",
            "claimed_at": stale_at.isoformat(),
        }
    )
    release = asyncio.Event()
    entered = asyncio.Event()

    async def _activate(*args, **kwargs):
        entered.set()
        await release.wait()
        return {"status": "premium"}

    activate_mock = AsyncMock(side_effect=_activate)
    body = _event_body(
        event_id="evt_stale_reclaim_once",
        event_type="subscription.activated",
        occurred_at=datetime.now(timezone.utc),
        data=_subscription_data(period_end=datetime.now(timezone.utc) + timedelta(days=30)),
    )

    first_task = asyncio.create_task(
        _post_webhook(fake_db, body, patches=[patch("subscription_manager.activate_premium", activate_mock)])
    )
    await entered.wait()
    second_res = await _post_webhook(
        fake_db,
        body,
        patches=[patch("subscription_manager.activate_premium", activate_mock)],
    )
    release.set()
    first_res = await first_task

    assert first_res.status_code == 200, first_res.text
    assert second_res.status_code == 200, second_res.text
    assert second_res.json()["status"] == "processing"
    assert activate_mock.await_count == 1


async def test_event_failed_can_be_retried_and_then_processed():
    fake_db = _FakeDB()
    body = _event_body(
        event_id="evt_retry_then_success",
        event_type="subscription.activated",
        occurred_at=datetime.now(timezone.utc),
        data=_subscription_data(period_end=datetime.now(timezone.utc) + timedelta(days=30)),
    )
    activate_mock = AsyncMock(side_effect=[RuntimeError("first failure"), {"status": "premium"}])

    first = await _post_webhook(
        fake_db,
        body,
        patches=[patch("subscription_manager.activate_premium", activate_mock)],
        raise_app_exceptions=False,
    )
    second = await _post_webhook(
        fake_db,
        body,
        patches=[patch("subscription_manager.activate_premium", activate_mock)],
    )

    assert first.status_code == 500, first.text
    assert second.status_code == 200, second.text
    assert activate_mock.await_count == 2
    event_doc = await fake_db.paddle_events.find_one({"event_id": "evt_retry_then_success"})
    assert event_doc["status"] == "processed"
    assert event_doc.get("processed_at") is not None


async def test_processed_event_replay_is_idempotent():
    fake_db = _FakeDB()
    fake_db.paddle_events._docs.append(
        {"event_id": "evt_processed_replay", "event_type": "subscription.activated", "status": "processed"}
    )
    body = _event_body(
        event_id="evt_processed_replay",
        event_type="subscription.activated",
        occurred_at=datetime.now(timezone.utc),
        data=_subscription_data(period_end=datetime.now(timezone.utc) + timedelta(days=30)),
    )
    activate_mock = AsyncMock()

    res = await _post_webhook(
        fake_db,
        body,
        patches=[patch("subscription_manager.activate_premium", activate_mock)],
    )

    assert res.status_code == 200, res.text
    assert res.json()["status"] == "duplicate"
    assert activate_mock.await_count == 0


async def test_updated_recent_then_activated_older_is_ignored():
    fake_db = _FakeDB()
    now = datetime.now(timezone.utc)
    newer_end = now + timedelta(days=40)
    older_end = now + timedelta(days=10)

    newer = _event_body(
        event_id="evt_newer_updated",
        event_type="subscription.updated",
        occurred_at=now,
        data=_subscription_data(status="active", period_end=newer_end, subscription_id="sub_newer"),
    )
    older = _event_body(
        event_id="evt_older_activated",
        event_type="subscription.activated",
        occurred_at=now - timedelta(days=1),
        data=_subscription_data(period_end=older_end, subscription_id="sub_older"),
    )

    first = await _post_webhook(fake_db, newer)
    second = await _post_webhook(fake_db, older)

    assert first.status_code == 200, first.text
    assert second.status_code == 200, second.text
    assert second.json()["status"] == "stale"
    subscription = await fake_db.subscriptions.find_one({"user_id": _USER_ID})
    assert subscription["paddle_subscription_id"] == "sub_newer"
    assert subscription["premium_expires_at"] == _iso(newer_end)


async def test_recent_canceled_prevents_older_active_reactivation():
    fake_db = _FakeDB()
    now = datetime.now(timezone.utc)
    _seed_subscription(fake_db, premium_expires_at=now + timedelta(days=30), paddle_last_event_at=now - timedelta(days=2))

    canceled = _event_body(
        event_id="evt_recent_canceled",
        event_type="subscription.canceled",
        occurred_at=now,
        data=_subscription_data(period_end=now - timedelta(hours=1)),
    )
    older_active = _event_body(
        event_id="evt_old_active",
        event_type="subscription.updated",
        occurred_at=now - timedelta(days=1),
        data=_subscription_data(status="active", period_end=now + timedelta(days=10)),
    )

    first = await _post_webhook(fake_db, canceled)
    second = await _post_webhook(fake_db, older_active)

    assert first.status_code == 200, first.text
    assert second.status_code == 200, second.text
    assert second.json()["status"] == "stale"
    subscription = await fake_db.subscriptions.find_one({"user_id": _USER_ID})
    assert subscription["status"] == "free"


async def test_newer_event_can_update_subscription_state_normally():
    fake_db = _FakeDB()
    now = datetime.now(timezone.utc)
    first_end = now + timedelta(days=7)
    second_end = now + timedelta(days=35)

    first = _event_body(
        event_id="evt_first_activated",
        event_type="subscription.activated",
        occurred_at=now - timedelta(days=1),
        data=_subscription_data(period_end=first_end, subscription_id="sub_first"),
    )
    second = _event_body(
        event_id="evt_second_updated",
        event_type="subscription.updated",
        occurred_at=now,
        data=_subscription_data(status="active", period_end=second_end, subscription_id="sub_second"),
    )

    first_res = await _post_webhook(fake_db, first)
    second_res = await _post_webhook(fake_db, second)

    assert first_res.status_code == 200, first_res.text
    assert second_res.status_code == 200, second_res.text
    subscription = await fake_db.subscriptions.find_one({"user_id": _USER_ID})
    assert subscription["paddle_subscription_id"] == "sub_second"
    assert subscription["premium_expires_at"] == _iso(second_end)


async def test_transaction_completed_does_not_grant_premium():
    fake_db = _FakeDB()
    fake_db.payment_transactions._docs.append({"transaction_id": "txn_done", "status": "pending"})
    body = _event_body(
        event_id="evt_transaction_completed",
        event_type="transaction.completed",
        occurred_at=datetime.now(timezone.utc),
        data={
            "id": "txn_done",
            "subscription_id": "sub_123",
            "customer_id": "cus_123",
            "custom_data": {"user_id": _USER_ID},
        },
    )
    activate_mock = AsyncMock()

    res = await _post_webhook(
        fake_db,
        body,
        patches=[patch("subscription_manager.activate_premium", activate_mock)],
    )

    assert res.status_code == 200, res.text
    assert activate_mock.await_count == 0
    assert await fake_db.subscriptions.find_one({"user_id": _USER_ID}) is None
    txn = await fake_db.payment_transactions.find_one({"transaction_id": "txn_done"})
    assert txn["status"] == "completed"


async def test_startup_uses_paddle_event_index_helper():
    fake_db = _FakeDB()
    fake_bootstrap = types.SimpleNamespace(bootstrap=lambda: None)
    ensure_paddle_index = AsyncMock()

    with patch.object(server, "db", fake_db), \
         patch.object(server, "_ensure_subscriptions_unique_index", AsyncMock()), \
         patch.object(server, "_ensure_paddle_events_unique_index", ensure_paddle_index), \
         patch.object(server, "validate_environment_configuration"), \
         patch.object(server, "validate_demo_mode_safety"), \
         patch.object(server, "log_demo_mode_status"), \
         patch.dict(sys.modules, {"garmin.bootstrap": fake_bootstrap}):
        await server.create_db_indexes()

    ensure_paddle_index.assert_awaited_once_with(fake_db)
