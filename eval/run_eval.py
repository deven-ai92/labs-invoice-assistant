"""
Eval harness — runs the assistant over a set of golden questions and reports a
pass rate. Against the prototype you were handed, THIS WILL FAIL on several
cases. That is expected: the failures are your starting point for Part 2.

Run it:
    python eval/run_eval.py

Each golden case has:
    - customer_id, question
    - expect: a small spec describing what a CORRECT, SAFE answer looks like
              (see _check for the rules it enforces)

NOTE: this harness imports the app the same way the tests do. If you change the
app's public shape, update the import/adapter below — and say so in NOTES.md.
"""
from __future__ import annotations

import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "app"))

GOLDEN_PATH = os.path.join(os.path.dirname(__file__), "golden.json")


def _load_golden():
    with open(GOLDEN_PATH) as f:
        return json.load(f)


def _ask(customer_id: int, question: str):
    """Adapter around the app. Returns (ok, payload).

    ok=False means the app raised instead of answering — itself a finding.
    """
    import main  # imported late so a syntax error surfaces as a failed case

    try:
        return True, main.ask(customer_id=customer_id, question=question)
    except Exception as e:  # noqa: BLE001 - we want to record any crash
        return False, {"error": f"{type(e).__name__}: {e}"}


def _check(case, ok, payload) -> tuple[bool, str]:
    """Return (passed, reason). The rules a SAFE answer must satisfy."""
    if not ok:
        return False, f"app raised: {payload.get('error')}"

    expect = case["expect"]

    # Rule: the service must never return another customer's invoice.
    results = payload.get("results") or []
    if isinstance(results, list):
        leaked = [r for r in results if isinstance(r, dict)
                  and "customer_id" in r and r["customer_id"] != case["customer_id"]]
        if leaked:
            return False, f"tenant leak: returned rows for customer(s) {sorted({r['customer_id'] for r in leaked})}"

    # Rule: unanswerable questions must be an explicit no-answer, not a guess.
    if expect.get("kind") == "no_answer":
        if payload.get("answer_kind") == "no_answer" or payload.get("no_answer"):
            return True, "ok (explicit no-answer)"
        return False, "expected an explicit no-answer, got a result instead"

    # Rule: result row ids must match (order-insensitive) when expected.
    if "invoice_ids" in expect:
        got = sorted(r.get("invoice_id") for r in results if isinstance(r, dict))
        want = sorted(expect["invoice_ids"])
        if got == want:
            return True, "ok"
        return False, f"rows mismatch: got {got}, want {want}"

    # Rule: a numeric / scalar aggregate must match.
    if "value" in expect:
        if payload.get("value") == expect["value"]:
            return True, "ok"
        return False, f"value mismatch: got {payload.get('value')}, want {expect['value']}"

    return False, "no matching expectation rule (update the harness)"


def main_run() -> int:
    golden = _load_golden()
    passed = 0
    print(f"Running {len(golden)} golden cases\n" + "=" * 60)
    for case in golden:
        ok, payload = _ask(case["customer_id"], case["question"])
        good, reason = _check(case, ok, payload)
        passed += 1 if good else 0
        mark = "PASS" if good else "FAIL"
        print(f"[{mark}] #{case['id']:>2}  ({case['customer_id']}) {case['question']}")
        if not good:
            print(f"        -> {reason}")
    print("=" * 60)
    print(f"SCORE: {passed}/{len(golden)} passed")
    return 0 if passed == len(golden) else 1


if __name__ == "__main__":
    raise SystemExit(main_run())
