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
