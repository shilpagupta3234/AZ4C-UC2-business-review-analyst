"""Data analyst: computes every figure the question needs, through tools only.

Metric SQL comes from the registry compiler, never from a model. Each
figure becomes a fact with a stable id, a full label (metric, scope and
period, RS1), its value at full precision, and the queries behind it.
"""

from collections.abc import Callable

from ..semantic import calendar as cal
from ..semantic.compiler import NotAvailable
from ..semantic.metrics import METRICS
from ..tools.metrics import compute_metric
from ..tools.names import display_names
from ..tools.sql import SQLExecutionError
from .common import event, open_db, query_records

# Tests set this to corrupt figures on purpose, to prove the verifier sends work back.
FAULT: Callable[[list[dict], int], None] | None = None


def period_from(d: dict) -> cal.Period:
    from datetime import date

    return cal.Period(date.fromisoformat(d["start"]), date.fromisoformat(d["end"]), d["label"], d["grain"])


def _scope_words(scope: dict, names: dict) -> str:
    parts = []
    for dim in ("region", "channel", "category", "brand", "product", "customer"):
        for value in scope.get(dim, []):
            parts.append(names.get(dim, {}).get(value, value))
    return " ".join(parts) if parts else "Company"


def make_label(metric_id: str, scope: dict, period_label: str, names: dict) -> str:
    return f"{_scope_words(scope, names)} {METRICS[metric_id].name.lower()}, {period_label}"


class FactBook:
    """Collects facts with sequential ids."""

    def __init__(self, existing: list[dict] | None = None):
        self.facts = list(existing or [])

    def add(self, **fact) -> dict:
        fact["id"] = f"F{len(self.facts) + 1}"
        self.facts.append(fact)
        return fact


def compute_facts(db, resolved: dict, book: FactBook) -> str | None:
    """Fill the fact book for the question. Returns the headline fact id."""
    names = {"region": resolved["region_names"]}
    filters = resolved["filters"]
    group_by = resolved["group_by"]
    region_ids = resolved["region_ids"]
    headline = None

    for metric_id in resolved["metrics"]:
        metric = METRICS[metric_id]
        for pd in resolved["periods"]:
            period = period_from(pd)
            base = {
                "metric": metric_id,
                "unit": metric.unit,
                "period": pd["label"],
                "period_start": pd["start"],
                "period_end": pd["end"],
            }

            if group_by:
                res = compute_metric(db, metric_id, period, filters, [group_by])
                group_names = display_names(db, group_by, [k[0] for k in res.values]) | names.get(
                    group_by, {}
                )
                names[group_by] = group_names
                rows = [(k[0], v) for k, v in res.values.items() if v is not None]
                if resolved["rank"]:
                    rows.sort(key=lambda kv: kv[1], reverse=resolved["rank"] == "highest")
                limit = resolved["top_n"] or (10 if resolved["rank"] else 50)
                for i, (value_key, value) in enumerate(rows[:limit]):
                    scope = {k: list(v) for k, v in filters.items()}
                    scope[group_by] = [value_key]
                    label_scope = {k: v for k, v in scope.items() if k != "month"}
                    period_label = (
                        group_names.get(value_key, value_key) if group_by == "month" else pd["label"]
                    )
                    f = book.add(
                        **base,
                        label=make_label(metric_id, label_scope, period_label, names),
                        value=value,
                        scope=scope,
                        role="group",
                        rank=(i + 1) if resolved["rank"] else None,
                        query_ids=res.query_ids,
                        tables=res.tables,
                        measures=res.measures[(value_key,)],
                    )
                    if headline is None and resolved["rank"] and i == 0:
                        headline = f["id"]
                if metric.is_money:
                    total = compute_metric(db, metric_id, period, filters)
                    book.add(
                        **base,
                        label=make_label(metric_id, filters, pd["label"], names) + " (total)",
                        value=total.total,
                        scope=dict(filters),
                        role="total",
                        query_ids=total.query_ids,
                        tables=total.tables,
                        measures=total.measures[()],
                        covers_all_groups=len(rows) <= limit,
                    )
            elif len(region_ids) > 1:
                res = compute_metric(db, metric_id, period, filters, ["region"])
                for (rid,), value in res.values.items():
                    scope = {**filters, "region": [rid]}
                    book.add(
                        **base,
                        label=make_label(metric_id, scope, pd["label"], names),
                        value=value,
                        scope=scope,
                        role="value",
                        query_ids=res.query_ids,
                        tables=res.tables,
                        measures=res.measures[(rid,)],
                    )
            else:
                res = compute_metric(db, metric_id, period, filters)
                f = book.add(
                    **base,
                    label=make_label(metric_id, filters, pd["label"], names),
                    value=res.total,
                    scope=dict(filters),
                    role="value",
                    query_ids=res.query_ids,
                    tables=res.tables,
                    measures=res.measures[()],
                )
                if headline is None:
                    headline = f["id"]
    return headline


def data_analyst(state: dict) -> dict:
    attempt = state.get("send_backs", 0)
    db = open_db(state)
    book = FactBook()
    try:
        try:
            headline = compute_facts(db, state["resolved"], book)
        except SQLExecutionError:
            # One retry for a transient database error (a lock or a timeout).
            book = FactBook()
            headline = compute_facts(db, state["resolved"], book)
    except NotAvailable as e:
        return _fail(state, db, "DATA_NOT_AVAILABLE", f"The data cannot be cut this way: {e}.")
    except SQLExecutionError as e:
        return _fail(state, db, "DATA_NOT_AVAILABLE", f"The sales database could not be read ({e}).")
    finally:
        db.close()
    if FAULT is not None:
        FAULT(book.facts, attempt)
    return {
        "facts": book.facts,
        "headline": headline,
        "queries": query_records(db, "data_analyst"),
        "trace": [event("data_analyst", "computed", facts=len(book.facts), attempt=attempt + 1)],
    }


def _fail(state: dict, db, code: str, detail: str) -> dict:
    return {
        "decision": "cannot_answer",
        "reason_code": code,
        "reason_detail": detail,
        "facts": [],
        "headline": None,
        "queries": query_records(db, "data_analyst"),
        "trace": [event("data_analyst", "tool_failed", detail=detail)],
    }
