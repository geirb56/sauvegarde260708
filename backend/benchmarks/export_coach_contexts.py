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
    "email", "user_id", "username", "first_name", "last_name", "full_name", "display_name",
    "token", "access_token", "refresh_token", "api_key", "secret", "password",
    "lat", "lon", "lng", "latitude", "longitude", "polyline", "location", "city", "start_location",
    "garmin_user_id", "garmin_activity_id", "device", "device_name", "name", "title", "notes",
}
ID_KEYS = {"id", "workout_id", "activity_id", "session_id"}
UUID_RE = re.compile(r"\b[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\b")
LEAK_PATTERNS = {
    "email": re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}"),
    "url": re.compile(r"https?://", re.I),
    "api_key": re.compile(r"\bsk-[A-Za-z0-9_-]{16,}"),
    "long_hex": re.compile(r"\b[0-9a-fA-F]{24,}\b"),
    "uuid": UUID_RE,
}


class AnonymizationError(RuntimeError):
    pass


class Pseudonymizer:
    """Stable ids (w1, w2...) so cross-references between sessions stay consistent."""

    def __init__(self) -> None:
        self._map: dict[str, str] = {}

    def alias(self, raw: Any) -> str:
        key = str(raw)
        if key not in self._map:
            self._map[key] = f"w{len(self._map) + 1}"
        return self._map[key]

    def scrub_text(self, text: str) -> str:
        text = UUID_RE.sub(lambda m: self.alias(m.group(0)), text)
        for raw, alias in self._map.items():
            if raw in text:
                text = text.replace(raw, alias)
        return text


def anonymize(value: Any, pseudo: Pseudonymizer, parent_key: Optional[str] = None) -> Any:
    if isinstance(value, dict):
        out = {}
        for key, item in value.items():
            lowered = str(key).lower()
            if lowered in DROP_KEYS:
                continue
            if lowered in ID_KEYS or lowered.endswith("_id"):
                out[key] = pseudo.alias(item) if item is not None else None
            else:
                out[key] = anonymize(item, pseudo, lowered)
        return out
    if isinstance(value, list):
        return [anonymize(item, pseudo, parent_key) for item in value]
    if isinstance(value, str):
        return pseudo.scrub_text(value)
    return value


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
    contexts = anonymize(raw, Pseudonymizer())
    assert_no_leaks(contexts)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({"contexts": contexts}, ensure_ascii=False, indent=2), encoding="utf-8")
    out.chmod(0o600)
    print(f"Exported contexts: {', '.join(contexts)} -> {out.name} (anonymised; review before use).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
