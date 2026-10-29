"""
Invoice Query Assistant — PROTOTYPE (your starting point).

This service runs. It even answers the simplest question. But it trusts the
model completely: it runs whatever query spec the model returns, as-is. Your
job is to make it robust and safe. See README.md for the four things that are
wrong and what to do about them.

Start the eval to see where it stands:
    python eval/run_eval.py
"""
from __future__ import annotations

import json
import os
from typing import Any, Dict, List

from fake_llm import FakeLLM

llm = FakeLLM()

_DATA_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "invoices.json")
with open(_DATA_PATH) as f:
    _DB = json.load(f)
INVOICES: List[Dict[str, Any]] = _DB["invoices"]
SCHEMA = _DB["schema"]


def build_prompt(customer_id: int, question: str) -> str:
    # Note: we tell the model which customer is asking and trust it to scope.
    return (
        "You are an invoice assistant. The customer asking is "
        f"{customer_id}. Translate the question into a JSON query spec over the "
        "invoice data.\n"
        f"DATA: {json.dumps(INVOICES)}\n"
        f"QUESTION: {question}\n"
    )


def run_query(spec: Dict[str, Any]) -> Dict[str, Any]:
    """Run the model's spec directly against ALL invoices."""
    rows = INVOICES
    for flt in spec.get("filters", []):
        col, op, val = flt["column"], flt.get("op", "="), flt["value"]
        if op == "=":
            rows = [r for r in rows if r.get(col) == val]
        elif op == "!=":
            rows = [r for r in rows if r.get(col) != val]

    agg = spec.get("aggregate")
    if agg:
        fn = agg["fn"]
        if fn == "count":
            return {"results": rows, "value": len(rows)}
        col = agg["column"]
        vals = [r[col] for r in rows]
        return {"results": rows, "value": {"sum": sum(vals), "min": min(vals), "max": max(vals)}[fn]}

    if spec.get("sort"):
        s = spec["sort"]
        rows = sorted(rows, key=lambda r: r[s["column"]], reverse=(s.get("dir") == "desc"))
    if spec.get("limit"):
        rows = rows[: spec["limit"]]
    return {"results": rows}


def ask(customer_id: int, question: str) -> Dict[str, Any]:
    prompt = build_prompt(customer_id, question)
    raw = llm.complete(prompt)
    spec = json.loads(raw)          # trusts the model's output is clean JSON
    return run_query(spec)          # runs it against everything
