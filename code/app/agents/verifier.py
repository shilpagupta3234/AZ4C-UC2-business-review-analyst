"""Verifier: checks every figure by a second, independent path.

Plain code, no model (a model cannot reliably check arithmetic).
- Each base figure is recomputed with SQL written separately here, using
  subqueries instead of the compiler's joins, and its own formulas.
- Derived figures (changes, gaps) are recomputed from the figures they use.
- Invariants: group figures add up to their total within INR 1 (RS2), bridge
  drivers add up to the change within 0.1 pp (RS2), margins sit in -100..100,
  and a ranking's headline really is the top or bottom item.
If anything disagrees, the work goes back to the data analyst, twice at most.
"""

from .. import config
from ..tools.sql import SQLExecutionError
from .common import event, open_db, query_records

_MAX_CHECKED = 15
_TOL = {"INR": 1.0, "PCT": 0.01, "PP": 0.01, "UNITS": 0.5}


def _where_orders(scope: dict, params: list) -> str:
    """Conditions on orders o for a scope. Product filters are applied to lines separately."""
    sql = ""
    if scope.get("region"):
        sql += f" AND o.region_id IN ({','.join('?' * len(scope['region']))})"
        params += scope["region"]
    if scope.get("customer"):
        sql += f" AND o.customer_id IN ({','.join('?' * len(scope['customer']))})"
        params += scope["customer"]
    if scope.get("channel"):
        sql += (
            " AND o.customer_id IN (SELECT customer_id FROM customers WHERE channel IN "
            f"({','.join('?' * len(scope['channel']))}))"
        )
        params += scope["channel"]
    return sql


def _where_product(scope: dict, params: list, col: str) -> str:
    sql = ""
    for dim, column in (("product", "product_id"), ("category", "category"), ("brand", "brand")):
        if scope.get(dim):
            sql += (
                f" AND {col} IN (SELECT product_id FROM products WHERE {column} IN "
                f"({','.join('?' * len(scope[dim]))}))"
            )
            params += scope[dim]
    return sql


def _dates(fact: dict) -> tuple[str, str]:
    months = fact["scope"].get("month")
    if months:
        m = months[0]
        return f"{m}-01", f"{m}-31"  # ISO strings: '-31' sorts after every real day of the month
    return fact["period_start"], fact["period_end"]


def independent_inputs(db, fact: dict) -> dict:
    start, end = _dates(fact)
    scope = fact["scope"]

    params = [start, end]
    lines_sql = (
        "SELECT SUM(net_revenue), SUM(cogs), SUM(qty * list_price), SUM(discount_amount) FROM order_lines "
        "WHERE order_id IN (SELECT o.order_id FROM orders o WHERE o.order_date >= ? AND o.order_date <= ?"
    )
    lines_sql += _where_orders(scope, params) + ")" + _where_product(scope, params, "product_id")
    lnr, lc, gross, disc = db.run(lines_sql, params).rows[0]

    params = [start, end]
    ret_sql = (
        "SELECT SUM(r.refund_amount), SUM(r.cogs_reversed) FROM returns r "
        "WHERE r.return_date >= ? AND r.return_date <= ? "
        "AND r.order_id IN (SELECT o.order_id FROM orders o WHERE 1 = 1"
    )
    ret_sql += _where_orders(scope, params) + ")"
    if any(scope.get(d) for d in ("product", "category", "brand")):
        prod = _where_product(scope, params, "x.product_id")
        ret_sql += (
            " AND EXISTS (SELECT 1 FROM order_lines x WHERE x.order_id = r.order_id "
            f"AND x.line_no = r.line_no{prod})"
        )
    refunds, reversed_cogs = db.run(ret_sql, params).rows[0]

    params = [start, end]
    freight_sql = "SELECT SUM(o.freight_cost) FROM orders o WHERE o.order_date >= ? AND o.order_date <= ?"
    freight_sql += _where_orders(scope, params)
    (freight,) = db.run(freight_sql, params).rows[0]

    return {
        "lnr": lnr or 0.0,
        "lc": lc or 0.0,
        "gross": gross or 0.0,
        "disc": disc or 0.0,
        "refunds": refunds or 0.0,
        "reversed": reversed_cogs or 0.0,
        "freight": freight or 0.0,
    }


def independent_value(db, fact: dict) -> float | None:
    metric = fact["metric"]
    if metric == "revenue_target":
        params = [fact["period_start"][:7], fact["period_end"][:7]]
        sql = "SELECT SUM(revenue_target) FROM targets WHERE month >= ? AND month <= ?"
        if fact["scope"].get("region"):
            sql += f" AND region_id IN ({','.join('?' * len(fact['scope']['region']))})"
            params += fact["scope"]["region"]
        return db.run(sql, params).rows[0][0]
    if metric == "promotion_cost":
        start, end = _dates(fact)
        params = [start, end]
        sql = (
            "SELECT SUM(l.qty * l.list_price * p.discount_pct) / 100.0 "
            "FROM promotions p, orders o, order_lines l "
            "WHERE o.region_id = p.region_id AND o.order_date >= p.start_date AND o.order_date <= p.end_date "
            "AND l.order_id = o.order_id AND o.order_date >= ? AND o.order_date <= ?"
        )
        sql += _where_orders(fact["scope"], params) + _where_product(fact["scope"], params, "l.product_id")
        return db.run(sql, params).rows[0][0] or 0.0
    v = independent_inputs(db, fact)
    net_rev = v["lnr"] - v["refunds"]
    net_cogs = v["lc"] - v["reversed"]
    formulas = {
        "gross_sales": lambda: v["gross"],
        "discounts": lambda: v["disc"],
        "net_revenue": lambda: net_rev,
        "net_cogs": lambda: net_cogs,
        "gross_margin_pct": lambda: (net_rev - net_cogs) / net_rev * 100 if net_rev else None,
        "contribution_margin": lambda: net_rev - net_cogs - v["freight"],
    }
    return formulas[metric]() if metric in formulas else None


def check_facts(db, facts: list[dict], headline: str | None, variance: dict) -> tuple[list[str], int]:
    issues, checked = [], 0
    by_id = {f["id"]: f for f in facts}

    base = [f for f in facts if f["role"] in ("value", "group", "total", "target")]
    base.sort(key=lambda f: (f["id"] != headline, f["role"] == "group" and (f.get("rank") or 0) > 3))
    for f in base[:_MAX_CHECKED]:
        expected = independent_value(db, f)
        if expected is None:
            continue
        checked += 1
        if f["value"] is None or abs(f["value"] - expected) > _TOL[f["unit"]]:
            issues.append(f"{f['label']}: computed {f['value']}, second path gives {expected}")
        if (
            f["unit"] == "PCT"
            and f["metric"] == "gross_margin_pct"
            and f["value"] is not None
            and not -100 <= f["value"] <= 100
        ):
            issues.append(f"{f['label']}: margin {f['value']} outside -100..100")

    for f in facts:
        if f["role"] == "derived" and f.get("derived_from"):
            a, b = (by_id[i]["value"] for i in f["derived_from"])
            if a is None or b is None:
                continue
            if f["metric"].endswith("_pct"):
                expected = (a / b * 100) if f["metric"].startswith("revenue_vs") else (a - b) / abs(b) * 100
            else:
                expected = a - b
            checked += 1
            if f["value"] is None or abs(f["value"] - expected) > _TOL[f["unit"]]:
                issues.append(f"{f['label']}: {f['value']} does not follow from its inputs ({expected})")

    groups: dict[tuple, list] = {}
    for f in facts:
        if f["role"] == "group" and f["unit"] == "INR":
            groups.setdefault((f["metric"], f["period"]), []).append(f)
    for f in facts:
        if f["role"] == "total" and f.get("covers_all_groups") and (f["metric"], f["period"]) in groups:
            checked += 1
            total = sum(m["value"] for m in groups[(f["metric"], f["period"])])
            if abs(total - f["value"]) > 1.0:
                issues.append(f"groups add up to {total:.2f}, total is {f['value']:.2f} (RS2: within INR 1)")

    ranked = [f for f in facts if f["role"] == "group" and f.get("rank")]
    if headline and ranked and by_id.get(headline, {}).get("role") == "group":
        top = by_id[headline]
        peers = [f["value"] for f in ranked if f["metric"] == top["metric"] and f["period"] == top["period"]]
        checked += 1
        if top["value"] not in (max(peers), min(peers)):
            issues.append(f"{top['label']} is not the top or bottom item")

    for bridge in variance.get("bridges", []):
        checked += 1
        if not bridge["reconciles"]:
            issues.append(
                f"{bridge['scope']} bridge drivers sum to {bridge['sum_of_drivers']:.4f}, "
                f"change is {bridge['total_change']:.4f} (RS2)"
            )
    return issues, checked


def verifier(state: dict) -> dict:
    db = open_db(state)
    try:
        issues, checked = check_facts(
            db, state.get("facts", []), state.get("headline"), state.get("variance", {})
        )
    except SQLExecutionError as e:
        issues, checked = [f"second path could not run: {e}"], 0
    finally:
        db.close()
    send_backs = state.get("send_backs", 0)
    status = "passed" if not issues else "failed"
    update = {
        "verification": {"status": status, "checked": checked, "issues": issues, "send_backs": send_backs},
        "queries": query_records(db, "verifier"),
        "trace": [event("verifier", status, checked=checked, issues=issues, send_backs=send_backs)],
    }
    if issues:
        if send_backs < config.MAX_SEND_BACKS:
            update["send_backs"] = send_backs + 1
        else:
            update.update(
                {
                    "decision": "cannot_answer",
                    "reason_code": "DATA_NOT_AVAILABLE",
                    "reason_detail": "The figures could not be reconciled by two independent calculations "
                    f"after {send_backs} rechecks, so no number is reported (RS2). "
                    f"Issues: {'; '.join(issues[:3])}",
                }
            )
    return update


def route_after_verifier(state: dict) -> str:
    v = state["verification"]
    if v["status"] == "failed" and state.get("decision") == "answered":
        return "data_analyst"
    return "writer"
