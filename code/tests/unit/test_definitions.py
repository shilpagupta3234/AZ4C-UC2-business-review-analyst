"""The answerability gate: RS5, RS6, RS7 and data coverage."""

import pytest

from app.agents.definitions import gate
from app.agents.orchestrator import rule_spec
from tests.unit.test_orchestrator import COV


def run_gate(question: str) -> dict:
    return gate(rule_spec(question, COV).model_dump(), question, COV)


@pytest.mark.parametrize(
    ("question", "code"),
    [
        ("Update North's July 2026 revenue target to 6000000.", "WRITE_REQUEST_REFUSED"),
        ("Please delete the returns recorded in September 2026.", "WRITE_REQUEST_REFUSED"),
        ("What was gross margin by salesperson for North in June 2026?", "DATA_NOT_AVAILABLE"),
        ("What are South's inventory levels in September 2026?", "DATA_NOT_AVAILABLE"),
        ("What was gross margin in December 2026?", "DATA_NOT_AVAILABLE"),
        ("What was net revenue in March 2025?", "DATA_NOT_AVAILABLE"),
        ("What was net revenue for the Atlantis region in July 2026?", "DATA_NOT_AVAILABLE"),
        ("Did West hit its revenue target by channel in July 2026?", "DATA_NOT_AVAILABLE"),
        ("How did we do last month?", "AMBIGUOUS_QUESTION"),
        ("What was margin in August?", "AMBIGUOUS_QUESTION"),
        ("What was net revenue last quarter?", "AMBIGUOUS_QUESTION"),
    ],
)
def test_gate_refuses(question, code):
    out = run_gate(question)
    assert (out["decision"], out["reason_code"]) == ("cannot_answer", code)
    assert out["reason_detail"]


def test_write_refusal_says_who_can_change_it():
    assert "CFO's office" in run_gate("Set South's August 2026 target to 1")["reason_detail"]


def test_missing_data_is_named():
    assert "salesperson" in run_gate("Gross margin by salesperson for North in June 2026")["reason_detail"]


def test_answerable_question_is_resolved_to_ids_and_dates():
    out = run_gate("What was South's gross margin in August 2026?")
    assert out["decision"] == "answered"
    r = out["resolved"]
    assert r["region_ids"] == ["R2"]
    assert r["periods"] == [
        {"label": "August 2026", "start": "2026-08-01", "end": "2026-08-31", "grain": "month"}
    ]
    assert "metric_definitions.md#M5" in r["citations"]


def test_quarter_resolves_with_finance_calendar():
    r = run_gate("Which sales channel had the highest net revenue in Q1 FY27?")["resolved"]
    assert (r["periods"][0]["start"], r["periods"][0]["end"]) == ("2026-04-01", "2026-06-30")
