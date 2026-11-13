"""LLM gateway: retries, rate limits, provider fallback, budgets and the call log."""

import json

from pydantic import BaseModel

from app import config
from app.llm.gateway import LLMGateway, _extract_json
from tests.fakes import FakeLLM, bad_key, outage, rate_limited

SYSTEM = "You write answers for the CFO"


class Out(BaseModel):
    answer: str


def make(script, **kw):
    fake = FakeLLM({"writer": script})
    return LLMGateway("run-1", transport=fake, sleep=lambda s: None, require_keys=False, **kw), fake


def test_valid_reply_on_first_try():
    gw, fake = make(['{"answer": "ok"}'])
    assert gw.json_call("specialist", "writer", SYSTEM, "q", Out).answer == "ok"
    assert [c["status"] for c in gw.calls] == ["ok"]
    assert fake.calls[0]["provider"] == "gemini"  # specialists start on Gemini


def test_bad_reply_is_sent_back_with_the_error():
    gw, fake = make(["not json at all", '{"answer": "fixed"}'])
    assert gw.json_call("specialist", "writer", SYSTEM, "q", Out).answer == "fixed"
    assert [c["status"] for c in gw.calls] == ["invalid_reply", "ok"]
    assert "not valid" in fake.calls[1]["messages"][-1]["content"]


def test_schema_mismatch_counts_as_bad_reply():
    gw, _ = make(['{"wrong_key": 1}', '{"answer": "fixed"}'])
    assert gw.json_call("specialist", "writer", SYSTEM, "q", Out).answer == "fixed"


def test_rate_limit_waits_and_retries():
    waits = []
    fake = FakeLLM({"writer": [rate_limited(1.5), '{"answer": "ok"}']})
    gw = LLMGateway("run-1", transport=fake, sleep=waits.append, require_keys=False)
    assert gw.json_call("specialist", "writer", SYSTEM, "q", Out).answer == "ok"
    assert waits == [1.5]  # honours retry-after
    assert [c["status"] for c in gw.calls] == ["rate_limited", "ok"]


def test_long_rate_limit_switches_provider_instead_of_waiting():
    gw, fake = make([rate_limited(120), '{"answer": "from groq"}'])
    assert gw.json_call("specialist", "writer", SYSTEM, "q", Out).answer == "from groq"
    assert [c["provider"] for c in fake.calls] == ["gemini", "groq"]


def test_rate_limited_provider_rests_for_later_calls():
    now = [0.0]
    fake = FakeLLM({"writer": [rate_limited(120), '{"answer": "a"}', '{"answer": "b"}', '{"answer": "c"}']})
    gw = LLMGateway("run-1", transport=fake, sleep=lambda s: None, require_keys=False, clock=lambda: now[0])
    gw.json_call("specialist", "writer", SYSTEM, "q", Out)
    gw.json_call("specialist", "writer", SYSTEM, "q", Out)
    assert [c["provider"] for c in fake.calls] == ["gemini", "groq", "groq"]  # Gemini skipped, not retried
    assert [c["status"] for c in gw.calls] == ["rate_limited", "ok", "ok"]  # rests don't use the budget
    now[0] = 121.0
    gw.json_call("specialist", "writer", SYSTEM, "q", Out)
    assert fake.calls[-1]["provider"] == "gemini"  # back after the rest


def test_three_short_rate_limits_also_rest_the_provider():
    gw, fake = make([rate_limited(1), rate_limited(1), rate_limited(1), '{"answer": "x"}', '{"answer": "y"}'])
    gw.json_call("specialist", "writer", SYSTEM, "q", Out)
    gw.json_call("specialist", "writer", SYSTEM, "q", Out)
    assert [c["provider"] for c in fake.calls] == ["gemini"] * 3 + ["groq", "groq"]


def test_outage_falls_back_to_other_provider():
    gw, fake = make([outage(), outage(), outage(), '{"answer": "from groq"}'])
    assert gw.json_call("specialist", "writer", SYSTEM, "q", Out).answer == "from groq"
    assert fake.calls[-1]["provider"] == "groq"


def test_permanent_error_moves_on_immediately():
    gw, fake = make([bad_key(), '{"answer": "from groq"}'])
    assert gw.json_call("specialist", "writer", SYSTEM, "q", Out).answer == "from groq"
    assert len(fake.calls) == 2


def test_everything_failing_returns_none():
    gw, _ = make(["x", "y", "z", "w"])
    assert gw.json_call("specialist", "writer", SYSTEM, "q", Out) is None


def test_call_budget_stops_runaway_runs():
    gw, fake = make(["x"] * 10, max_calls=3)
    assert gw.json_call("specialist", "writer", SYSTEM, "q", Out) is None
    assert len(fake.calls) == 3


def test_no_keys_means_no_calls(monkeypatch):
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    fake = FakeLLM()
    gw = LLMGateway("run-1", transport=fake)
    assert gw.json_call("specialist", "writer", SYSTEM, "q", Out) is None
    assert fake.calls == []


def test_every_attempt_is_logged():
    gw, _ = make(["bad", '{"answer": "ok"}'])
    gw.json_call("specialist", "writer", SYSTEM, "q", Out)
    lines = [json.loads(x) for x in config.LLM_LOG_PATH.read_text(encoding="utf-8").splitlines()]
    assert [x["status"] for x in lines] == ["invalid_reply", "ok"]
    assert {"run_id", "node", "provider", "model", "latency_ms", "input_tokens", "output_tokens"} <= set(
        lines[0]
    )


def test_extract_json_tolerates_fences_and_text():
    assert _extract_json('Here:\n```json\n{"a": 1}\n```') == {"a": 1}
    assert _extract_json('sure {"a": 2} done') == {"a": 2}
