"""Metric registry: finance's approved definitions (docs/metric_definitions.md).

Two layers:
- Measures are single SQL aggregates over one source (order lines, returns,
  orders, promotions, targets). The compiler turns them into SQL.
- Metrics combine measures with a formula in Python. The model never writes
  these formulas; it only picks a metric id.

Each measure is dated the way the definition says: order lines and freight
by order date, refunds and reversed cost by return date (M3, M4).
"""

from collections.abc import Callable
from dataclasses import dataclass, field

DOC = "metric_definitions.md"


@dataclass(frozen=True)
class Measure:
    id: str
    source: str  # key in compiler.SOURCES
    expr: str  # SQL aggregate over that source's aliases
    note: str


MEASURES: dict[str, Measure] = {
    m.id: m
    for m in [
        Measure("gross_sales", "lines", "SUM(l.qty * l.list_price)", "M1: list price x quantity"),
        Measure("discounts", "lines", "SUM(l.discount_amount)", "M2: trade + promotional discounts"),
        Measure("line_net_revenue", "lines", "SUM(l.net_revenue)", "M3: order-line net revenue, order month"),
        Measure("refunds", "returns", "SUM(r.refund_amount)", "M3: refunds, return month"),
        Measure("line_cogs", "lines", "SUM(l.cogs)", "M4: order-line COGS, order month"),
        Measure(
            "cogs_reversed", "returns", "SUM(r.cogs_reversed)", "M4: cost reversed on returns, return month"
        ),
        Measure("freight", "orders", "SUM(o.freight_cost)", "M6: freight, order month"),
        # Promotional discounts sit on top of trade discounts at the promotion's
        # stated rate (promo briefs), so the promotional part is exact.
        Measure(
            "promotion_cost",
            "promo",
            "SUM(l.qty * l.list_price * pr.discount_pct / 100.0)",
            "M8: promotional part of discounts, in the promotion's region and dates",
        ),
        Measure("revenue_target", "targets", "SUM(t.revenue_target)", "M7: revenue target"),
        # Inputs for explaining a change (margin and revenue bridges), not metrics on their own.
        Measure(
            "refunds_damaged",
            "returns",
            "SUM(CASE WHEN r.return_reason = 'damaged' THEN r.refund_amount ELSE 0 END)",
            "M4: refunds on damaged returns, whose cost is not reversed",
        ),
        Measure("units", "lines", "SUM(l.qty)", "units sold, order month"),
    ]
}


def _div(a: float, b: float) -> float | None:
    return None if b == 0 else a / b


@dataclass(frozen=True)
class Metric:
    id: str
    name: str
    doc_ref: str  # citation, e.g. "metric_definitions.md#M5"
    unit: str  # INR | PCT
    measures: tuple[str, ...]
    formula: Callable[[dict[str, float]], float | None]
    synonyms: tuple[str, ...] = field(default=())

    @property
    def is_money(self) -> bool:
        return self.unit == "INR"


def _net_revenue(v):
    return v["line_net_revenue"] - v["refunds"]


def _net_cogs(v):
    return v["line_cogs"] - v["cogs_reversed"]


def _gross_margin_pct(v):
    nr = _net_revenue(v)
    r = _div(nr - _net_cogs(v), nr)
    return None if r is None else r * 100


def _gap(v):
    return _net_revenue(v) - v["revenue_target"]


def _gap_pct(v):
    r = _div(_gap(v), v["revenue_target"])
    return None if r is None else r * 100


METRICS: dict[str, Metric] = {
    m.id: m
    for m in [
        Metric(
            "gross_sales",
            "Gross sales",
            f"{DOC}#M1",
            "INR",
            ("gross_sales",),
            lambda v: v["gross_sales"],
            ("gross sales", "list sales"),
        ),
        Metric(
            "discounts",
            "Discounts",
            f"{DOC}#M2",
            "INR",
            ("discounts",),
            lambda v: v["discounts"],
            ("discounts", "discount"),
        ),
        Metric(
            "net_revenue",
            "Net revenue",
            f"{DOC}#M3",
            "INR",
            ("line_net_revenue", "refunds"),
            _net_revenue,
            ("net revenue", "revenue", "sales", "net sales"),
        ),
        Metric(
            "net_cogs",
            "Net cost of goods sold",
            f"{DOC}#M4",
            "INR",
            ("line_cogs", "cogs_reversed"),
            _net_cogs,
            ("cogs", "cost of goods sold", "net cogs"),
        ),
        Metric(
            "gross_margin_pct",
            "Gross margin %",
            f"{DOC}#M5",
            "PCT",
            ("line_net_revenue", "refunds", "line_cogs", "cogs_reversed"),
            _gross_margin_pct,
            ("gross margin", "margin", "gm"),
        ),
        Metric(
            "contribution_margin",
            "Contribution margin",
            f"{DOC}#M6",
            "INR",
            ("line_net_revenue", "refunds", "line_cogs", "cogs_reversed", "freight"),
            lambda v: _net_revenue(v) - _net_cogs(v) - v["freight"],
            ("contribution margin",),
        ),
        Metric(
            "revenue_target",
            "Revenue target",
            f"{DOC}#M7",
            "INR",
            ("revenue_target",),
            lambda v: v["revenue_target"],
            ("revenue target", "target"),
        ),
        Metric(
            "revenue_vs_target_gap",
            "Net revenue minus target",
            f"{DOC}#M7",
            "INR",
            ("line_net_revenue", "refunds", "revenue_target"),
            _gap,
            ("gap to target", "vs target"),
        ),
        Metric(
            "revenue_vs_target_gap_pct",
            "Gap to target, % of target",
            f"{DOC}#M7",
            "PCT",
            ("line_net_revenue", "refunds", "revenue_target"),
            _gap_pct,
            ("% of target",),
        ),
        Metric(
            "promotion_cost",
            "Promotion cost",
            f"{DOC}#M8",
            "INR",
            ("promotion_cost",),
            lambda v: v["promotion_cost"],
            ("promotion cost", "promo cost", "promotional spend"),
        ),
    ]
}

# Things finance asks about that the data does not hold (RS5). The gate
# answers DATA_NOT_AVAILABLE for these instead of estimating.
NOT_IN_DATA = {
    "salesperson": "sales by salesperson (no salesperson field on orders or customers)",
    "marketing_spend": "marketing spend (only promotional discounts are recorded)",
    "inventory": "inventory or stock levels",
    "raw_material_cost": "raw material or factory cost breakdown (only COGS per order line)",
    "headcount": "headcount or payroll",
    "forecast": "forecasts or future months (data ends September 2026)",
}
