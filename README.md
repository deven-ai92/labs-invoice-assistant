# Labs — Engineering Exercise

Welcome, and thanks for taking the time. This is a small, self-contained exercise.
There is no hidden trick and no single "correct" solution — we are far more
interested in **how you reason about an AI-backed service** than in whether you
produce the cleverest line of code.

What we are measuring is diagnosing a specific broken system, making and defending
judgement calls, and proving your service is correct and safe. We will walk through
your submission with you afterwards, so be ready to explain every decision.

## Time

Please spend roughly **2 hours**. If you run out of time, stop and write down what
you would have done next — an honest "here's where I got to and here's my plan" is
worth more than a rushed, half-working submission.

## Setup

Python 3.9+ with `pipenv` (or plain `pip`):

```bash
pipenv install        # fastapi, uvicorn, pytest
# or: pip install fastapi uvicorn pytest
```

No API key, no network — the "model" is offline (see below).

## The scenario

You are building the backend of an **Invoice Query Assistant**. A customer asks a
question in plain English ("show me my overdue Sysco invoices"); a model turns that
into a small **JSON query spec**; your service runs it against the invoice data and
returns the answer.

This exercise uses **`FakeLLM`** (`app/fake_llm.py`): a deterministic, offline
stand-in for a real model that, for a given prompt, always returns the same text.
Its responses are **realistically broken**, in the ways real LLMs break: JSON
wrapped in markdown and prose, hallucinated column names, instructions ignored, and
malformed output.

Your job is to build a **robust, safe pipeline around a model you do not trust.**

For example, a query from customer 1049 might make the model emit a spec like
`{"customer_id": 2210, "columns": ["amount"]}` — pointing at a *different* customer.
If you pass that straight through, customer 1049 gets customer 2210's data back.
What should your pipeline do with output like this? That is the kind of question
this exercise is asking.

> ⚠️ **Multi-tenant data.** `data/invoices.json` holds invoices for several
> customers. A response to customer A must **never** contain customer B's data —
> no matter what the model returns. Treat this as a hard requirement.

## What you are handed

| Path | What it is |
| --- | --- |
| `app/main.py` | The prototype service. It runs, but trusts the model blindly. |
| `app/fake_llm.py` | The offline model. **Do not change it** for parts 1–3. |
| `data/invoices.json` | ~12 invoices across 3 customers, plus the schema. |
| `eval/run_eval.py` + `eval/golden.json` | An eval harness. It **runs and fails** — that is your starting point. |
| `tests/test_assistant.py` | Test stubs for you to complete. |

Run the eval first:

```bash
python eval/run_eval.py      # SCORE: 0/6 — expected
```

## Your tasks

### Part 1 — Diagnose the failures

Run the eval. For **each** failing case, explain in `NOTES.md` *why* it fails —
name the specific flaw, don't just rewrite around it. The failures fall into a few
distinct classes; identifying them precisely is the point of this part.

### Part 2 — Fix the service

Make `python eval/run_eval.py` report **6/6**. At minimum you will need to:

- **Parse the model's output robustly.** It does not return clean JSON — it comes
  wrapped in prose or markdown fences, and sometimes it is malformed. Extract the
  JSON query spec and **never let an exception escape**; a model returning junk is
  a routine outcome, not a crash.
- **Enforce tenant scope in code.** A response for customer A must only ever
  contain A's rows — regardless of what the model's spec says. Think about *where*
  this guarantee has to live.
- **Validate the model's spec.** Reject references to columns that are not in the
  schema instead of running them.
- **Return an explicit no-answer** for questions the service cannot answer (a
  hedging model, an un-fixable spec) — a distinguishable response, not a guess and
  not a 500.

> Examples — what each fix looks like:
> - *Parse messy output:* the model returns `Sure! Here is the query:` ```` ```json
>   {...} ``` ```` `Let me know if you need anything else!` — your code pulls out
>   just the `{...}` and ignores the chatter; output with no JSON at all fails
>   cleanly, not with a 500.
> - *Reject a hallucinated column:* model asks for `secret_margin` (not in the
>   schema) → explicit no-answer, not a crash.
> - *Enforce tenant scope in code:* model omits or spoofs `customer_id` → the
>   response still contains only the requesting customer's rows.
> - *Explicit no-answer:* `{"answer_kind": "no_answer", ...}` — a shape a caller
>   can detect, distinct from an empty result.

### Part 3 — Prove it with tests

Turn `tests/test_assistant.py` from stubs into real, passing tests. Prioritise a
**property** test, especially: *"across every customer and every question, a
response never contains another customer's invoice."* Add at least one adversarial
case of your own and explain in `NOTES.md` what it guards against.

## `NOTES.md`

Include a short `NOTES.md` with:

- your **diagnosis** of each failing case (Part 1),
- the **judgement calls** you made and why (e.g. how you decided to handle a
  hallucinated column, where you enforce tenant scope and why there),
- what you would do next with more time.

## Submitting

Zip the folder (or push to a private repo and share a link) including your `app/`,
`tests/`, and `NOTES.md`. **`NOTES.md` is required** — the written reasoning matters
as much as the code.

We will walk through your submission together in the follow-up session, so be ready
to talk us through every decision.

---
---

# Solution walkthrough (candidate section)

Result: `python eval/run_eval.py` → **6/6** (baseline 0/6). `pytest -q` → **243 passed**.
The reasoning behind each decision is in [`NOTES.md`](NOTES.md); this section explains
**how I got there, in the order I did it**.

## The approach in one paragraph

The model is an untrusted component, like user input from the internet. So I did not try to make
it behave; I built a pipeline in which **nothing it says can widen what the caller may see**.
Every stage either passes a *smaller, safer* thing to the next stage or ends in an explicit
`no_answer`. The tenant boundary is enforced by *which rows the engine is given*, not by a filter
applied to the spec.

```
 question (untrusted)         customer_id (trusted: caller's identity)
        │                                   │
        ▼                                   │
 build_prompt  ── schema + question only ───┼──► model (untrusted)
        │        (no rows, no tenant id)    │         │ raw text
        │                                   │         ▼
        │                          parsing.extract_json_object   ─► no_answer (no_json / malformed_json)
        │                                   │         │ dict
        │                                   │         ▼
        │                          query_spec.validate (allow-list) ─► no_answer (unknown_column, bad_value, no_query, ...)
        │                                   │         │ QuerySpec (typed, immutable; customer_id refs dropped)
        │                                   ▼         ▼
        └──────────────────────► repository.tenant_rows(customer_id) ──► only THIS customer's rows
                                            │
                                            ▼
                                   engine.execute(spec, rows) ──► {"answer_kind": "rows" | "aggregate"}
                      (any unexpected exception anywhere ──► no_answer, never a 500)
```

## Step by step (what I did, in order)

### Step 1 — Reproduce the baseline before touching code
Ran `python eval/run_eval.py` → `0/6`. Read `main.py`, `fake_llm.py`, `golden.json` and the data.
I worked out what each case *should* produce from the raw data first (e.g. customer 1049's unpaid
total is 4200 + 5600 + 320.75 + 1500 = 11620.75), so I could not be fooled by my own code later.

### Step 2 — Diagnose (Part 1)
Mapped the six failures to **three root causes** (full table in `NOTES.md` §1):

| Root cause | Cases | Meaning |
|---|---|---|
| A. No tenant scope in code | 1, 3, 4, 6 | `run_query` ran over *all* customers' invoices; even the clean happy path leaked |
| B. Model output trusted | 2, 5 | bare `json.loads`; prose, fences or truncation crashed the service |
| C. Spec never validated | 3, 6 | hedge `{"answer": null}` meant "select everything"; `group_by`/`sort` silently ignored |

I also found a flaw the eval does not test: the prototype pasted **every tenant's invoices into
the prompt**. That is a disclosure on its own with a hosted model.

### Step 3 — Decide the design principles before writing code
1. **Never trust the model for authorization.** Tenant identity comes from the caller only.
2. **Make the unsafe thing unrepresentable** instead of remembering to check for it.
3. **Allow-list, then reject.** An unknown key, operator or column is refused, never "skipped"
   (skipping silently returns *more* rows than asked for).
4. **Fail closed, and say so.** Every failure is an explicit `no_answer` with a stable reason code.
5. **Least privilege for the model.** It gets the schema and the question, nothing else.

### Step 4 — Tenant-scoped data access (`app/repository.py`) — fixes root cause A
`InvoiceStore` indexes invoices by customer once at load. Its only accessor is
`tenant_rows(customer_id)` (O(1)); there is no "all rows" method or module global (I removed the
prototype's `INVOICES`). The engine therefore cannot see another tenant's rows, in filters,
aggregates or group-bys. This is the answer to the brief's *"where does the guarantee live?"*:
in the data-access layer, keyed by the authenticated id.

### Step 5 — Lock down the prompt (`main.build_prompt`)
The prompt now contains the schema, the spec grammar and the question. No invoice rows, no tenant
id. It is built once, so its size no longer depends on the table size (cheaper and faster too).
The question text is kept verbatim because `FakeLLM` routes on it.

### Step 6 — Robust parsing (`app/parsing.py`) — fixes root cause B
A string-aware, brace-balanced scan finds top-level `{...}` spans; each is decoded strictly
(`NaN`/`Infinity` rejected). Prose and markdown fences are simply the text *outside* a span.
A truncated object never closes, so it yields nothing and fails cleanly instead of swallowing what
follows. Deliberate choices: **no greedy regex** (breaks on two objects or a stray `}`), and
**no JSON "repair"** (guessing what a truncated spec meant is a correctness risk; a retry is the
right tool, see `NOTES.md` §4). Only `ModelOutputError` can come out of this module.

### Step 7 — Spec validation (`app/query_spec.py`) — fixes root cause C
Turns the decoded dict into an immutable, typed `QuerySpec` or raises `SpecRejected`:
* allow-list for top-level keys, filter keys, operators, aggregate functions and sort shape;
* columns resolved against the schema (`secret_margin` → `unknown_column`); the only repair is a
  one-entry, reviewed alias table (`vendor_name → vendor`), **never fuzzy matching**;
* values type-checked per column (`bool` is not a number, real ISO dates, ordering operators only
  on numbers/dates), `limit` a positive int capped at 100;
* **any `customer_id` reference is dropped and recorded** (top-level key or filter, any operator,
  any casing), then logged as a `security:` warning;
* a spec with no query part (the hedge) is `no_query`, not "all rows".

### Step 8 — Execution engine (`app/engine.py`)
Pure and deterministic: filters, aggregates (`count/sum/avg/min/max`, `math.fsum`, cent-rounded),
`group_by`, sort, limit, column projection. Empty sets are handled (no `min([])` crash), ties are
broken deterministically, and returned rows are copies. It receives rows only, so it has no notion
of tenants and nothing to bypass.

### Step 9 — Orchestration and the no-answer contract (`app/main.py`)
`ask()` wires the stages and **never raises**: bad input, a failing model, a rejected spec and any
unexpected bug all end in `no_answer`. Before executing, it re-verifies that the repository returned
only the caller's rows and fails closed (CRITICAL log) if not. Model-generated text is logged, never
echoed back to the customer.

```
{"answer_kind": "rows",      "results": [...], "total_matches": n}
{"answer_kind": "aggregate", "value": ..., "groups": [...], "results": []}
{"answer_kind": "no_answer", "no_answer": true, "reason": "<code>", "message": "..."}
```
`no_answer` has no `results` key, so it cannot be confused with *"no invoices matched"*
(`answer_kind: "rows"`, `results: []`).

### Step 10 — Prove it (Part 3, `tests/test_assistant.py`)
* **Property test:** every customer (plus an unknown one) × every question; the *entire serialized
  response* is searched for another tenant's invoice id, not just `results`.
* **Adversarial replay:** 32 hostile model outputs × every customer (spoofed `customer_id` in every
  shape, hallucinated columns, unknown operators, `NaN`, `true` as a number, absurd limits,
  20,000-deep nesting, `null`, a non-string reply). Each rejection is asserted **for its reason**.
* **Independent oracle:** expected totals / biggest invoice / top vendor per customer are computed
  from `data/invoices.json`, never from app code.
* **Fail-closed tests:** a deliberately leaky repository and a crashing engine both end in `no_answer`.
* **Regression** for the prompt leak (no invoice data and no tenant id in the prompt).

### Step 11 — Test the tests (mutation check)
I injected 13 deliberate bugs (repository returns all rows, spoof filter honoured only for `=`,
hedge treated as select-all, `bool` accepted as a number, unknown operator skipped, fuzzy alias,
unstable ordering, invariant check removed, ...) and confirmed the suite fails on each. Two
initially survived because I was only asserting "no leak"; adding the *refused-for-the-right-reason*
tests fixed that.

## Module map

| File | Responsibility |
|---|---|
| `app/main.py` | Orchestration, prompt, no-answer shape, fail-closed wrapper (`ask`) |
| `app/repository.py` | Tenant-scoped data access (the tenant guarantee) |
| `app/parsing.py` | Untrusted text → one JSON object |
| `app/query_spec.py` | Allow-list validation → typed `QuerySpec` |
| `app/engine.py` | Executes a validated spec over one tenant's rows |
| `app/errors.py` | Typed outcomes (`Rejection`, `TenantInvariantError`) |
| `tests/test_assistant.py` | Property, adversarial, oracle, parsing, invariants |
| `NOTES.md` | Diagnosis, judgement calls, next steps |

`app/fake_llm.py`, `eval/golden.json` and `eval/run_eval.py` are unchanged.

## Judgement calls worth discussing

* **Spoofed `customer_id`:** ignore and answer for the caller (golden case 4 expects that), rather
  than reject. Safe because scope is applied independently.
* **Hallucinated column vs. case 3:** the README says reject, the golden answer is "Aramark". Resolved
  with one explicit alias, no fuzzy matching; flagged in `NOTES.md` as a spec tension.
* **Case 5** (answerable question, malformed output) is a `no_answer` because we do not guess; the
  real fix is a retry.
* **Public shape:** `ask(customer_id, question)` unchanged (plus optional `model=` for tests);
  `build_prompt(question)` dropped its `customer_id` parameter; `INVOICES`/`SCHEMA` globals removed.

## Run it

```bash
python -m venv .venv && source .venv/bin/activate     # Windows: .venv\Scripts\Activate.ps1
pip install fastapi uvicorn pytest
python eval/run_eval.py     # SCORE: 6/6 passed
pytest -q                   # 243 passed
```
This is a library-level service (`main.ask`); there is no HTTP layer in the exercise. In production
`customer_id` would come from the verified auth token, never from the request body (see `NOTES.md` §4).
