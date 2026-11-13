"""Grounding check, template answers and the bridge arithmetic (RS2)."""

import pytest

from app.agents.variance import margin_bridge, margin_steps, revenue_bridge
from app.agents.writer import allowed_numbers, template_answer, ungrounded

FACTS = [
    {
        "id": "F1",
        "label": "South gross margin %, August 2026",
        "unit": "PCT",
        "value": 34.6721,
        "role": "value",
    },
    {
        "id": "F2",
        "label": "South net revenue, August 2026",
        "unit": "INR",
        "value": 5727515.754,
        "role": "value",
    },
    {"id": "F3", "label": "South gross margin % change", "unit": "PP", "value": -14.4234, "role": "derived"},
]


def test_grounded_text_passes():
    text = (
        "South gross margin, August 2026: 34.67%. Net revenue was \u20b95,727,515.75; "
        "margin fell -14.42 pp in Q2 FY27."
    )
    assert ungrounded(text, allowed_numbers(FACTS, None)) == []


def test_invented_number_is_caught():
    assert ungrounded("South gross margin, August 2026: 35%.", allowed_numbers(FACTS, None)) == ["35"]
    assert ungrounded("Revenue grew 12.5%.", allowed_numbers(FACTS, None)) == ["12.5"]


def test_years_quarters_and_small_counts_are_not_figures():
    assert ungrounded("In Q2 FY27 and 2026, the top 3 regions over 2 months.", []) == []


def test_numbers_claimed_in_notes_may_be_quoted():
    ctx = {"claim_checks": [{"claimed": 11.0}]}
    assert ungrounded("The note says revenue was up about 11%.", allowed_numbers(FACTS, ctx)) == []


def test_template_never_invents_numbers():
    state = {"decision": "answered", "facts": FACTS, "headline": "F1", "resolved": {}}
    text = template_answer(state)
    assert "34.67%" in text
    assert ungrounded(text, allowed_numbers(FACTS, None)) == []


def test_refusal_template_uses_the_reason():
    state = {"decision": "cannot_answer", "reason_detail": "No data for December 2026."}
    assert template_answer(state) == "No data for December 2026."


def _inputs(promo=0.0, damaged=0.0, refunds=0.0, cost=600.0):
    gross, trade = 1000.0, 40.0
    return {
        "gross_sales": gross,
        "discounts": trade + promo,
        "promotion_cost": promo,
        "line_net_revenue": gross - trade - promo,
        "line_cogs": cost,
        "refunds": refunds + damaged,
        "refunds_damaged": damaged,
        "cogs_reversed": refunds * 0.6,
        "units": 10,
    }


def test_margin_steps_end_at_reported_margin():
    v = _inputs(promo=150, damaged=30, refunds=20)
    nr = v["line_net_revenue"] - v["refunds"]
    nc = v["line_cogs"] - v["cogs_reversed"]
    assert margin_steps(v)["actual"] == pytest.approx((nr - nc) / nr * 100)


def test_margin_bridge_drivers_add_up_exactly():
    b = margin_bridge(_inputs(), _inputs(promo=150, damaged=30, refunds=20, cost=610))
    assert sum(b["drivers"].values()) == pytest.approx(b["change"], abs=1e-9)
    assert b["drivers"]["promo_discounts"] < 0
    assert b["drivers"]["damaged_returns"] < 0


def test_promotion_shows_up_as_the_promotion_driver():
    b = margin_bridge(_inputs(), _inputs(promo=150))
    biggest = min(b["drivers"], key=b["drivers"].get)
    assert biggest == "promo_discounts"
    assert abs(b["drivers"]["product_cost"]) < 1e-9


def test_revenue_bridge_drivers_add_up_exactly():
    b = revenue_bridge(_inputs(), _inputs(promo=150, damaged=30, refunds=20))
    assert sum(b["drivers"].values()) == pytest.approx(b["change"], abs=1e-9)
