"""
Typed outcomes for the pipeline.

A model producing junk is a ROUTINE event, so it is modelled as a normal,
typed `Rejection` that `main.ask` turns into an explicit no-answer. It is never
allowed to surface as a 500.

`TenantInvariantError` is deliberately NOT a `Rejection`: it means our own
tenant guarantee was violated (a bug), which is a different severity from
"the model said something unusable", and is logged at CRITICAL.
"""
from __future__ import annotations


class Rejection(Exception):
    """An expected "cannot answer this" outcome.

    `code`   stable, machine-readable reason, safe to return to the caller.
    `detail` free text for SERVER LOGS ONLY. It can contain model-generated
             text, so it is never echoed back to the customer.
    """

    def __init__(self, code: str, detail: str = "") -> None:
        super().__init__(f"{code}: {detail}" if detail else code)
        self.code = code
        self.detail = detail


class ModelOutputError(Rejection):
    """The raw model text did not contain a usable JSON object."""


class SpecRejected(Rejection):
    """The JSON parsed, but it is not a query spec we are willing to run."""


class TenantInvariantError(RuntimeError):
    """Rows that do not belong to the requesting customer reached the pipeline."""
