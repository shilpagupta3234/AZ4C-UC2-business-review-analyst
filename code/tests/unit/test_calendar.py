"""Finance calendar rules from docs/finance_calendar.md."""

from datetime import date

import pytest

from app.semantic import calendar as cal


def test_quarters_follow_finance_calendar():
    q1 = cal.quarter(1, 2027)
    assert (q1.start, q1.end) == (date(2026, 4, 1), date(2026, 6, 30))
    assert cal.quarter(2, 2027).months() == ["2026-07", "2026-08", "2026-09"]


def test_q4_falls_in_the_calendar_year_the_fy_ends():
    q4 = cal.quarter(4, 2026)
    assert (q4.start, q4.end) == (date(2026, 1, 1), date(2026, 3, 31))


def test_fiscal_year_named_after_end_year():
    fy26 = cal.fiscal_year(2026)
    assert (fy26.start, fy26.end, fy26.label) == (date(2025, 4, 1), date(2026, 3, 31), "FY26")
    assert len(fy26.months()) == 12


def test_month_handles_leap_year():
    assert cal.month(2028, 2).end == date(2028, 2, 29)


def test_invalid_quarter_rejected():
    with pytest.raises(ValueError, match="quarter must be 1-4"):
        cal.quarter(5, 2027)


@pytest.mark.parametrize(
    ("text", "label"),
    [
        ("What was South's gross margin in August 2026?", "August 2026"),
        ("net revenue in Sept 2026", "September 2026"),
        ("revenue for 2026-07", "July 2026"),
        ("highest net revenue in Q1 FY27", "Q1 FY27"),
        ("Q2 FY2027 revenue", "Q2 FY27"),
        ("total for FY26", "FY26"),
    ],
)
def test_parse_periods(text, label):
    assert [p.label for p in cal.parse_periods(text)] == [label]


def test_parse_two_periods_in_order():
    ps = cal.parse_periods("Compare July 2026 with August 2026")
    assert [p.label for p in ps] == ["July 2026", "August 2026"]


def test_quarter_is_not_also_read_as_a_fiscal_year():
    assert [p.grain for p in cal.parse_periods("Q1 FY27")] == ["quarter"]


@pytest.mark.parametrize("text", ["What was margin in August?", "revenue last month", "sales this quarter"])
def test_unclear_period_is_not_guessed(text):
    assert cal.parse_periods(text) == []


def test_previous_period():
    assert cal.previous(cal.month(2026, 1)).label == "December 2025"
    assert cal.previous(cal.quarter(1, 2027)).label == "Q4 FY26"
    assert cal.previous(cal.quarter(3, 2027)).label == "Q2 FY27"
    assert cal.previous(cal.fiscal_year(2027)).label == "FY26"
