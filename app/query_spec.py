"""
Validate the model's spec against the schema and turn it into a typed,
immutable `QuerySpec`.

Principle: the model's JSON is *untrusted input*, like a form field from the
internet. We allow-list what we understand and REJECT the rest. We never run a
spec "as best we can": silently ignoring an unknown key, operator or column is
how the prototype returned wrong (and cross-tenant) data.

Tenant handling: any reference to `customer_id` (top-level key or filter) is
DROPPED and recorded, never honoured. The requesting customer comes from the
caller's identity (see repository.py), not from the model.
"""
from __future__ import annotations

import math
import re
from dataclasses import dataclass
from datetime import date
from typing import Any, Dict, FrozenSet, List, Mapping, Optional, Set, Tuple

from errors import SpecRejected
from repository import TENANT_COLUMN, Column

QUERY_KEYS = frozenset({"filters", "aggregate", "group_by", "sort", "limit", "columns"})
# Keys a hedging model adds ("answer": null, "confidence": 0.2). Tolerated but
# never executed, and they alone do not make a runnable query.
METADATA_KEYS = frozenset({"answer", "confidence", "note"})
TENANT_KEYS = frozenset({TENANT_COLUMN})

ORDERING_OPS = frozenset({"<", "<=", ">", ">="})
FILTER_OPS = frozenset({"=", "!=", "in"}) | ORDERING_OPS
AGG_FNS = frozenset({"count", "sum", "avg", "min", "max"})
NUMERIC_TYPES = frozenset({"int", "float"})
ORDERABLE_TYPES = NUMERIC_TYPES | {"date"}

# The ONLY column "repair" we do: an explicit, reviewed alias table. We do not
# fuzzy-match names (e.g. "customer" ~ "customer_id" is exactly the kind of
# near-miss we must not guess about). Add entries here deliberately.
COLUMN_ALIASES: Mapping[str, str] = {"vendor_name": "vendor"}

MAX_LIMIT = 100       # hard cap on rows/groups returned per query
MAX_FILTERS = 20
MAX_IN_VALUES = 50
MAX_COLUMNS = 20

# In a grouped aggregate, `sort.column` can only mean one of these two things.
SORT_BY_GROUP_KEY = "key"
SORT_BY_VALUE = "value"

_ISO_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


@dataclass(frozen=True)
class Filter:
    column: str
    op: str
    value: Any  # already type-checked; strings folded; for "in" a frozenset


@dataclass(frozen=True)
class Aggregate:
    fn: str
    column: Optional[str]  # None only for count


@dataclass(frozen=True)
class Sort:
    # Rows mode: a column name. Grouped mode: SORT_BY_GROUP_KEY or SORT_BY_VALUE.
    target: str
    desc: bool


@dataclass(frozen=True)
class QuerySpec:
    filters: Tuple[Filter, ...]
    aggregate: Optional[Aggregate]
    group_by: Optional[str]
    sort: Optional[Sort]
    limit: Optional[int]
    columns: Optional[Tuple[str, ...]]
    # Audit trail of tenant references we refused to honour.
    ignored_tenant_refs: FrozenSet[str]


def fold(value: Any) -> Any:
    """Case/space-insensitive comparison form for strings; identity otherwise."""
    return value.strip().casefold() if isinstance(value, str) else value


def _clip(value: Any, n: int = 80) -> str:
    return repr(value)[:n]


def _resolve(name: Any, columns: Mapping[str, Column]) -> Column:
    if not isinstance(name, str):
        raise SpecRejected("bad_value", "column name is not a string: " + _clip(name))
    key = name.strip().lower()
    key = COLUMN_ALIASES.get(key, key)
    col = columns.get(key)
    if col is None:
        raise SpecRejected("unknown_column", _clip(name))
    return col


def _is_number(v: Any) -> bool:
    # bool is a subclass of int in Python: True must not pass as a number.
    return isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)


def _coerce(col: Column, value: Any) -> Any:
    """Type-check `value` against the column type; return its comparison form."""
    t = col.type
    ok = False
    if t == "string":
        ok = isinstance(value, str)
    elif t == "int":
        ok = isinstance(value, int) and not isinstance(value, bool)
    elif t == "float":
        ok = _is_number(value)
    elif t == "date":
        if isinstance(value, str) and _ISO_DATE.match(value):
            try:
                date.fromisoformat(value)
                ok = True
            except ValueError:
                ok = False
    else:
        raise SpecRejected("unsupported", "column type " + t)
    if not ok:
        raise SpecRejected("bad_value", "%s: %s" % (col.name, _clip(value)))
    return fold(value)


def _parse_filters(value: Any, columns: Mapping[str, Column], ignored: Set[str]) -> Tuple[Filter, ...]:
    if value is None:
        return ()
    if not isinstance(value, list):
        raise SpecRejected("malformed_spec", "filters must be a list")
    if len(value) > MAX_FILTERS:
        raise SpecRejected("malformed_spec", "too many filters")

    out: List[Filter] = []
    for f in value:
        if not isinstance(f, dict):
            raise SpecRejected("malformed_spec", "filter must be an object")
        extra = set(f) - {"column", "op", "value"}
        if extra:
            raise SpecRejected("unknown_key", "filter keys: " + _clip(sorted(extra)))
        if "column" not in f:
            raise SpecRejected("malformed_spec", "filter has no column")

        col = _resolve(f["column"], columns)
        if col.name == TENANT_COLUMN:
            # Whatever the model wanted here (=, !=, in; own id or someone
            # else's) is irrelevant: scope is applied by the repository.
            ignored.add("filter:" + TENANT_COLUMN)
            continue

        op = f.get("op", "=")
        op = op.strip().lower() if isinstance(op, str) else op
        if op not in FILTER_OPS:
            raise SpecRejected("bad_operator", _clip(f.get("op")))
        if "value" not in f:
            raise SpecRejected("malformed_spec", "filter has no value")
        if op in ORDERING_OPS and col.type not in ORDERABLE_TYPES:
            raise SpecRejected("bad_operator", "%s on %s column %s" % (op, col.type, col.name))

        v = f["value"]
        if op == "in":
            if not isinstance(v, list) or not v or len(v) > MAX_IN_VALUES:
                raise SpecRejected("bad_value", "'in' needs a short non-empty list")
            v = frozenset(_coerce(col, item) for item in v)
        else:
            v = _coerce(col, v)
        out.append(Filter(col.name, op, v))
    return tuple(out)


def _parse_aggregate(value: Any, columns: Mapping[str, Column]) -> Optional[Aggregate]:
    if value is None:
        return None
    if not isinstance(value, dict):
        raise SpecRejected("malformed_spec", "aggregate must be an object")
    extra = set(value) - {"fn", "column"}
    if extra:
        raise SpecRejected("unknown_key", "aggregate keys: " + _clip(sorted(extra)))

    fn = value.get("fn")
    fn = fn.strip().lower() if isinstance(fn, str) else fn
    if fn not in AGG_FNS:
        raise SpecRejected("unsupported", "aggregate fn " + _clip(value.get("fn")))

    if fn == "count":
        if value.get("column") is not None:
            _resolve(value["column"], columns)  # still reject hallucinated names
        return Aggregate("count", None)

    if value.get("column") is None:
        raise SpecRejected("malformed_spec", fn + " needs a column")
    col = _resolve(value["column"], columns)
    allowed = ORDERABLE_TYPES if fn in ("min", "max") else NUMERIC_TYPES
    if col.type not in allowed:
        raise SpecRejected("bad_value", "%s over %s column %s" % (fn, col.type, col.name))
    return Aggregate(fn, col.name)


def _parse_group_by(value: Any, columns: Mapping[str, Column]) -> Optional[str]:
    if value is None:
        return None
    if isinstance(value, list) and len(value) == 1:
        value = value[0]
    if not isinstance(value, str):
        raise SpecRejected("unsupported", "group_by must be a single column")
    return _resolve(value, columns).name


def _parse_sort(
    value: Any,
    columns: Mapping[str, Column],
    agg: Optional[Aggregate],
    group_by: Optional[str],
) -> Optional[Sort]:
    if value is None:
        return None
    if isinstance(value, list):
        raise SpecRejected("unsupported", "multi-column sort")
    if not isinstance(value, dict):
        raise SpecRejected("malformed_spec", "sort must be an object")
    extra = set(value) - {"column", "dir"}
    if extra:
        raise SpecRejected("unknown_key", "sort keys: " + _clip(sorted(extra)))
    if "column" not in value:
        raise SpecRejected("malformed_spec", "sort has no column")

    direction = value.get("dir", "asc")
    direction = direction.strip().lower() if isinstance(direction, str) else direction
    if direction not in ("asc", "desc"):
        raise SpecRejected("bad_value", "sort dir " + _clip(value.get("dir")))
    desc = direction == "desc"

    raw_col = value["column"]
    if agg is not None and group_by is not None:
        # Grouped result: the model sorts "by amount" meaning the aggregated
        # amount, so accept the group column or the aggregated column (or the
        # literal "value"); anything else is not a column of the result.
        if isinstance(raw_col, str) and raw_col.strip().lower() == SORT_BY_VALUE:
            return Sort(SORT_BY_VALUE, desc)
        col = _resolve(raw_col, columns)
        if col.name == group_by:
            return Sort(SORT_BY_GROUP_KEY, desc)
        if col.name == agg.column:
            return Sort(SORT_BY_VALUE, desc)
        raise SpecRejected("unsupported", "cannot sort grouped result by " + col.name)

    col = _resolve(raw_col, columns)  # validated even when it is then ignored
    if agg is not None:
        return None  # a scalar aggregate has nothing to sort
    return Sort(col.name, desc)


def _parse_limit(value: Any) -> Optional[int]:
    if value is None:
        return None
    if not isinstance(value, int) or isinstance(value, bool) or value < 1:
        raise SpecRejected("bad_value", "limit " + _clip(value))
    return min(value, MAX_LIMIT)


def _parse_columns(value: Any, columns: Mapping[str, Column]) -> Optional[Tuple[str, ...]]:
    if value is None:
        return None
    if not isinstance(value, list) or not value or len(value) > MAX_COLUMNS:
        raise SpecRejected("malformed_spec", "columns must be a short non-empty list")
    seen: Dict[str, None] = {}
    for name in value:
        seen[_resolve(name, columns).name] = None
    return tuple(seen)


def validate(raw: Mapping[str, Any], columns: Mapping[str, Column]) -> QuerySpec:
    """Validate a decoded model spec. Raises SpecRejected; returns a QuerySpec."""
    unknown = set(raw) - QUERY_KEYS - METADATA_KEYS - TENANT_KEYS
    if unknown:
        raise SpecRejected("unknown_key", _clip(sorted(unknown)))
    if not (set(raw) & QUERY_KEYS):
        # The hedge: {"answer": null, "confidence": 0.2, ...}. No query means
        # nothing to run. (The prototype treated "no filters" as "all rows".)
        raise SpecRejected("no_query", "model returned no query")

    ignored: Set[str] = set()
    if TENANT_COLUMN in raw:
        ignored.add("key:" + TENANT_COLUMN)

    filters = _parse_filters(raw.get("filters"), columns, ignored)
    agg = _parse_aggregate(raw.get("aggregate"), columns)
    group_by = _parse_group_by(raw.get("group_by"), columns)
    if group_by is not None and agg is None:
        raise SpecRejected("unsupported", "group_by without aggregate")
    sort = _parse_sort(raw.get("sort"), columns, agg, group_by)
    limit = _parse_limit(raw.get("limit"))
    cols = _parse_columns(raw.get("columns"), columns)
    if cols is not None and agg is not None:
        raise SpecRejected("unsupported", "columns together with aggregate")

    return QuerySpec(filters, agg, group_by, sort, limit, cols, frozenset(ignored))
