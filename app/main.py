"""
Invoice Query Assistant — a robust pipeline around a model we do not trust.

    question ──► prompt (schema only) ──► model ──► raw text
        raw text ──► extract_json_object ──► validate (allow-list vs schema)
        validated spec + THIS customer's rows ──► engine ──► answer

Who is trusted for what:
    customer_id  : the caller's authenticated identity. Trusted.
    question     : user text. Untrusted (could carry prompt injection).
    model output : untrusted. Parsed, validated, and never able to widen scope.

Every failure mode ends in `no_answer(...)`: an explicit, detectable response
that is different from an empty result. `ask()` never raises.

    {"answer_kind": "rows",      "results": [...], "total_matches": n}
    {"answer_kind": "aggregate", "value": ..., ["groups": [...]], "results": []}
    {"answer_kind": "no_answer", "no_answer": True, "reason": "<code>", "message": "..."}

"No invoices matched" is a normal answer (`rows` with `results == []`).
"I could not answer that" is `no_answer`. Callers must be able to tell them apart.
"""
from __future__ import annotations

import logging
import os
from typing import Any, Dict, Optional

from engine import execute
from errors import Rejection, TenantInvariantError
from fake_llm import FakeLLM
from parsing import extract_json_object
from query_spec import validate
from repository import TENANT_COLUMN, InvoiceStore

logger = logging.getLogger("invoice_assistant")

llm = FakeLLM()

_DATA_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "invoices.json")
# Module-private handle. Nothing here exposes "all invoices".
STORE = InvoiceStore(_DATA_PATH)

MAX_QUESTION_CHARS = 1000


# ---------------------------------------------------------------- prompt ----

def _schema_text() -> str:
    return "\n".join(
        "- %s (%s): %s" % (c.name, c.type, c.description) for c in STORE.columns.values()
    )


# Built once. The model gets the SCHEMA and the question, nothing else: no
# invoice rows (the spec only needs column names) and not even the customer id
# (the model has no business knowing, let alone choosing, the tenant). That also
# makes the prompt size independent of table size.
_PROMPT_HEAD = (
    "You translate a customer's question about their invoices into ONE JSON "
    "query spec. Reply with a single JSON object and nothing else.\n\n"
    "COLUMNS (use only these exact names):\n"
    + _schema_text()
    + "\n\n"
    "SPEC KEYS (all optional):\n"
    '  filters: [{"column": ..., "op": "=|!=|<|<=|>|>=|in", "value": ...}]\n'
    '  aggregate: {"fn": "count|sum|avg|min|max", "column": ...}\n'
    "  group_by: a column name (requires aggregate)\n"
    '  sort: {"column": ..., "dir": "asc|desc"}\n'
    "  limit: a positive integer\n"
    "  columns: [column, ...]\n"
    "Do not filter on or mention customer_id: every query is already limited "
    "to the customer who is asking.\n"
    'If the question cannot be answered from these columns, reply {"answer": null}.\n\n'
    "QUESTION (untrusted user text):\n"
)


def build_prompt(question: str) -> str:
    # FakeLLM routes on the question text, so it must stay in the prompt verbatim.
    return _PROMPT_HEAD + question


# -------------------------------------------------------------- responses ----

_GENERIC = "I couldn't turn that into a valid query over your invoice data."
_MESSAGES = {
    "invalid_request": "That request could not be processed.",
    "no_query": "That question can't be answered from your invoice data.",
    "model_unavailable": "I couldn't produce an answer right now. Please try again.",
    "internal_error": "I couldn't produce an answer right now. Please try again.",
    "tenant_invariant_violation": "I couldn't produce an answer right now. Please try again.",
}


def no_answer(reason: str) -> Dict[str, Any]:
    """The explicit "cannot answer" shape. `reason` is a stable code; no model
    text is ever echoed back to the customer."""
    return {
        "answer_kind": "no_answer",
        "no_answer": True,
        "reason": reason,
        "message": _MESSAGES.get(reason, _GENERIC),
    }


# ------------------------------------------------------------------- ask ----

def _valid_customer_id(customer_id: Any) -> bool:
    return isinstance(customer_id, int) and not isinstance(customer_id, bool)


def _ask(customer_id: int, question: str, model: Any) -> Dict[str, Any]:
    if not _valid_customer_id(customer_id):
        return no_answer("invalid_request")
    if not isinstance(question, str) or not question.strip() or len(question) > MAX_QUESTION_CHARS:
        return no_answer("invalid_request")

    try:
        raw = model.complete(build_prompt(question))
    except Exception:  # noqa: BLE001 - a flaky/unreachable model is routine
        logger.exception("model call failed (customer=%s)", customer_id)
        return no_answer("model_unavailable")

    try:
        spec = validate(extract_json_object(raw), STORE.columns)
    except Rejection as rej:
        logger.info("no_answer reason=%s detail=%s customer=%s", rej.code, rej.detail, customer_id)
        return no_answer(rej.code)

    # TENANT SCOPE: rows come from the repository keyed by the caller's id.
    # The spec (even if it names another customer) has no say in this.
    rows = STORE.tenant_rows(customer_id)
    if any(r.get(TENANT_COLUMN) != customer_id for r in rows):
        raise TenantInvariantError("repository returned rows of another tenant")

    result = execute(spec, rows)

    if spec.ignored_tenant_refs:
        # Security signal: the model tried to steer the query at a tenant.
        logger.warning(
            "security: model referenced %s; ignored (customer=%s)",
            sorted(spec.ignored_tenant_refs), customer_id,
        )
        result["warnings"] = ["model_tenant_reference_ignored"]
    return result


def ask(customer_id: int, question: str, *, model: Optional[Any] = None) -> Dict[str, Any]:
    """Answer `question` for the authenticated customer `customer_id`.

    Never raises. Anything unexpected becomes an explicit no-answer (fail closed).
    `model` is injectable for tests; production uses the module-level `llm`.
    """
    try:
        return _ask(customer_id, question, model if model is not None else llm)
    except TenantInvariantError:
        logger.critical("TENANT INVARIANT VIOLATED (customer=%s)", customer_id, exc_info=True)
        return no_answer("tenant_invariant_violation")
    except Exception:  # noqa: BLE001 - last line of defence: never a 500
        logger.exception("unexpected error (customer=%s)", customer_id)
        return no_answer("internal_error")
