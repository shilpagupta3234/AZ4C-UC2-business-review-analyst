"""Builds tests/cases and tests/expected (28 cases) from the data pack.

Expected answers are computed here with hand-written SQL that shares no code with app/,
so the eval checks the system against an independent calculation.

Run from code/:  python tests/build_cases.py
"""

import json
import os
import sqlite3
from pathlib import Path

CODE = Path(__file__).resolve().parents[1]
PACK = Path(os.environ.get("DATA_DIR", "").strip() or CODE.parent)
con = sqlite3.connect(f"{(PACK / 'data' / 'sales.sqlite').resolve().as_uri()}?mode=ro", uri=True)

PERIODS = {
    "jun26": ("2026-06-01", "2026-06-30"),
    "jul26": ("2026-07-01", "2026-07-31"),
    "aug26": ("2026-08-01", "2026-08-31"),
    "sep26": ("2026-09-01", "2026-09-30"),
    "q1fy27": ("2026-04-01", "2026-06-30"),
    "q2fy27": ("2026-07-01", "2026-09-30"),
    "fy26": ("2025-04-01", "2026-03-31"),
}
REGIONS = {"North": "R1", "South": "R2", "East": "R3", "West": "R4", "Central": "R5"}


def one(sql: str, *params) -> float:
    return con.execute(sql, params).fetchone()[0] or 0.0


def _region(region: str | None) -> tuple[str, list]:
    return (" AND o.region_id = ?", [region]) if region else ("", [])


def line_sum(col: str, period: str, region: str | None = None, extra: str = "") -> float:
    rf, rp = _region(region)
    sql = (
        f"SELECT SUM(l.{col}) FROM order_lines l, orders o WHERE l.order_id = o.order_id "
        f"AND o.order_date BETWEEN ? AND ?{rf}{extra}"
    )
    return one(sql, *PERIODS[period], *rp)


def return_sum(col: str, period: str, region: str | None = None, extra: str = "") -> float:
    rf, rp = _region(region)
    sql = (
        f"SELECT SUM(r.{col}) FROM returns r, orders o WHERE r.order_id = o.order_id "
        f"AND r.return_date BETWEEN ? AND ?{rf}{extra}"
    )
    return one(sql, *PERIODS[period], *rp)


def net_revenue(period, region=None, extra_l="", extra_r=""):
    return line_sum("net_revenue", period, region, extra_l) - return_sum(
        "refund_amount", period, region, extra_r
    )


def net_cogs(period, region=None, extra_l="", extra_r=""):
    return line_sum("cogs", period, region, extra_l) - return_sum("cogs_reversed", period, region, extra_r)


def gross_margin(period, region=None, extra_l="", extra_r=""):
    nr = net_revenue(period, region, extra_l, extra_r)
    return (nr - net_cogs(period, region, extra_l, extra_r)) / nr * 100


def product_filters(column: str, value: str) -> tuple[str, str]:
    products = f"SELECT product_id FROM products WHERE {column} = '{value}'"
    lines = f" AND l.product_id IN ({products})"
    returns = (
        " AND EXISTS (SELECT 1 FROM order_lines x WHERE x.order_id = r.order_id "
        f"AND x.line_no = r.line_no AND x.product_id IN ({products}))"
    )
    return lines, returns


def customer_filter(condition: str) -> str:
    return f" AND o.customer_id IN (SELECT customer_id FROM customers WHERE {condition})"


def money(v: float) -> dict:
    return {"value": round(v, 2), "tolerance": 1.0}


def pct(v: float) -> dict:
    return {"value": round(v, 2), "tolerance": 0.05}


CASES: list[tuple[str, dict]] = []


def add(question, decision="answered", codes=("ANSWERED",), amount=None, keys=(), cite=()):
    CASES.append(
        (
            question,
            {
                "decision": decision,
                "reason_code": list(codes),
                "amount": amount,
                "key_numbers": list(keys),
                "must_cite": list(cite),
                "needs_human": decision == "answered",
            },
        )
    )


def refuse(question, *codes):
    add(question, "cannot_answer", codes)


def build() -> None:
    v = net_revenue("sep26", "R1")
    add(
        "What was North's net revenue in September 2026?",
        amount=money(v),
        keys=[money(v)],
        cite=["order_lines", "returns"],
    )
    add(
        "What was the company's gross margin in Q2 FY27?",
        keys=[pct(gross_margin("q2fy27"))],
        cite=["order_lines", "returns"],
    )
    freight = one(
        "SELECT SUM(freight_cost) FROM orders WHERE region_id = 'R3' "
        "AND order_date BETWEEN '2026-08-01' AND '2026-08-31'"
    )
    v = net_revenue("aug26", "R3") - net_cogs("aug26", "R3") - freight
    add("What was East's contribution margin in August 2026?", amount=money(v), keys=[money(v)])
    v = max(net_revenue("q1fy27", r) for r in REGIONS.values())
    add("Which region had the highest net revenue in Q1 FY27?", amount=money(v), keys=[money(v)])
    categories = [c for (c,) in con.execute("SELECT DISTINCT category FROM products")]
    lowest = min(gross_margin("fy26", None, *product_filters("category", c)) for c in categories)
    add("Which product category had the lowest gross margin in FY26?", keys=[pct(lowest)])
    target = one("SELECT revenue_target FROM targets WHERE region_id = 'R5' AND month = '2026-07'")
    actual = net_revenue("jul26", "R5")
    add(
        "Did Central meet its revenue target in July 2026?",
        amount=money(actual - target),
        keys=[money(target), money(actual)],
        cite=["targets"],
    )
    promo = 0.15 * one(
        "SELECT SUM(l.qty * l.list_price) FROM order_lines l JOIN orders o ON o.order_id = l.order_id "
        "WHERE o.region_id = 'R2' AND o.order_date BETWEEN '2026-09-01' AND '2026-09-30'"
    )
    add(
        "What was the promotion cost in South in September 2026?",
        amount=money(promo),
        keys=[money(promo)],
        cite=["promotions"],
    )
    add(
        "Why did South's margin drop in September 2026?",
        keys=[pct(gross_margin("aug26", "R2")), pct(gross_margin("sep26", "R2"))],
        cite=["commentary/2026-09_south.md", "promotions", "returns"],
    )
    add("What was North's gross margin in September 2026?", keys=[pct(gross_margin("sep26", "R1"))])
    jul, aug = net_revenue("jul26", "R4"), net_revenue("aug26", "R4")
    add(
        "Compare West's net revenue in July 2026 and August 2026.",
        amount=money(aug - jul),
        keys=[money(jul), money(aug)],
    )
    channels = [customer_filter(f"channel = '{c}'") for c in ("Modern Trade", "General Trade", "E-commerce")]
    add(
        "Show net revenue by channel for Central in Q2 FY27.",
        keys=[money(net_revenue("q2fy27", "R5", f, f)) for f in channels],
        cite=["customers"],
    )
    refuse("What was gross margin in December 2026?", "DATA_NOT_AVAILABLE")
    refuse("How much did East spend on marketing in Q1 FY27?", "DATA_NOT_AVAILABLE")
    refuse("Update North's July 2026 revenue target to 6000000.", "WRITE_REQUEST_REFUSED")
    refuse("How did we do last month?", "AMBIGUOUS_QUESTION")
    refuse("What was margin in August?", "AMBIGUOUS_QUESTION")
    refuse(
        "What was net revenue for the Atlantis region in July 2026?",
        "DATA_NOT_AVAILABLE",
        "AMBIGUOUS_QUESTION",
    )
    v = line_sum("qty * l.list_price", "q1fy27", "R2")
    add("What were South's gross sales in Q1 FY27?", amount=money(v), keys=[money(v)])
    add(
        "Show the monthly net revenue trend for North in Q2 FY27.",
        keys=[money(net_revenue(m, "R1")) for m in ("jul26", "aug26", "sep26")],
    )
    brands = [b for (b,) in con.execute("SELECT DISTINCT brand FROM products")]
    v = max(net_revenue("sep26", None, *product_filters("brand", b)) for b in brands)
    add("Which brand had the highest net revenue in September 2026?", amount=money(v), keys=[money(v)])
    v = line_sum("discount_amount", "aug26")
    add("What were total discounts in August 2026?", amount=money(v), keys=[money(v)])
    jul, jun = net_revenue("jul26", "R3"), net_revenue("jun26", "R3")
    add(
        "Why did East's net revenue fall in July 2026?",
        amount=money(jul - jun),
        keys=[money(jul), money(jun)],
        cite=["commentary/2026-07_east.md"],
    )
    refuse("What are South's inventory levels in September 2026?", "DATA_NOT_AVAILABLE")
    refuse("Please delete the returns recorded in September 2026.", "WRITE_REQUEST_REFUSED")
    v = net_revenue("fy26")
    add("What was the company's total net revenue in FY26?", amount=money(v), keys=[money(v)])
    refuse("What will net revenue be next quarter?", "DATA_NOT_AVAILABLE", "AMBIGUOUS_QUESTION")
    target = one("SELECT revenue_target FROM targets WHERE region_id = 'R2' AND month = '2026-08'")
    actual = net_revenue("aug26", "R2")
    add(
        "How did South do against its revenue target in August 2026?",
        amount=money(actual - target),
        keys=[money(target), money(actual)],
        cite=["targets"],
    )
    customers = [c for (c,) in con.execute("SELECT customer_id FROM customers")]
    v = max(
        net_revenue("sep26", None, f" AND o.customer_id = '{c}'", f" AND o.customer_id = '{c}'")
        for c in customers
    )
    add("Which customer had the highest net revenue in September 2026?", amount=money(v), keys=[money(v)])


def write() -> None:
    cases_dir, expected_dir = CODE / "tests" / "cases", CODE / "tests" / "expected"
    for d in (cases_dir, expected_dir):
        d.mkdir(parents=True, exist_ok=True)
        for old in d.glob("TC-*.json"):
            old.unlink()
    for i, (question, expected) in enumerate(CASES, 1):
        case_id = f"TC-{i:02d}"
        case = {"case_id": case_id, "input": {"question": question}}
        (cases_dir / f"{case_id}.json").write_text(json.dumps(case, indent=2) + "\n", encoding="utf-8")
        (expected_dir / f"{case_id}.json").write_text(
            json.dumps({"case_id": case_id, **expected}, indent=2) + "\n", encoding="utf-8"
        )
    print(f"{len(CASES)} cases written")


if __name__ == "__main__":
    build()
    write()
