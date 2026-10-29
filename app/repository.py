"""
Tenant-scoped data access.

THIS is where the multi-tenant guarantee lives. Design rule:

    The only way to read invoices is `tenant_rows(customer_id)`.
    There is no method, attribute or module global that returns every
    tenant's rows.

So the query engine (engine.py) is *structurally* unable to see another
customer's data: it only ever receives the rows of the already-authenticated
customer. The model's spec can say anything it likes about customer_id; by the
time it is executed, the other tenants' rows are simply not in memory scope.

`customer_id` must come from the caller's authenticated identity, never from
the model and never from the question text.
"""
from __future__ import annotations

import json
from collections import defaultdict
from dataclasses import dataclass
from typing import Any, Dict, List, Mapping, Tuple

TENANT_COLUMN = "customer_id"


@dataclass(frozen=True)
class Column:
    name: str
    type: str  # "string" | "int" | "float" | "date"
    description: str


class InvoiceStore:
    """Read-only invoice store, indexed by tenant once at load time."""

    def __init__(self, path: str) -> None:
        with open(path, encoding="utf-8") as f:
            db = json.load(f)

        self.columns: Dict[str, Column] = {
            c["name"]: Column(c["name"], c["type"], c.get("description", ""))
            for c in db["schema"]["columns"]
        }
        if TENANT_COLUMN not in self.columns:
            raise ValueError("schema has no tenant column '%s'" % TENANT_COLUMN)

        by_tenant: Dict[Any, List[Mapping[str, Any]]] = defaultdict(list)
        for row in db["invoices"]:
            by_tenant[row[TENANT_COLUMN]].append(row)
        # Private on purpose. Do not add an "all rows" accessor.
        self._by_tenant: Dict[Any, Tuple[Mapping[str, Any], ...]] = {
            k: tuple(v) for k, v in by_tenant.items()
        }

    def tenant_rows(self, customer_id: int) -> Tuple[Mapping[str, Any], ...]:
        """Rows owned by `customer_id`. O(1) lookup, no table scan.

        Unknown customers get an empty tuple (not an error), so the response
        does not reveal whether a customer id exists.
        """
        return self._by_tenant.get(customer_id, ())
