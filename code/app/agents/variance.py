"""Targets and variance agent: actual vs target, change vs another period, and why.

Plain code, no model. For "why" questions it builds a bridge: the change is
split into drivers that add up to it exactly (RS2, within 0.1 pp):

  gross margin bridge (pp): product cost vs list price, trade discounts,
      promotional discounts, saleable returns, damaged returns
  net revenue bridge (INR):   gross sales, trade discounts, promotional
      discounts, refunds

Each step adds one cost to the previous margin, so the steps telescope and
their sum equals the total change by construction.
"""

import re

from ..semantic import calendar as cal
from ..semantic.metrics import METRICS
from ..tools.metrics import compute_metric, run_measures
from ..tools.sql import SQLExecutionError
from .common import event, open_db, query_records
from .data_analyst import FactBook, _scope_words, make_label, period_from

BRIDGE_MEASURES = [
    "gross_sales",
    "discounts",
    "promotion_cost",
    "line_net_revenue",
    "line_cogs",
    "refunds",
    "refunds_damaged",
    "cogs_reversed",
    "units",
]
MARGIN_DRIVERS = [
    ("product_cost", "product cost relative to list price (incl. mix)"),
    ("trade_discounts", "trade discounts"),
    ("promo_discounts", "promotional discounts"),
    ("saleable_returns", "returns of saleable stock"),
    ("damaged_returns", "damaged returns (refunded, cost not reversed)"),
]
REVENUE_DRIVERS = [
    ("gross_sales", "gross sales (volume and list price)"),
    ("trade_discounts", "trade discounts"),
    ("promo_discounts", "promotional discounts"),
    ("refunds", "refunds for returns"),
]


def _ratio(num: float, den: float) -> float:
    return num / den * 100 if den else 0.0


def margin_steps(v: dict) -> dict:
    """Margin after adding each cost in turn. The last step is the reported gross margin (M5)."""
    g, d, pr = v["gross_sales"], v["discounts"], v["promotion_cost"]
    lnr, lc = v["line_net_revenue"], v["line_cogs"]
    rf, rd, cr = v["refunds"], v["refunds_damaged"], v["cogs_reversed"]
    trade = d - pr
    rs = rf - rd
    return {
        "list": _ratio(g - lc, g),
        "trade": _ratio(g - trade - lc, g - trade),
        "promo": _ratio(lnr - lc, lnr),
        "saleable": _ratio(lnr - rs - (lc - cr), lnr - rs),
        "actual": _ratio(lnr - rf - (lc - cr), lnr - rf),
    }


def margin_bridge(base: dict, cur: dict) -> dict:
    b, c = margin_steps(base), margin_steps(cur)
    drivers = {
        "product_cost": c["list"] - b["list"],
        "trade_discounts": (c["trade"] - c["list"]) - (b["trade"] - b["list"]),
        "promo_discounts": (c["promo"] - c["trade"]) - (b["promo"] - b["trade"]),
        "saleable_returns": (c["saleable"] - c["promo"]) - (b["saleable"] - b["promo"]),
        "damaged_returns": (c["actual"] - c["saleable"]) - (b["actual"] - b["saleable"]),
    }
    return {
        "base": b["actual"],
        "current": c["actual"],
        "change": c["actual"] - b["actual"],
        "drivers": drivers,
    }


def revenue_bridge(base: dict, cur: dict) -> dict:
    def nr(v):
        return v["line_net_revenue"] - v["refunds"]

    def trade(v):
        return v["discounts"] - v["promotion_cost"]

    drivers = {
        "gross_sales": cur["gross_sales"] - base["gross_sales"],
        "trade_discounts": -(trade(cur) - trade(base)),
        "promo_discounts": -(cur["promotion_cost"] - base["promotion_cost"]),
        "refunds": -(cur["refunds"] - base["refunds"]),
    }
    return {"base": nr(base), "current": nr(cur), "change": nr(cur) - nr(base), "drivers": drivers}


def _scopes(resolved: dict) -> list[dict]:
    filters = resolved["filters"]
    if len(resolved["region_ids"]) > 1:
        return [{**filters, "region": [rid]} for rid in resolved["region_ids"]]
    return [dict(filters)]


def _comparison_periods(resolved: dict, data_start: str) -> tuple[cal.Period | None, cal.Period]:
    periods = [period_from(p) for p in resolved["periods"]]
    current = periods[-1]
    if len(periods) >= 2:
        return periods[0], current
    base = cal.previous(current)
    return (base if base.start.isoformat() >= data_start else None), current


def _value(db, book: FactBook, metric_id: str, period: cal.Period, scope: dict, names: dict, tables: list):
    for f in book.facts:
        if (
            f["metric"] == metric_id
            and f["period"] == period.label
            and f["scope"] == scope
            and f["role"] == "value"
        ):
            return f
    res = compute_metric(db, metric_id, period, scope)
    tables += [t for t in res.tables if t not in tables]
    return book.add(
        metric=metric_id,
        unit=METRICS[metric_id].unit,
        period=period.label,
        period_start=period.start.isoformat(),
        period_end=period.end.isoformat(),
        label=make_label(metric_id, scope, period.label, names),
        value=res.total,
        scope=scope,
        role="value",
        query_ids=res.query_ids,
        tables=res.tables,
        measures=res.measures[()],
    )


def _targets(db, book: FactBook, resolved: dict, names: dict, out: dict) -> str | None:
    headline = None
    scopes = _scopes(resolved) if resolved["region_ids"] else [{}]
    for scope in scopes:
        for pd in resolved["periods"]:
            period = period_from(pd)
            actual = _value(db, book, "net_revenue", period, scope, names, out["tables"])
            target = compute_metric(db, "revenue_target", period, scope)
            gap = actual["value"] - target.total
            gap_pct = gap / target.total * 100 if target.total else None
            common = {
                "period": pd["label"],
                "period_start": pd["start"],
                "period_end": pd["end"],
                "scope": scope,
                "query_ids": target.query_ids,
                "tables": target.tables,
            }
            t = book.add(
                **common,
                metric="revenue_target",
                unit="INR",
                value=target.total,
                role="target",
                label=make_label("revenue_target", scope, pd["label"], names),
                measures={},
            )
            g = book.add(
                **common,
                metric="revenue_vs_target_gap",
                unit="INR",
                value=gap,
                role="derived",
                label=make_label("revenue_vs_target_gap", scope, pd["label"], names),
                derived_from=[actual["id"], t["id"]],
                measures={},
            )
            gp = book.add(
                **common,
                metric="revenue_vs_target_gap_pct",
                unit="PCT",
                value=gap_pct,
                role="derived",
                label=make_label("revenue_vs_target_gap_pct", scope, pd["label"], names),
                derived_from=[g["id"], t["id"]],
                measures={},
            )
            out["targets"].append(
                {
                    "scope": _scope_words(scope, names),
                    "period": pd["label"],
                    "actual": actual["id"],
                    "target": t["id"],
                    "gap": g["id"],
                    "gap_pct": gp["id"],
                    "met": gap >= 0,
                }
            )
            out["tables"] += [x for x in target.tables if x not in out["tables"]]
            headline = headline or g["id"]
            if "gross_margin_pct" in resolved["metrics"] and pd["grain"] == "month" and scope.get("region"):
                rid = scope["region"][0]
                res = db.run(
                    "SELECT gross_margin_target_pct FROM targets WHERE region_id = ? AND month = ?",
                    [rid, pd["start"][:7]],
                )
                if res.rows:
                    margin = _value(db, book, "gross_margin_pct", period, scope, names, out["tables"])
                    mt = book.add(
                        **{**common, "query_ids": [res.query_id], "tables": ["targets"]},
                        metric="gross_margin_target_pct",
                        unit="PCT",
                        value=float(res.rows[0][0]),
                        role="target",
                        measures={},
                        label=f"{_scope_words(scope, names)} gross margin target %, {pd['label']}",
                    )
                    book.add(
                        **{**common, "query_ids": [res.query_id], "tables": ["targets"]},
                        metric="gross_margin_vs_target_pp",
                        unit="PP",
                        value=margin["value"] - mt["value"],
                        role="derived",
                        derived_from=[margin["id"], mt["id"]],
                        measures={},
                        label=f"{_scope_words(scope, names)} gross margin minus target, {pd['label']}",
                    )
    return headline


def _changes(db, book: FactBook, resolved: dict, names: dict, out: dict, why: bool) -> str | None:
    base_p, cur_p = _comparison_periods(resolved, resolved["data_start"])
    if base_p is None:
        out["notes"].append(f"No earlier period than {cur_p.label} is held, so no change can be shown.")
        return None
    out["base_period"], out["current_period"] = base_p.label, cur_p.label
    headline = None
    span = f"{base_p.label} to {cur_p.label}"
    for scope in _scopes(resolved):
        words = _scope_words(scope, names)
        for metric_id in resolved["metrics"]:
            metric = METRICS[metric_id]
            b = _value(db, book, metric_id, base_p, scope, names, out["tables"])
            c = _value(db, book, metric_id, cur_p, scope, names, out["tables"])
            if b["value"] is None or c["value"] is None:
                continue
            unit = "INR" if metric.is_money else "PP"
            common = {
                "period": span,
                "period_start": base_p.start.isoformat(),
                "period_end": cur_p.end.isoformat(),
                "scope": scope,
                "query_ids": [],
                "tables": [],
                "measures": {},
            }
            change = book.add(
                **common,
                metric=f"{metric_id}_change",
                unit=unit,
                value=c["value"] - b["value"],
                role="derived",
                derived_from=[c["id"], b["id"]],
                label=f"{words} {metric.name.lower()} change, {span}",
            )
            headline = headline or change["id"]
            if metric.is_money and b["value"]:
                book.add(
                    **common,
                    metric=f"{metric_id}_change_pct",
                    unit="PCT",
                    role="derived",
                    value=(c["value"] - b["value"]) / abs(b["value"]) * 100,
                    derived_from=[c["id"], b["id"]],
                    label=f"{words} {metric.name.lower()} change %, {span}",
                )
            out["changes"].append(
                {
                    "metric": metric_id,
                    "scope": words,
                    "base": b["id"],
                    "current": c["id"],
                    "change": change["id"],
                }
            )
            if why and metric_id in ("gross_margin_pct", "net_revenue"):
                _bridge(db, book, metric_id, base_p, cur_p, scope, words, span, change["value"], out)
    return headline


def _bridge(db, book, metric_id, base_p, cur_p, scope, words, span, total_change, out) -> None:
    bv, bq, bt = run_measures(db, BRIDGE_MEASURES, base_p, scope)
    cv, cq, ct = run_measures(db, BRIDGE_MEASURES, cur_p, scope)
    tables = list(dict.fromkeys(bt + ct))
    out["tables"] += [t for t in tables if t not in out["tables"]]
    if metric_id == "gross_margin_pct":
        bridge, spec, unit = margin_bridge(bv, cv), MARGIN_DRIVERS, "PP"
    else:
        bridge, spec, unit = revenue_bridge(bv, cv), REVENUE_DRIVERS, "INR"
    common = {
        "period": span,
        "period_start": base_p.start.isoformat(),
        "period_end": cur_p.end.isoformat(),
        "scope": scope,
        "query_ids": bq + cq,
        "tables": tables,
        "measures": {},
    }
    drivers = []
    for key, name in spec:
        f = book.add(
            **common,
            metric=f"{metric_id}_driver_{key}",
            unit=unit,
            value=bridge["drivers"][key],
            role="driver",
            label=f"{words} {METRICS[metric_id].name.lower()} change from {name}, {span}",
        )
        drivers.append({"key": key, "name": name, "fact": f["id"], "value": bridge["drivers"][key]})
    total = sum(d["value"] for d in drivers)
    tolerance = 0.1 if unit == "PP" else 1.0
    if metric_id == "gross_margin_pct":
        promo = book.add(
            **{**common, "period": cur_p.label},
            metric="promo_discount_rate",
            unit="PCT",
            role="support",
            value=_ratio(cv["promotion_cost"], cv["gross_sales"]),
            label=f"{words} promotional discounts as % of gross sales, {cur_p.label}",
        )
        damaged = book.add(
            **{**common, "period": cur_p.label},
            metric="damaged_refunds",
            unit="INR",
            role="support",
            value=cv["refunds_damaged"],
            label=f"{words} refunds on damaged returns, {cur_p.label}",
        )
        cost_b = book.add(
            **{**common, "period": base_p.label},
            metric="cost_to_list",
            unit="PCT",
            role="support",
            value=_ratio(bv["line_cogs"], bv["gross_sales"]),
            label=f"{words} COGS as % of gross sales, {base_p.label}",
        )
        cost_c = book.add(
            **{**common, "period": cur_p.label},
            metric="cost_to_list",
            unit="PCT",
            role="support",
            value=_ratio(cv["line_cogs"], cv["gross_sales"]),
            label=f"{words} COGS as % of gross sales, {cur_p.label}",
        )
        support = [promo["id"], damaged["id"], cost_b["id"], cost_c["id"]]
    else:
        units = book.add(
            **common,
            metric="units_change",
            unit="UNITS",
            role="support",
            value=cv["units"] - bv["units"],
            label=f"{words} change in units sold, {span}",
        )
        support = [units["id"]]
    out["bridges"].append(
        {
            "metric": metric_id,
            "scope": words,
            "base_period": base_p.label,
            "current_period": cur_p.label,
            "unit": unit,
            "total_change": total_change,
            "drivers": drivers,
            "sum_of_drivers": total,
            "reconciles": abs(total - total_change) <= tolerance,
            "support": support,
            "measures": {"base": bv, "current": cv},
        }
    )


def variance(state: dict) -> dict:
    resolved = state["resolved"]
    names = {"region": resolved["region_names"]}
    book = FactBook(state.get("facts", []))
    out = {"changes": [], "targets": [], "bridges": [], "notes": [], "tables": []}
    qtype = resolved["question_type"]
    why = qtype == "why"
    wants_target = qtype == "vs_target" or (why and re.search(r"\btargets?\b", state["question"], re.I))
    db = open_db(state)
    headline = state.get("headline")
    try:
        if wants_target:
            headline = _targets(db, book, resolved, names, out) or headline
        if qtype in ("comparison", "why") or resolved["compare_previous"]:
            change_headline = _changes(db, book, resolved, names, out, why)
            if qtype != "vs_target":
                headline = change_headline or headline
    except SQLExecutionError as e:
        out["notes"].append(f"variance tool failed: {e}")
    finally:
        db.close()
    return {
        "facts": book.facts,
        "headline": headline,
        "variance": out,
        "queries": query_records(db, "variance"),
        "trace": [
            event(
                "variance",
                "compared",
                changes=len(out["changes"]),
                targets=len(out["targets"]),
                bridges=len(out["bridges"]),
                notes=out["notes"],
            )
        ],
    }
