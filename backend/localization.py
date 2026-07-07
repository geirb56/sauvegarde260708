"""LLM-based localization for template-generated coach text.

The deterministic RAG/analysis engines produce English-only text (large template
banks). Rather than maintaining 3x translated template banks, we translate the
final short text fields into the user's language with a single cached GPT call.

Cheap & safe: skipped entirely for English; results cached in-memory by content
hash + language; any failure falls back to the original text (never blocks UI).
"""

from __future__ import annotations

import hashlib
import json
import logging

from llm_coach import _call_gpt, _LANG_NAMES

logger = logging.getLogger(__name__)

_CACHE: dict = {}
_CACHE_MAX = 2000


def _key(fields: dict, lang: str) -> tuple:
    blob = json.dumps(fields, sort_keys=True, ensure_ascii=False)
    return (hashlib.md5(blob.encode("utf-8")).hexdigest(), lang)


def _strip_fences(text: str) -> str:
    t = text.strip()
    if t.startswith("```"):
        t = t.strip("`")
        if t[:4].lower() == "json":
            t = t[4:]
    return t.strip()


async def localize_fields(fields: dict, language: str, user_id: str = "unknown") -> dict:
    """Translate the string values of `fields` into `language` (keys unchanged).

    Returns the original dict for English, empty input, cache miss failure, or
    any LLM error.
    """
    lang = (language or "fr").lower()
    if lang == "en" or not fields:
        return fields

    key = _key(fields, lang)
    if key in _CACHE:
        return _CACHE[key]

    name = _LANG_NAMES.get(lang, _LANG_NAMES["fr"])
    system = (
        f"You are a professional translator for a running-coach app. Translate "
        f"every string VALUE of the given JSON object into {name}. Keep the JSON "
        f"structure and keys IDENTICAL. Preserve all numbers, units, emojis and "
        f"line breaks. Output ONLY the translated JSON, nothing else."
    )
    prompt = json.dumps(fields, ensure_ascii=False)

    text, ok, _meta = await _call_gpt(system, prompt, user_id, "localize")
    if not ok or not text:
        return fields
    try:
        result = json.loads(_strip_fences(text))
        if not isinstance(result, dict):
            return fields
        # Only keep keys we asked for; fall back per-missing-key to the original.
        merged = {k: result.get(k, v) for k, v in fields.items()}
        if len(_CACHE) < _CACHE_MAX:
            _CACHE[key] = merged
        return merged
    except (ValueError, TypeError):
        logger.warning("[localize] could not parse LLM JSON, returning original")
        return fields
