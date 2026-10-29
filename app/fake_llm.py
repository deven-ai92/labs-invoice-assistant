"""
FakeLLM — a deterministic, offline stand-in for a real LLM.

WHY THIS EXISTS
---------------
This exercise is about everything *around* the model: prompt construction,
parsing untrusted model output, enforcing tenant scope, and returning an
honest no-answer. A real model is non-deterministic, costs money, and needs
credentials — none of which belong in a hiring exercise. So the "model" here
is a scripted fake whose outputs are realistic — including realistically
BROKEN in the ways real LLMs break (prose around JSON, markdown fences,
hallucinated columns, ignored instructions, malformed output).

You should NOT need to edit this file to complete parts 1–3. It is the fixed
"model" you build a robust pipeline around. In part 4 you may ADD one new
scripted case to extend the eval.

CONTRACT
--------
`FakeLLM.complete(prompt: str) -> str` returns the raw model text for a prompt.
It is a pure function of the prompt: the same prompt always returns the same
string. Routing is based on substrings the prompt is expected to contain (the
user's question text) — so if you change how you build the prompt, keep the
question text in it.
"""
from __future__ import annotations


class FakeLLM:
    """Deterministic scripted model. complete(prompt) -> raw text."""

    def complete(self, prompt: str) -> str:
        p = prompt.lower()

        # 1. CLEAN happy path — valid JSON, correct columns.
        if "overdue sysco invoices" in p:
            return '{"filters": [{"column": "vendor", "op": "=", "value": "Sysco"}, {"column": "status", "op": "=", "value": "overdue"}], "sort": {"column": "amount", "dir": "desc"}}'

        # 2. JSON wrapped in markdown fences + chatty prose (very common).
        if "total amount i owe" in p:
            return (
                "Sure! Here is the query you asked for:\n\n"
                "```json\n"
                '{"aggregate": {"fn": "sum", "column": "amount"}, '
                '"filters": [{"column": "status", "op": "!=", "value": "paid"}]}\n'
                "```\n"
                "Let me know if you'd like anything else!"
            )

        # 3. HALLUCINATED COLUMN — "vendor_name" is not in the schema (it is "vendor").
        if "who do i owe the most to" in p:
            return '{"aggregate": {"fn": "sum", "column": "amount"}, "group_by": "vendor_name", "sort": {"column": "amount", "dir": "desc"}}'

        # 4. IGNORES TENANT SCOPE — emits a filter on a DIFFERENT customer_id.
        #    The model was told to answer for the requesting customer only, and ignored it.
        if "biggest invoice" in p:
            return '{"filters": [{"column": "customer_id", "op": "=", "value": 2210}], "sort": {"column": "amount", "dir": "desc"}, "limit": 1}'

        # 5. MALFORMED — not valid JSON at all (truncated / broken).
        if "how many invoices are open" in p:
            return '{"aggregate": {"fn": "count" "filters": [{"column": "status", "op": "=", "value": "open"}'

        # 6. LOW CONFIDENCE / ambiguous — model hedges and returns no query.
        if "is this a good deal" in p:
            return '{"answer": null, "confidence": 0.2, "note": "The question is not answerable from invoice data."}'

        # Default: model shrugs.
        return '{"answer": null, "confidence": 0.0, "note": "unrecognized question"}'
