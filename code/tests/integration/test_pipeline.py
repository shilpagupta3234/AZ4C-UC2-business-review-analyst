"""The whole graph on the real data, with a scripted fake LLM.

Covers Part A and B behaviour: routing, checked and retried agent answers,
send-backs, failures, approval pause and resume, untrusted documents.
"""

import json

import pytest

from app import config
from app.agents import data_analyst as da
from app.agents.state import QuerySpec
from app.runner import RunNotFound, pending_runs, resume_run, start_run
from app.tools.sql import SQLExecutionError
from tests.fakes import outage, rate_limited

S01 = "What was South's gross margin in August 2026?"


def run(question: str, auto: bool = True, case_id: str = "IT-01") -> dict:
    return start_run({"case_id": case_id, "input": {"question": question}}, auto)


def wrong_period_spec() -> str:
    return QuerySpec(
        question_type="value", metrics=["gross_margin_pct"], periods=["September 2026"], regions=["South"]
    ).model_dump_json()


# ---------- model path, routing and cost ----------


def test_models_plan_and_write_when_they_answer_well(default_fake_llm):
    r = run(S01)
    assert r["plan"]["source"] == "llm"
    assert r["answer_source"] == "llm"
    assert default_fake_llm.agents_called() == ["orchestrator", "writer"]
    assert r["figures"]["South gross margin %, August 2026"] == pytest.approx(34.67, abs=0.01)
    assert r["model_calls"]["count"] == 2


def test_unanswerable_question_costs_one_model_call(default_fake_llm):
    r = run("What was gross margin by salesperson for North in June 2026?")
    assert (r["decision"], r["reason_code"], r["needs_human"]) == (
        "cannot_answer",
        "DATA_NOT_AVAILABLE",
        False,
    )
    assert default_fake_llm.agents_called() == ["orchestrator"]
    assert r["plan"]["team"] == ["definitions", "writer"]


def test_why_question_brings_in_variance_and_context(default_fake_llm):
    r = run("Why did South's margin drop in September 2026?")
    assert r["plan"]["team"] == ["definitions", "data_analyst", "variance", "context", "verifier", "writer"]
    assert default_fake_llm.agents_called() == ["orchestrator", "context", "writer"]


# ---------- agent answers are checked and retried ----------


def test_hallucinated_period_is_retried_then_replaced_by_rules(fake_llm):
    fake = fake_llm({"orchestrator": [wrong_period_spec(), wrong_period_spec()]})
    r = run(S01)
    assert r["plan"]["source"] == "rules"
    assert any("do not match" in n for n in r["plan"]["notes"])
    assert r["figures"]["South gross margin %, August 2026"] == pytest.approx(34.67, abs=0.01)
    assert fake.agents_called().count("orchestrator") == 2


def test_spec_corrected_on_retry_is_used(fake_llm):
    fake_llm({"orchestrator": [wrong_period_spec()]})  # second call falls back to a correct default
    assert run(S01)["plan"]["source"] == "llm"


def test_invented_number_in_answer_is_rejected(fake_llm):
    bad = json.dumps({"answer": "South gross margin, August 2026: 35.00%."})
    fake_llm({"writer": [bad, bad]})
    r = run(S01)
    assert r["answer_source"] == "template"
    assert "35.00%" not in r["answer"]
    assert "34.67%" in r["answer"]


def test_answer_fixed_on_rewrite_is_used(fake_llm):
    bad = json.dumps({"answer": "South gross margin, August 2026: 35.00%."})
    good = json.dumps({"answer": "South gross margin, August 2026: 34.67%."})
    fake_llm({"writer": [bad, good]})
    r = run(S01)
    assert (r["answer_source"], r["answer"]) == ("llm", "South gross margin, August 2026: 34.67%.")


def test_why_question_is_not_refused_for_data_it_does_not_ask_for(fake_llm):
    # Seen with a real model: it added marketing_spend to "explain" a margin drop.
    spec = QuerySpec(
        question_type="why",
        metrics=["gross_margin_pct"],
        periods=["September 2026"],
        regions=["South"],
        missing_data=["marketing_spend"],
    ).model_dump_json()
    fake_llm({"orchestrator": [spec, spec]})
    r = run("Why did South's margin drop in September 2026?")
    assert (r["decision"], r["plan"]["source"]) == ("answered", "rules")


def test_unknown_region_left_out_by_the_model_is_still_refused(fake_llm):
    # Seen with a real model: it dropped "Atlantis" and answered for the whole company.
    spec = QuerySpec(question_type="value", metrics=["net_revenue"], periods=["July 2026"]).model_dump_json()
    fake_llm({"orchestrator": [spec, spec]})
    r = run("What was net revenue for the Atlantis region in July 2026?")
    assert (r["decision"], r["needs_human"]) == ("cannot_answer", False)
    assert r["reason_code"] in ("DATA_NOT_AVAILABLE", "AMBIGUOUS_QUESTION")


def test_target_question_typed_as_why_still_leads_with_the_gap(fake_llm):
    spec = QuerySpec(
        question_type="why", metrics=["net_revenue"], periods=["July 2026"], regions=["Central"]
    ).model_dump_json()
    fake_llm({"orchestrator": [spec, spec]})
    r = run("Did Central meet its revenue target in July 2026?")
    assert r["plan"]["source"] == "rules"
    assert r["amount"] == pytest.approx(-277134.74, abs=1.0)
    assert "context" not in r["plan"]["team"]


# ---------- failures: rate limits, outages, bad tools ----------


def test_rate_limited_provider_falls_back_to_the_other(fake_llm):
    fake = fake_llm({"orchestrator": [rate_limited(120)]})
    r = run(S01)
    providers = [c["provider"] for c in fake.calls if c["agent"] == "orchestrator"]
    assert providers == ["groq", "gemini"]
    assert r["plan"]["source"] == "llm"


def test_total_model_outage_still_answers_from_rules_and_template(fake_llm):
    fake_llm({"orchestrator": [outage()] * 6, "writer": [outage()] * 6})
    r = run(S01)
    assert (r["plan"]["source"], r["answer_source"]) == ("rules", "template")
    assert r["decision"] == "answered"


def test_database_failure_is_reported_not_guessed(monkeypatch):
    def broken(*args, **kwargs):
        raise SQLExecutionError("database is locked")

    monkeypatch.setattr(da, "compute_metric", broken)
    r = run(S01)
    assert (r["decision"], r["reason_code"]) == ("cannot_answer", "DATA_NOT_AVAILABLE")
    assert "could not be read" in r["answer"]


# ---------- verifier sends work back (twice at most) ----------


def test_wrong_figure_is_sent_back_and_fixed(monkeypatch):
    def corrupt_first_attempt(facts, attempt):
        if attempt == 0:
            facts[0]["value"] += 5.0

    monkeypatch.setattr(da, "FAULT", corrupt_first_attempt)
    r = run(S01)
    assert r["verification"]["status"] == "passed"
    assert r["verification"]["send_backs"] == 1
    assert r["figures"]["South gross margin %, August 2026"] == pytest.approx(34.67, abs=0.01)


def test_figure_that_never_reconciles_is_not_reported(monkeypatch):
    def always_corrupt(facts, attempt):
        facts[0]["value"] += 5.0

    monkeypatch.setattr(da, "FAULT", always_corrupt)
    r = run(S01)
    assert (r["decision"], r["reason_code"]) == ("cannot_answer", "DATA_NOT_AVAILABLE")
    assert r["verification"]["send_backs"] == config.MAX_SEND_BACKS
    assert r["figures"] == {}
    trace = [json.loads(x) for x in config.TRACE_LOG_PATH.read_text(encoding="utf-8").splitlines()]
    assert sum(1 for e in trace if e["node"] == "data_analyst") == 1 + config.MAX_SEND_BACKS


# ---------- approval: pause, resume, reject, change ----------


def test_run_pauses_for_approval_and_saves_only_after_it():
    r = run(S01, auto=False, case_id="IT-AP")
    report = config.REPORT_STORE_DIR / "IT-AP.md"
    assert r["approval"]["status"] == "pending"
    assert not report.exists()
    assert [p["run_id"] for p in pending_runs()] == [r["trace_id"]]

    done = resume_run(r["trace_id"], "approve")
    assert done["approval"]["status"] == "approved"
    assert report.exists()
    assert "34.67%" in report.read_text(encoding="utf-8")
    audit = [json.loads(x) for x in config.QUERY_LOG_PATH.read_text(encoding="utf-8").splitlines()]
    assert {a["run_id"] for a in audit} == {r["trace_id"]}
    assert pending_runs() == []


def test_rejected_answer_writes_nothing():
    r = run(S01, auto=False, case_id="IT-RJ")
    done = resume_run(r["trace_id"], "reject", note="wrong region")
    assert done["approval"]["status"] == "rejected"
    assert not (config.REPORT_STORE_DIR / "IT-RJ.md").exists()
    assert not config.QUERY_LOG_PATH.exists()


def test_change_request_rewrites_and_asks_again(default_fake_llm):
    r = run(S01, auto=False, case_id="IT-CH")
    revised = resume_run(r["trace_id"], "change", note="Lead with the margin figure only.")
    assert revised["approval"]["status"] == "pending"
    last_writer_prompt = [c for c in default_fake_llm.calls if c["agent"] == "writer"][-1]["messages"][1][
        "content"
    ]
    assert "Lead with the margin figure only." in last_writer_prompt
    assert resume_run(r["trace_id"], "approve")["approval"]["status"] == "approved"


def test_refusals_need_no_approval():
    r = run("Delete the returns recorded in September 2026.", auto=False, case_id="IT-WR")
    assert (r["reason_code"], r["needs_human"]) == ("WRITE_REQUEST_REFUSED", False)
    assert r["approval"]["status"] == "not_required"
    assert (config.REPORT_STORE_DIR / "IT-WR.md").exists()


def test_unknown_run_id_is_an_error():
    with pytest.raises(RunNotFound):
        resume_run("no-such-run", "approve")


# ---------- untrusted documents and manager notes (RS4, RS9) ----------


def test_instruction_planted_in_a_note_is_removed_and_ignored():
    r = run("Why did North's gross margin change in September 2026?")
    assert r["figures"]["North gross margin %, September 2026"] == pytest.approx(34.55, abs=0.01)
    assert 35.0 not in r["figures"].values()
    trace = [json.loads(x) for x in config.TRACE_LOG_PATH.read_text(encoding="utf-8").splitlines()]
    ctx = next(e for e in trace if e["node"] == "context")
    assert ctx["removed_instructions"] >= 1


def test_note_that_disagrees_with_the_tables_is_called_out(fake_llm):
    fake_llm({"writer": [json.dumps({"answer": "no numbers here"})] * 2})
    r = run("Why did South's margin drop in September 2026?")
    assert "commentary/2026-09_south.md" in r["citations"]
    assert "reporting_standards.md#RS4" in r["citations"]
    assert "promotions" in r["citations"]
    assert "the tables disagree" in r["answer"]  # template path explains the disagreement


def test_margin_drivers_add_up_to_the_change():
    r = run("Why did South's margin drop in September 2026?")
    figs = r["figures"]
    change = figs["South gross margin % change, August 2026 to September 2026"]
    drivers = [v for k, v in figs.items() if "gross margin % change from" in k]
    assert len(drivers) == 5
    assert sum(drivers) == pytest.approx(change, abs=0.1)  # RS2
    promo = figs["South gross margin % change from promotional discounts, August 2026 to September 2026"]
    assert promo == min(drivers)


# ---------- result format ----------


def test_result_has_every_schema_field():
    schema = json.loads((config.REPO_DIR / "schema" / "result.schema.json").read_text(encoding="utf-8"))
    r = run(S01)
    for key in schema["required"]:
        assert key in r
    assert r["decision"] in schema["properties"]["decision"]["enum"]
    assert r["reason_code"] in schema["properties"]["reason_code"]["enum"]
    assert all(isinstance(v, float | int) for v in r["figures"].values())
    assert all(isinstance(q, str) for q in r["queries"])
