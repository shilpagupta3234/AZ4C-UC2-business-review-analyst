"""compute_metric against the pack's expected answers and hand-written SQL."""

import pytest

from app.semantic import calendar as cal
from app.tools.metrics import compute_metric


def test_s01_south_gross_margin_aug_2026(db):
    r = compute_metric(db, "gross_margin_pct", cal.month(2026, 8), {"region": ["R2"]})
    assert r.total == pytest.approx(34.67, abs=0.05)
    assert {"order_lines", "returns"} <= set(r.tables)


def test_s02_company_net_revenue_jul_2026(db):
    r = compute_metric(db, "net_revenue", cal.month(2026, 7))
    assert r.total == pytest.approx(26637330.05, abs=1.0)


def test_s03_top_channel_q1_fy27(db):
    r = compute_metric(db, "net_revenue", cal.quarter(1, 2027), group_by=["channel"])
    top = max(r.values, key=r.values.get)
    assert top == ("Modern Trade",)
    assert r.values[top] == pytest.approx(43055486.49, abs=1.0)


def test_s04_west_net_revenue_sep_2026(db):
    r = compute_metric(db, "net_revenue", cal.month(2026, 9), {"region": ["R4"]})
    assert r.total == pytest.approx(6015889.56, abs=1.0)


def test_refunds_count_in_return_month(db, raw):
    expected = raw(
        """SELECT SUM(r.refund_amount) FROM returns r JOIN orders o ON o.order_id = r.order_id
           WHERE o.region_id = 'R2' AND r.return_date BETWEEN '2026-08-01' AND '2026-08-31'"""
    )[0][0]
    r = compute_metric(db, "net_revenue", cal.month(2026, 8), {"region": ["R2"]})
    assert r.measures[()]["refunds"] == pytest.approx(expected, abs=0.01)


@pytest.mark.parametrize("metric", ["net_revenue", "net_cogs", "contribution_margin", "gross_sales"])
def test_rs2_regions_add_up_to_company(db, metric):
    p = cal.month(2026, 9)
    company = compute_metric(db, metric, p).total
    by_region = compute_metric(db, metric, p, group_by=["region"])
    assert len(by_region.values) == 5
    assert sum(by_region.values.values()) == pytest.approx(company, abs=1.0)


def test_months_add_up_to_quarter(db):
    q = compute_metric(db, "net_revenue", cal.quarter(1, 2027)).total
    by_month = compute_metric(db, "net_revenue", cal.quarter(1, 2027), group_by=["month"])
    assert list(by_month.values) == [("2026-04",), ("2026-05",), ("2026-06",)]
    assert sum(by_month.values.values()) == pytest.approx(q, abs=1.0)


def test_promotion_cost_pr11(db, raw):
    expected = raw(
        """SELECT SUM(l.qty * l.list_price) * 0.15 FROM order_lines l JOIN orders o ON o.order_id = l.order_id
           WHERE o.region_id = 'R2' AND o.order_date BETWEEN '2026-09-01' AND '2026-09-30'"""
    )[0][0]
    r = compute_metric(db, "promotion_cost", cal.month(2026, 9), {"region": ["R2"]})
    assert r.total == pytest.approx(expected, abs=0.01)


def test_no_promotion_means_zero_promotion_cost(db):
    # Central (R5) had no promotion in July 2026.
    r = compute_metric(db, "promotion_cost", cal.month(2026, 7), {"region": ["R5"]})
    assert r.total == 0.0


def test_revenue_vs_target(db, raw):
    target = raw("SELECT revenue_target FROM targets WHERE region_id = 'R1' AND month = '2026-07'")[0][0]
    actual = compute_metric(db, "net_revenue", cal.month(2026, 7), {"region": ["R1"]}).total
    gap = compute_metric(db, "revenue_vs_target_gap", cal.month(2026, 7), {"region": ["R1"]}).total
    gap_pct = compute_metric(db, "revenue_vs_target_gap_pct", cal.month(2026, 7), {"region": ["R1"]}).total
    assert gap == pytest.approx(actual - target, abs=0.01)
    assert gap_pct == pytest.approx((actual - target) / target * 100, abs=0.001)


def test_empty_grouped_result_has_no_rows(db):
    r = compute_metric(db, "net_revenue", cal.month(2026, 9), {"region": ["R9"]}, ["channel"])
    assert r.values == {}
