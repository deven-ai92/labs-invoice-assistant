# NOTES

`python eval/run_eval.py` → **6/6** (baseline 0/6). `pytest -q` → **243 passed**.
Step-by-step build order and architecture: see "Solution walkthrough" in `README.md`.

## 1. Diagnosis (Part 1)

The six failures reduce to three root causes. **A** is the serious one.

| # | Case | Eval said | Flaw |
|---|------|-----------|------|
| 1 | overdue Sysco invoices | tenant leak (2210) | **A. No tenant scope in code.** `run_query` filters the list of *all* customers' invoices, so even a clean spec leaks. The prompt tells the model who is asking and the code trusts it. |
| 2 | total amount I owe | `JSONDecodeError` | **B. Model output trusted.** Bare `json.loads` on prose + a markdown fence; the exception escapes (a 500). |
| 3 | who do I owe most | tenant leak (2210, 3300) | **A + C.** No scope, and the spec is never validated: the hallucinated `group_by: "vendor_name"` and the `sort` are silently ignored, so even a scoped answer would be a plain total. |
| 4 | my biggest invoice | tenant leak (2210) | **A, model-spoofed.** The model emits `customer_id = 2210` and the code executes it: scope delegated to the model's output. |
| 5 | how many invoices open | `JSONDecodeError` | **B.** Truncated JSON, same unguarded `json.loads`. |
| 6 | is this a good deal | tenant leak (2210, 3300) | **C. "Nothing to run" treated as "run everything".** The hedge `{"answer": null}` has no filters, so all 12 invoices come back. There was no no-answer path. |

Also found, not covered by the eval: the prototype pasted **every tenant's invoices into the prompt**
(a disclosure with a hosted model), and silently ignored unknown operators/keys (returns *more*
rows than asked for).

## 2. Judgement calls

* **Tenant scope is enforced in the data-access layer, by construction** (`repository.py`). The only
  accessor is `tenant_rows(customer_id)`; there is no "all rows" method. The engine only ever receives
  that customer's rows, so a spec cannot reach another tenant, in filters, aggregates or group-bys.
  I chose this over "validate the spec and strip `customer_id`" because a validation step can be
  forgotten or wrong, whereas here the unsafe operation cannot be expressed. `customer_id` comes from
  the caller's identity, never from the model. Defence in depth: the prompt carries no data and no
  tenant id, and `ask()` re-checks the repository's rows and fails closed.
* **Spoofed `customer_id`: ignore, don't reject.** Any reference (key or filter, any operator or
  casing) is dropped, logged as a `security:` warning and flagged in `warnings`. Case 4 expects the
  caller's own answer, and this is safe because scope is applied independently.
* **Hallucinated column: reject** (`secret_margin` → `no_answer: unknown_column`, nothing runs), with
  one exception: golden case 3 needs `vendor_name` to mean `vendor`. I used a one-entry, reviewed alias
  table and **no fuzzy matching** (`customer` ≈ `customer_id` is exactly where guessing is dangerous).
  The README ("reject") and the golden file are in tension here; I resolved it conservatively.
* **Validate everything, skip nothing.** Allow-list for keys, operators, aggregates and sort; values
  type-checked (`true` is not a number, `NaN` rejected, real ISO dates); `limit` capped at 100.
* **Parse, don't repair.** A string-aware balanced-brace scan, no greedy regex. Truncated JSON is a
  `no_answer`, not a guess; a retry is the right tool.
* **No-answer is distinct from empty.** `{"answer_kind": "no_answer", "no_answer": true, "reason": ...}`
  has no `results` key; "nothing matched" is `answer_kind: "rows"` with `results: []`. `ask()` never
  raises, and model text is never echoed to the customer.
* **Public shape:** `ask(customer_id, question)` unchanged (+ optional `model=` for tests);
  `build_prompt(question)` lost its `customer_id` parameter; `INVOICES`/`SCHEMA` globals removed on
  purpose. `fake_llm.py`, `golden.json`, `run_eval.py` untouched.

## 3. Tests: what they guard

* **Property:** every customer (plus an unknown one) × every question; the whole serialized response
  is searched for another tenant's invoice id.
* **Adversarial (my own):** 32 hostile model outputs replayed for every customer, e.g. `customer_id`
  spoofed as `=`, `in`, `!=`, odd casing, a top-level key, inside an aggregate or a fence;
  hallucinated columns; `NaN`; 20,000-deep nesting. Guards against a confused or compromised model
  steering the query at another tenant or crashing the service. Each rejection is asserted for its reason.
* **Oracle:** per-customer answers checked against values computed from the raw data file.
* **Mutation check:** 13 deliberate bugs injected, all caught (two initially survived, which showed I was
  asserting only "no leak"; fixed).

## 4. Next steps

1. **Retry once** on `malformed_json`/`no_json`. Case 5 is an answerable question lost to a flaky model.
2. **Semantic check of spec vs. question.** Case 3's spec has no `status != paid`, so "owe" includes paid
   invoices; Aramark wins either way but the number is wrong in general.
3. **HTTP layer** taking `customer_id` from the verified auth token, with rate limits and metrics per
   `reason` code and on the `security:` warning.
4. **Real-model hardening:** structured-output mode, a confidence threshold, a larger eval set.
5. **Postgres row-level security** as a second tenant barrier, plus a CI check that nothing outside
   `repository.py` can read all tenants.
6. More operators (`like`, date ranges), multi-column sort.
