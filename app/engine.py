"""
Execute a VALIDATED `QuerySpec` over a list of rows.

The engine has no notion of tenants and no access to the store: it can only
ever see the rows it is handed, and `main.ask` hands it one customer's rows.
That is what makes the tenant guarantee structural rather than a filter that
someone could forget to apply.

Pure functions, deterministic output (ties are broken by data order, never by
hash order), and no input is mutated (returned rows are copies).
"""
from __future__ import annotations

import math
from typing import Any, Dict, List, Mapping, Sequence

from query_spec import (
    MAX_LIMIT,
    SORT_BY_GROUP_KEY,
    SORT_BY_VALUE,
    Aggregate,
    Filter,
    QuerySpec,
    fold,
)

Row = Mapping[str, Any]


def _matches(row: Row, f: Filter) -> bool:
    left = fold(row.get(f.column))
    if f.op == "=":
        return left == f.value
    if f.op == "!=":
        return left != f.value
    if f.op == "in":
        return left in f.value
    if left is None:
        return False
    if f.op == "<":
        return left < f.value
    if f.op == "<=":
        return left <= f.value
    if f.op == ">":
        return left > f.value
    return left >= f.value  # ">=" (validated upstream, so nothing else can reach here)


def _aggregate(agg: Aggregate, rows: Sequence[Row]) -> Any:
    if agg.fn == "count":
        return len(rows)
    vals = [r[agg.column] for r in rows]
    if agg.fn == "sum":
        return round(math.fsum(vals), 2)  # fsum: no float drift across many rows
    if not vals:
        return None  # avg/min/max of nothing is "no value", not 0 and not a crash
    if agg.fn == "avg":
        return round(math.fsum(vals) / len(vals), 2)
    return min(vals) if agg.fn == "min" else max(vals)


def _rows_answer(spec: QuerySpec, matched: List[Row]) -> Dict[str, Any]:
    ordered = matched
    if spec.sort is not None:
        col = spec.sort.target
        ordered = sorted(matched, key=lambda r: r[col], reverse=spec.sort.desc)
    page = ordered[: spec.limit or MAX_LIMIT]
    if spec.columns:
        results = [{c: r[c] for c in spec.columns} for r in page]
    else:
        results = [dict(r) for r in page]
    return {"answer_kind": "rows", "results": results, "total_matches": len(ordered)}


def _grouped_answer(spec: QuerySpec, agg: Aggregate, matched: List[Row]) -> Dict[str, Any]:
    buckets: Dict[Any, List[Row]] = {}
    for r in matched:
        buckets.setdefault(r[spec.group_by], []).append(r)
    groups = [{"key": k, "value": _aggregate(agg, rs)} for k, rs in buckets.items()]

    # Deterministic order: key ascending first, then a STABLE sort on the
    # requested target so equal values stay in key order.
    groups.sort(key=lambda g: g["key"])
    if spec.sort is not None:
        field = "key" if spec.sort.target == SORT_BY_GROUP_KEY else "value"
        groups.sort(key=lambda g: g[field], reverse=spec.sort.desc)
    groups = groups[: spec.limit or MAX_LIMIT]

    return {
        "answer_kind": "aggregate",
        "aggregate": {"fn": agg.fn, "column": agg.column},
        "group_by": spec.group_by,
        "groups": groups,
        # The leading group's key, i.e. the answer to "who/which ... most".
        # Only meaningful when the model asked for an ordering.
        "value": groups[0]["key"] if (spec.sort is not None and groups) else None,
        "results": [],
    }


def execute(spec: QuerySpec, rows: Sequence[Row]) -> Dict[str, Any]:
    matched = [r for r in rows if all(_matches(r, f) for f in spec.filters)]

    if spec.aggregate is None:
        return _rows_answer(spec, matched)
    if spec.group_by is not None:
        return _grouped_answer(spec, spec.aggregate, matched)
    return {
        "answer_kind": "aggregate",
        "aggregate": {"fn": spec.aggregate.fn, "column": spec.aggregate.column},
        "value": _aggregate(spec.aggregate, matched),
        "row_count": len(matched),
        "results": [],
    }
