"""Metric registry and SQL compiler: the SQL itself, without running it."""

import pytest

from app.semantic import calendar as cal
from app.semantic.compiler import NotAvailable, compile_measure
from app.semantic.metrics import MEASURES, METRICS
from app.tools.sql import check_sql


def test_every_metric_uses_known_measures_and_cites_a_definition():
    for metric in METRICS.values():
        assert set(metric.measures) <= set(MEASURES), metric.id
        assert metric.doc_ref.startswith("metric_definitions.md#M"), metric.id


def test_margin_formula():
    v = {"line_net_revenue": 1000.0, "refunds": 100.0, "line_cogs": 600.0, "cogs_reversed": 50.0}
    # net revenue 900, net cogs 550 -> (900 - 550) / 900 * 100
    assert METRICS["gross_margin_pct"].formula(v) == pytest.approx(38.888, abs=0.001)


def test_margin_with_zero_revenue_is_none_not_an_error():
    v = {"line_net_revenue": 0.0, "refunds": 0.0, "line_cogs": 0.0, "cogs_reversed": 0.0}
    assert METRICS["gross_margin_pct"].formula(v) is None


def test_damaged_returns_reduce_revenue_but_keep_cost():
    # A damaged return: refund 100, cogs_reversed 0 (M4).
    base = {"line_net_revenue": 1000.0, "line_cogs": 600.0, "cogs_reversed": 0.0}
    no_return = METRICS["gross_margin_pct"].formula({**base, "refunds": 0.0})
    damaged = METRICS["gross_margin_pct"].formula({**base, "refunds": 100.0})
    assert damaged < no_return


def test_refunds_are_dated_by_return_date_and_region_by_order():
    q = compile_measure("refunds", cal.month(2026, 8), {"region": ["R2"]})
    assert "r.return_date BETWEEN ? AND ?" in q.sql
    assert "o.region_id IN (?)" in q.sql
    assert q.params == ("2026-08-01", "2026-08-31", "R2")


def test_order_lines_are_dated_by_order_date():
    q = compile_measure("line_net_revenue", cal.month(2026, 8))
    assert "o.order_date BETWEEN ? AND ?" in q.sql


def test_values_are_bound_never_inlined():
    q = compile_measure("refunds", cal.month(2026, 8), {"region": ["R2"]})
    assert "R2" not in q.sql
    assert "2026-08-01" not in q.sql


def test_channel_grouping_joins_customers_and_cites_it():
    q = compile_measure("line_net_revenue", cal.quarter(1, 2027), group_by=["channel"])
    assert "JOIN customers c" in q.sql
    assert "GROUP BY c.channel" in q.sql
    assert "customers" in q.tables


def test_targets_use_month_strings():
    q = compile_measure("revenue_target", cal.quarter(2, 2027), {"region": ["R1"]})
    assert q.params == ("2026-07", "2026-09", "R1")


@pytest.mark.parametrize(
    ("measure", "dim"),
    [("revenue_target", "channel"), ("revenue_target", "product"), ("freight", "product")],
)
def test_cuts_the_data_does_not_support(measure, dim):
    with pytest.raises(NotAvailable):
        compile_measure(measure, cal.month(2026, 7), group_by=[dim])


def test_every_compiled_query_passes_the_sql_guard():
    p = cal.month(2026, 7)
    for measure_id in MEASURES:
        q = compile_measure(measure_id, p, {"region": ["R1"]}, ["month"])
        check_sql(q.sql)
