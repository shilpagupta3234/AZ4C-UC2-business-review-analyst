"""Orchestrator: the deterministic parser, the spec cross-check and team choice."""

from datetime import date

import pytest

from app.agents.orchestrator import check_spec, plan_team, rule_spec
from app.agents.state import QuerySpec
from app.tools.coverage import Coverage

COV = Coverage(
    first_date=date(2025, 4, 1),
    last_date=date(2026, 9, 30),
    target_months=("2025-04", "2026-09"),
    regions={"R1": "North", "R2": "South", "R3": "East", "R4": "West", "R5": "Central"},
    channels=("E-commerce", "General Trade", "Modern Trade"),
    categories=("Beverages", "Snacks"),
    brands=("Trail Crunch",),
    promotions={"PR-11": "Festive Saver"},
)


@pytest.mark.parametrize(
    ("question", "qtype", "metrics", "group_by"),
    [
        ("What was South's gross margin in August 2026?", "value", ["gross_margin_pct"], None),
        (
            "Which sales channel had the highest net revenue in Q1 FY27?",
            "ranking",
            ["net_revenue"],
            "channel",
        ),
        (
            "Which product category had the lowest gross margin in FY26?",
            "ranking",
            ["gross_margin_pct"],
            "category",
        ),
        ("Why did South's margin drop in September 2026?", "why", ["gross_margin_pct"], None),
        ("Did Central meet its revenue target in July 2026?", "vs_target", ["net_revenue"], None),
        ("Compare West's net revenue in July 2026 and August 2026.", "comparison", ["net_revenue"], None),
        ("Show the monthly net revenue trend for North in Q2 FY27.", "trend", ["net_revenue"], "month"),
        ("Show net revenue by channel for Central in Q2 FY27.", "breakdown", ["net_revenue"], "channel"),
        ("Update North's July 2026 revenue target to 6000000.", "write_request", ["net_revenue"], None),
        ("How did we do last month?", "unclear", [], None),
    ],
)
def test_rule_spec(question, qtype, metrics, group_by):
    spec = rule_spec(question, COV)
    assert (spec.question_type, spec.metrics, spec.group_by) == (qtype, metrics, group_by)


def test_rule_spec_finds_missing_data():
    assert rule_spec("What was gross margin by salesperson for North in June 2026?", COV).missing_data == [
        "salesperson"
    ]
    assert "marketing_spend" in rule_spec("East marketing spend in Q1 FY27", COV).missing_data


def test_sales_channel_is_not_salesperson():
    assert rule_spec("Which sales channel had the highest revenue in Q1 FY27?", COV).missing_data == []


def test_unknown_region_is_kept_for_the_gate():
    assert rule_spec("Net revenue for the Atlantis region in July 2026", COV).regions == ["Atlantis"]


def test_check_spec_catches_a_hallucinated_period():
    q = "What was South's gross margin in August 2026?"
    bad = QuerySpec(
        question_type="value", metrics=["gross_margin_pct"], periods=["September 2026"], regions=["South"]
    )
    assert any("periods" in e for e in check_spec(bad, q, rule_spec(q, COV)))


def test_check_spec_catches_region_and_metric_not_in_question():
    q = "What was South's gross margin in August 2026?"
    bad = QuerySpec(question_type="value", metrics=["ebitda"], periods=["August 2026"], regions=["North"])
    errors = check_spec(bad, q, rule_spec(q, COV))
    assert any("unknown metric" in e for e in errors)
    assert any("North" in e for e in errors)


def test_check_spec_catches_a_region_left_out():
    # The model drops a region it doesn't know, which would answer for the whole company.
    q = "What was net revenue for the Atlantis region in July 2026?"
    bad = QuerySpec(question_type="value", metrics=["net_revenue"], periods=["July 2026"])
    assert any("Atlantis" in e for e in check_spec(bad, q, rule_spec(q, COV)))


def test_check_spec_catches_missing_data_the_question_does_not_ask_for():
    # A "why" question must not be refused because the model thinks more data would help.
    q = "Why did South's margin drop in September 2026?"
    bad = rule_spec(q, COV).model_copy(update={"missing_data": ["marketing_spend"]})
    assert any("not asked for" in e for e in check_spec(bad, q, rule_spec(q, COV)))


def test_check_spec_accepts_missing_data_the_question_asks_for():
    q = "What was gross margin by salesperson for North in June 2026?"
    assert check_spec(rule_spec(q, COV), q, rule_spec(q, COV)) == []


@pytest.mark.parametrize(
    ("question", "model_type"),
    [
        ("Did Central meet its revenue target in July 2026?", "why"),
        ("Did Central meet its revenue target in July 2026?", "value"),
        ("Why did South's margin drop in September 2026?", "comparison"),
        ("What was South's gross margin in August 2026?", "why"),
    ],
)
def test_check_spec_catches_a_wrong_question_type(question, model_type):
    # Seen with a real model: a target question typed as "why" lost its headline figure.
    bad = rule_spec(question, COV).model_copy(update={"question_type": model_type})
    assert any("question_type" in e for e in check_spec(bad, question, rule_spec(question, COV)))


def test_check_spec_accepts_a_correct_spec():
    q = "What was South's gross margin in August 2026?"
    assert check_spec(rule_spec(q, COV), q, rule_spec(q, COV)) == []


def test_different_questions_get_different_teams():
    value = plan_team(rule_spec("South gross margin in August 2026", COV))["team"]
    why = plan_team(rule_spec("Why did South's margin drop in September 2026?", COV))["team"]
    target = plan_team(rule_spec("Did Central meet its revenue target in July 2026?", COV))["team"]
    refuse = plan_team(rule_spec("Delete the returns for September 2026", COV))["team"]
    assert value == ["definitions", "data_analyst", "verifier", "writer"]
    assert why == ["definitions", "data_analyst", "variance", "context", "verifier", "writer"]
    assert target == ["definitions", "data_analyst", "variance", "verifier", "writer"]
    assert refuse == ["definitions", "writer"]


def test_skipped_agents_are_explained():
    plan = plan_team(rule_spec("South gross margin in August 2026", COV))
    assert set(plan["skipped"]) == {"variance", "context"}
