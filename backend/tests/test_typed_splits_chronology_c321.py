"""Synthetic chronology evidence; these rows are not Garmin captures."""

import pytest

from garmin.data_layer import normalize_typed_splits


@pytest.mark.parametrize("evidence,expected", [
    ([{"startTimeGMT": "2026-10-01T10:02:00Z"},
      {"startTimeGMT": "2026-10-01T12:00:00+02:00"},
      {"startTimeGMT": "2026-10-01T10:01:00"}], [1, 2, 0]),
    ([{"messageIndex": 9}, {"messageIndex": 3}, {"messageIndex": 6}], [1, 2, 0]),
    ([{"messageIndex": 2, "startTimeGMT": "2026-10-01T10:02:00Z"},
      {"messageIndex": 0, "startTimeGMT": "2026-10-01T10:00:00Z"},
      {"messageIndex": 1}], [1, 2, 0]),
    ([{"startTimeGMT": "2026-10-01T10:02:00Z"}, {},
      {"startTimeGMT": "2026-10-01T10:00:00Z"}], [0, 1, 2]),
    ([{"messageIndex": 2}, {}, {"messageIndex": 0}], [0, 1, 2]),
    ([{"messageIndex": 2}, {"messageIndex": 2}, {"messageIndex": 0}], [0, 1, 2]),
    ([{"messageIndex": 2, "startTimeGMT": "2026-10-01T10:02:00Z"},
      {"messageIndex": 2, "startTimeGMT": "2026-10-01T10:01:00Z"},
      {"messageIndex": 0, "startTimeGMT": "2026-10-01T10:00:00Z"}], [2, 1, 0]),
    ([{"messageIndex": 0, "startTimeGMT": "2026-10-01T10:02:00Z"},
      {"messageIndex": 2, "startTimeGMT": "2026-10-01T10:00:00Z"},
      {"messageIndex": 1}], [0, 1, 2]),
    ([{"startTimeGMT": "invalid"}, {},
      {"startTimeGMT": "2026-10-01T10:00:00Z"}], [0, 1, 2]),
    ([{"startTimeGMT": "2026-10-01"}, {},
      {"startTimeGMT": "2026-10-01T10:00:00Z"}], [0, 1, 2]),
    ([{"messageIndex": True}, {"messageIndex": "0"}, {"messageIndex": -1}], [0, 1, 2]),
    ([{"startTimeGMT": "2026-10-01T10:00:00Z"},
      {"startTimeGMT": "2026-10-01T10:00:00Z"},
      {"startTimeGMT": "2026-10-01T09:00:00Z"}], [2, 0, 1]),
    ([{}, {}, {}], [0, 1, 2]),
])
def test_global_chronology_is_coherent_stable_and_not_reconstructed(evidence, expected):
    rows = [{"type": "INTERVAL_ACTIVE", "distance": i, **item}
            for i, item in enumerate(evidence)]
    # Neither a lap index nor a duration establishes a phase's position.
    for i, row in enumerate(rows):
        row.update({"lapIndexes": [100 - i], "duration": 100 - i})
    phases = normalize_typed_splits({"splits": rows})
    assert [phase["distance_m"] for phase in phases] == expected
    assert [phase["order"] for phase in phases] == [0, 1, 2]
    assert normalize_typed_splits({"splits": rows}) == phases


@pytest.mark.parametrize("native_type", ["RWD_RUN", "RWD_WALK", "RWD_STAND", "RWD_UNKNOWN"])
def test_rwd_family_between_intervals_cannot_change_retained_order(native_type):
    rows = [
        {"type": "INTERVAL_ACTIVE", "messageIndex": 0, "duration": 240},
        {"type": native_type, "messageIndex": 0, "startTimeGMT": "invalid"},
        {"type": "INTERVAL_RECOVERY", "messageIndex": 1, "duration": 180},
        {"type": "INTERVAL_ACTIVE", "messageIndex": 2, "duration": 240},
    ]
    expected = normalize_typed_splits({"splits": [rows[0], *rows[2:]]})
    assert normalize_typed_splits({"splits": rows}) == expected
    assert [phase["phase_type"] for phase in expected] == ["effort", "recovery", "effort"]
