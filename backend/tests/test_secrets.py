"""Tests for config.secrets.get_secret (env-only, fail-fast)."""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config.secrets import get_secret, MissingSecretError  # noqa: E402


def _ok(m): print(f"  ✅ {m}", flush=True)
def _fail(m):
    print(f"  ❌ {m}", flush=True)
    raise AssertionError(m)


def test_present():
    os.environ["TEST_SECRET_X"] = "value123"
    if get_secret("TEST_SECRET_X") != "value123":
        _fail("should return the env value")
    if get_secret("TEST_SECRET_X", required=True) != "value123":
        _fail("required=True should return the value when present")
    _ok("returns env value (optional + required)")
    del os.environ["TEST_SECRET_X"]


def test_missing_optional():
    os.environ.pop("TEST_SECRET_MISSING", None)
    if get_secret("TEST_SECRET_MISSING") is not None:
        _fail("missing optional should be None")
    if get_secret("TEST_SECRET_MISSING", default="d") != "d":
        _fail("should return provided default")
    _ok("missing optional -> default")


def test_empty_treated_as_missing():
    os.environ["TEST_SECRET_EMPTY"] = ""
    if get_secret("TEST_SECRET_EMPTY", default="d") != "d":
        _fail("empty string should be treated as missing")
    try:
        get_secret("TEST_SECRET_EMPTY", required=True)
        _fail("empty + required should raise")
    except MissingSecretError:
        pass
    _ok("empty string treated as missing")
    del os.environ["TEST_SECRET_EMPTY"]


def test_required_missing_raises():
    os.environ.pop("TEST_SECRET_REQ", None)
    try:
        get_secret("TEST_SECRET_REQ", required=True)
        _fail("required missing should raise MissingSecretError")
    except MissingSecretError as exc:
        if "TEST_SECRET_REQ" not in str(exc):
            _fail("error message must name the missing secret")
    _ok("required missing -> MissingSecretError with clear message")


def main() -> int:
    print("config.secrets tests", flush=True)
    failed = 0
    for t in (test_present, test_missing_optional, test_empty_treated_as_missing,
              test_required_missing_raises):
        try:
            t()
        except AssertionError:
            failed += 1
    print(f"\nRESULT: {'ALL PASSED ✅' if failed == 0 else f'{failed} FAILED ❌'}", flush=True)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
