"""C427B - one-off, read-only export of anonymised Coach contexts for the model benchmark.

Run ONLY in an authorised, isolated environment (see docs/C427B_COACH_MODEL_BENCHMARK.md).
It performs MongoDB reads only, verifies the account identity, rebuilds the same LLM context
the chat endpoint sends (single-workout path, documented as read-only), anonymises it and
fails closed if any personal pattern remains. Output must be outside the repository.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

BACKEND_DIR = Path(__file__).resolve().parents[1]
REPO_ROOT = BACKEND_DIR.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

# Keys removed outright (identity, secrets, location, free text naming places/people).
DROP_KEYS = {
    "user_id", "username", "first_name", "last_name", "full_name", "display_name",
    "lat", "lon", "lng", "latitude", "longitude", "location", "city", "start_location",
    "garmin_user_id", "garmin_activity_id", "device", "device_name", "name", "title", "notes",
}
DROP_KEY_SUBSTRINGS = ("email", "token", "secret", "password", "api_key", "polyline")
UUID_RE = re.compile(r"\b[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\b")
# Complete identifier shapes only: UUID, Mongo ObjectId, Garmin-style numeric id (8+ digits).
FULL_ID_RE = re.compile(r"^(?:[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}"
                        r"|[0-9a-fA-F]{24}|\d{8,})$")
SMALL_INDEX_RE = re.compile(r"^\d{1,7}$")  # lap/split indexes under *_id keys: not identifying, kept as is
# A sport value never contains an 8+ digit run next to these separators, so they bound a whole token.
NUMBER_TOKEN_RE = re.compile(r"\d+(?::\d+)*(?:[.,]\d+)?")
LEAK_PATTERNS = {
    "email": re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}"),
    "url": re.compile(r"https?://|www\.", re.I),
    "api_key": re.compile(r"\bsk-[A-Za-z0-9_-]{16,}"),
    "long_hex": re.compile(r"\b[0-9a-fA-F]{24,}\b"),
    "uuid": UUID_RE,
    "long_number": re.compile(r"(?<![\d.,:/-])\d{9,}(?!\d)"),
    "gps_pair": re.compile(r"-?\d{1,3}\.\d{4,}\s*,\s*-?\d{1,3}\.\d{4,}"),
}


def _is_id_key(lowered: str) -> bool:
    return lowered == "id" or lowered.endswith("_id") or lowered.endswith("_ids")


class AnonymizationError(RuntimeError):
    pass


class Pseudonymizer:
    """Stable ids (w1, w2...) so cross-references between sessions stay consistent."""

    def __init__(self) -> None:
        self._map: dict[str, str] = {}
        self._regex: Optional[re.Pattern] = None

    def register(self, raw: Any) -> str:
        key = str(raw)
        if key not in self._map:
            self._map[key] = f"w{len(self._map) + 1}"
            self._regex = None
        return self._map[key]

    def alias(self, raw: Any) -> str:
        key = str(raw)
        if key not in self._map:
            raise AnonymizationError("identifier was not registered in the collection pass")
        return self._map[key]

    def scrub_text(self, text: str) -> str:
        """Replace only whole registered identifiers: never a digit run inside a pace, HR, date or distance."""
        if not self._map:
            return text
        if self._regex is None:
            ids = sorted(self._map, key=len, reverse=True)
            self._regex = re.compile(
                r"(?<![\w.:/+-])(?:" + "|".join(re.escape(i) for i in ids) + r")(?!\w|[.:/,+-]\d)")
        return self._regex.sub(lambda m: self._map[m.group(0)], text)


def _classify_id_value(value: Any) -> Optional[str]:
    """Return a string to alias, None for a harmless small index/null, or fail on anything ambiguous."""
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, str)):
        text = str(value)
        if FULL_ID_RE.match(text):
            return text
        if SMALL_INDEX_RE.match(text):
            return None
    raise AnonymizationError("unrecognised identifier format under an id key; refusing to guess")


def _iter_id_values(item: Any):
    if isinstance(item, list):
        for sub in item:
            yield from _iter_id_values(sub)
    elif not isinstance(item, dict):
        yield item


def collect_identifiers(value: Any, pseudo: Pseudonymizer) -> None:
    """Pass 1: register every complete identifier, in document order, before any text is rewritten."""
    if isinstance(value, dict):
        for key, item in value.items():
            lowered = str(key).lower()
            if _is_drop_key(lowered):
                continue
            if _is_id_key(lowered) and not isinstance(item, dict):
                for scalar in _iter_id_values(item):
                    found = _classify_id_value(scalar)
                    if found is not None:
                        pseudo.register(found)
            else:
                collect_identifiers(item, pseudo)
    elif isinstance(value, list):
        for item in value:
            collect_identifiers(item, pseudo)
    elif isinstance(value, str):
        for match in UUID_RE.finditer(value):
            pseudo.register(match.group(0))


def _is_drop_key(lowered: str) -> bool:
    return lowered in DROP_KEYS or any(part in lowered for part in DROP_KEY_SUBSTRINGS)


def _rewrite(value: Any, pseudo: Pseudonymizer) -> Any:
    if isinstance(value, dict):
        out = {}
        for key, item in value.items():
            lowered = str(key).lower()
            if _is_drop_key(lowered):
                continue
            if _is_id_key(lowered) and not isinstance(item, dict):
                if isinstance(item, list):
                    out[key] = [_alias_scalar(sub, pseudo) for sub in item]
                else:
                    out[key] = _alias_scalar(item, pseudo)
            else:
                out[key] = _rewrite(item, pseudo)
        return out
    if isinstance(value, list):
        return [_rewrite(item, pseudo) for item in value]
    if isinstance(value, str):
        return pseudo.scrub_text(value)
    return value


def _alias_scalar(value: Any, pseudo: Pseudonymizer) -> Any:
    if isinstance(value, (dict, list)):
        return _rewrite(value, pseudo)
    found = _classify_id_value(value)
    return value if found is None else pseudo.alias(found)


def anonymize(value: Any, pseudo: Optional[Pseudonymizer] = None) -> Any:
    pseudo = pseudo or Pseudonymizer()
    collect_identifiers(value, pseudo)
    return _rewrite(value, pseudo)


def _kept_leaves(value: Any, out: list) -> None:
    """Sport leaves that must survive anonymisation untouched, in document order."""
    if isinstance(value, dict):
        for key, item in value.items():
            lowered = str(key).lower()
            if _is_drop_key(lowered) or (_is_id_key(lowered) and not isinstance(item, dict)):
                continue
            _kept_leaves(item, out)
    elif isinstance(value, list):
        for item in value:
            _kept_leaves(item, out)
    else:
        out.append(value)


def verify_sport_data_preserved(raw: Any, clean: Any, pseudo: Pseudonymizer) -> None:
    """Gate: numbers/bools identical; in strings only registered identifiers may differ, every
    number-like token (paces 5:01, HR 148, distances, dates) must be unchanged."""
    before, after = [], []
    _kept_leaves(raw, before)
    _kept_leaves(clean, after)
    if len(before) != len(after):
        raise AnonymizationError("sport data count changed during anonymisation")
    for old, new in zip(before, after):
        if isinstance(old, str):
            if not isinstance(new, str) or new != pseudo.scrub_text(old):
                raise AnonymizationError("a text value changed beyond identifier replacement")
            if NUMBER_TOKEN_RE.findall(_without_raw_ids(old)) != NUMBER_TOKEN_RE.findall(
                    re.sub(r"\bw\d+\b", "", new)):
                raise AnonymizationError("a numeric token inside text changed")
        elif old != new or type(old) is not type(new):
            raise AnonymizationError("a numeric/boolean sport value changed")


def _without_raw_ids(text: str) -> str:
    """Independent of the pseudonymizer: drop UUIDs and 8+ digit runs before comparing number tokens."""
    return re.sub(r"(?<![\w.:/+-])\d{8,}(?!\w|[.:/,+-]\d)", "", UUID_RE.sub("", text))


def assert_no_leaks(payload: Any) -> None:
    """Fail closed: refuse to write a file that still looks personal."""
    text = json.dumps(payload, ensure_ascii=False)
    found = sorted(name for name, pattern in LEAK_PATTERNS.items() if pattern.search(text))
    if found:
        raise AnonymizationError(f"anonymisation incomplete, patterns still present: {', '.join(found)}")


def identity_matches(user_doc: Optional[dict], expected_email: str) -> bool:
    """Compare without logging or storing the email."""
    if not user_doc or not user_doc.get("email"):
        return False
    digest = lambda s: hashlib.sha256(s.strip().lower().encode()).hexdigest()  # noqa: E731
    return digest(str(user_doc["email"])) == digest(expected_email)


def parse_workouts(specs: list[str]) -> dict[str, str]:
    """KEY=WORKOUT_ID, KEY in {s0511, s0311}."""
    out = {}
    for spec in specs:
        key, _, workout_id = spec.partition("=")
        if key not in {"s0511", "s0311"} or not workout_id:
            raise SystemExit(f"invalid --workout '{key}': expected s0511=<id> or s0311=<id>")
        out[key] = workout_id
    return out


async def export_contexts(args: argparse.Namespace) -> dict[str, Any]:
    import server  # read-only use: only find/find_one paths below

    user = await server.db.users.find_one({"id": args.user_id}, {"_id": 0})
    if not identity_matches(user, args.expected_email):
        raise SystemExit("Identity check failed: user id and expected email do not match. Nothing exported.")
    _, allowed = await server._coach_access(args.user_id)
    if not allowed:
        raise SystemExit("Account is not entitled to workout analysis; the benchmark needs the Premium path.")

    now_utc = datetime.now(timezone.utc)
    raw: dict[str, Any] = {}
    for key, workout_id in parse_workouts(args.workout).items():
        selected = await server.load_scoped_workout_analysis_v2(
            db=server.db, user_id=args.user_id, workout_id=workout_id, language="fr")
        if selected is None:
            raise SystemExit(f"Workout for {key} not found for this account. Nothing exported.")
        workout, analysis = selected
        context, _ = await server._build_coach_llm_context(
            user=user, language="fr", workout=workout, workout_analysis=analysis,
            workout_analysis_allowed=True, workout_id=workout_id, now_utc=now_utc)
        raw[key] = context

    if args.comparison_message:
        turn = await server._resolve_coach_activity_turn(
            user_id=args.user_id, message=args.comparison_message, language="fr", now_utc=now_utc,
            analysis_allowed=True, scope_workout_id=None)
        if turn.get("kind") != "compare":
            raise SystemExit("The comparison message did not resolve to a two-session comparison.")
        raw["comparison"] = server.coach_session_comment.build_comparison_chat_context(turn, "fr")
    return raw


def main(argv: Optional[list[str]] = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--user-id", required=True)
    p.add_argument("--expected-email", default=os.environ.get("C427B_EXPECTED_EMAIL", ""),
                   help="or env C427B_EXPECTED_EMAIL; used only for the identity check")
    p.add_argument("--workout", action="append", default=[], metavar="s0511=ID|s0311=ID")
    p.add_argument("--comparison-message", default=None,
                   help="a chat message that designates the two sessions (resolved read-only)")
    p.add_argument("--out", required=True, type=Path)
    args = p.parse_args(argv)

    out = args.out.expanduser().resolve()
    if out == REPO_ROOT or REPO_ROOT in out.parents:
        raise SystemExit("--out must be outside the repository.")
    if not args.expected_email:
        raise SystemExit("--expected-email (or C427B_EXPECTED_EMAIL) is required for the identity check.")
    if not args.workout:
        raise SystemExit("At least one --workout is required.")

    raw = asyncio.run(export_contexts(args))
    pseudo = Pseudonymizer()
    try:
        contexts = anonymize(raw, pseudo)
        verify_sport_data_preserved(raw, contexts, pseudo)
        assert_no_leaks(contexts)
    except AnonymizationError as exc:
        raise SystemExit(f"Export refused, nothing written: {exc}")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({"contexts": contexts}, ensure_ascii=False, indent=2), encoding="utf-8")
    out.chmod(0o600)
    print(f"Exported contexts: {', '.join(contexts)} -> {out.name} (anonymised; review before use).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
