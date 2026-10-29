"""
Extract ONE JSON object from raw, untrusted model text.

Real models wrap JSON in prose and markdown fences, emit truncated output, or
answer in plain English. All of that is expected, so this module:

  * never raises anything except `ModelOutputError`,
  * does not use a greedy regex like r"\\{.*\\}" (breaks on two objects, or on
    a stray "}" in the chatter),
  * does not try to "repair" broken JSON: guessing what a truncated spec meant
    is a correctness risk, and a retry is the right tool for that, not a guess.

Approach: scan for top-level, brace-balanced `{...}` spans. The scan is
string-aware, so a "}" inside a JSON string does not close the object. Each
span is then decoded strictly. Fences and prose are ignored automatically
because they are simply "text outside a span".
"""
from __future__ import annotations

import json
import logging
from typing import Any, Dict, Iterator, List, Tuple

from errors import ModelOutputError

logger = logging.getLogger("invoice_assistant.parsing")

# Bound the work done on adversarial / runaway output.
MAX_RAW_CHARS = 100_000


def _reject_constant(name: str) -> Any:
    # json.loads accepts NaN / Infinity by default; those are not valid JSON.
    raise ValueError("non-finite JSON constant: " + name)


_DECODER = json.JSONDecoder(parse_constant=_reject_constant)


def _top_level_spans(text: str) -> Iterator[Tuple[int, int]]:
    """Yield (start, end) of each balanced top-level {...} span, string-aware.

    An object that never closes (truncated output) yields nothing, so it fails
    cleanly instead of swallowing whatever follows it.
    """
    depth = 0
    start = -1
    in_string = False
    escaped = False
    for i, ch in enumerate(text):
        if in_string:
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == '"':
                in_string = False
        elif depth == 0:
            if ch == "{":
                depth = 1
                start = i
        else:
            if ch == '"':
                in_string = True
            elif ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    yield start, i + 1


def extract_json_object(raw: Any) -> Dict[str, Any]:
    """Return the first JSON object found in `raw`, or raise ModelOutputError."""
    if not isinstance(raw, str):
        raise ModelOutputError("malformed_json", "model output is not text")
    if len(raw) > MAX_RAW_CHARS:
        raise ModelOutputError("malformed_json", "model output too large")

    found: List[Dict[str, Any]] = []
    for start, end in _top_level_spans(raw):
        try:
            obj = _DECODER.decode(raw[start:end])
        except (ValueError, RecursionError):
            continue  # e.g. "{curly}" in the chatter, or invalid JSON
        if isinstance(obj, dict):
            found.append(obj)

    if not found:
        code = "malformed_json" if "{" in raw else "no_json"
        raise ModelOutputError(code, "no decodable JSON object in model output")
    if len(found) > 1:
        # Safety does not depend on which one we pick (tenant scope is applied
        # later regardless), but ambiguity is worth seeing in the logs.
        logger.warning("model output contained %d JSON objects; using the first", len(found))
    return found[0]
