from __future__ import annotations

import inspect

import pytest


class _FakeIndexCollection:
    def __init__(self):
        self.create_index_calls = []

    async def create_index(self, keys, **kwargs):
        self.create_index_calls.append((keys, kwargs))
        return "uniq_user_prescription"


class _FakeIndexDB:
    def __init__(self):
        self.training_planned_prescription_memory = _FakeIndexCollection()


@pytest.mark.asyncio
async def test_ensure_training_planned_prescription_memory_unique_index_creates_expected_index():
    from services.training_planned_prescription_memory_index import (
        ensure_training_planned_prescription_memory_unique_index,
    )

    fake_db = _FakeIndexDB()
    await ensure_training_planned_prescription_memory_unique_index(fake_db)

    calls = fake_db.training_planned_prescription_memory.create_index_calls
    assert len(calls) == 1
    keys, kwargs = calls[0]
    assert keys == [("user_id", 1), ("prescription_id", 1)]
    assert kwargs.get("unique") is True


def test_create_db_indexes_wires_training_planned_prescription_memory_unique_index():
    import server

    source = inspect.getsource(server.create_db_indexes)
    assert "_ensure_training_planned_prescription_memory_unique_index(db)" in source

    week_source = inspect.getsource(server.get_training_v2_week)
    assert "training_planned_prescription_memory.create_index" not in week_source

