"""A fake LLM transport for tests: scripted replies, failures and a call log.

The transport works out which agent is calling from the system prompt. Each
agent has a queue of scripted replies; when a queue is empty, a sensible
default is used (the orchestrator echoes the deterministic parser's spec,
the writer repeats the first fact line).
"""

import json
import re

from app.llm.gateway import PermanentLLMError, TransientLLMError

AGENT_BY_PROMPT = {
    "You are the orchestrator": "orchestrator",
    "You summarise regional managers": "context",
    "You write answers for the CFO": "writer",
}


def agent_of(messages: list[dict]) -> str:
    system = messages[0]["content"]
    return next(name for prefix, name in AGENT_BY_PROMPT.items() if system.startswith(prefix))


def _question(messages: list[dict]) -> str:
    m = re.search(r"QUESTION:\n(.+?)(?:\n\n|$)", messages[1]["content"], re.S)
    return m.group(1).strip() if m else ""


def default_reply(agent: str, messages: list[dict]) -> str:
    if agent == "orchestrator":
        from app.agents.common import coverage_for
        from app.agents.orchestrator import rule_spec
        from app.tools.sql import ReadOnlyDB

        db = ReadOnlyDB()
        try:
            spec = rule_spec(_question(messages), coverage_for(db))
        finally:
            db.close()
        return spec.model_dump_json()
    if agent == "context":
        return json.dumps({"summary": "The manager describes the month in the note."})
    prompt = messages[1]["content"]
    head = re.search(r"^HEADLINE[^:]*: (.+)$", prompt, re.M)
    if head:
        answer = f"{head.group(1)}."
    else:
        first = re.search(r"^F\d+ \| (.+?) \| (.+)$", prompt, re.M)
        answer = f"{first.group(1)}: {first.group(2)}."
    if "-> disagrees" in prompt:
        answer += " The manager's note disagrees with the tables, which are the source of truth."
    return json.dumps({"answer": answer})


class FakeLLM:
    def __init__(self, script: dict[str, list] | None = None):
        # script: agent -> list of replies; a reply is a str (JSON text) or an Exception to raise
        self.script = {k: list(v) for k, v in (script or {}).items()}
        self.calls: list[dict] = []

    def __call__(self, provider: str, model: str, messages: list[dict]) -> tuple[str, dict]:
        agent = agent_of(messages)
        self.calls.append({"agent": agent, "provider": provider, "model": model, "messages": messages})
        queue = self.script.get(agent, [])
        reply = queue.pop(0) if queue else default_reply(agent, messages)
        if isinstance(reply, Exception):
            raise reply
        return reply, {"input_tokens": 100, "output_tokens": 20}

    def agents_called(self) -> list[str]:
        return [c["agent"] for c in self.calls]


def rate_limited(retry_after: float = 0.0) -> TransientLLMError:
    return TransientLLMError("429 Too Many Requests", 429, retry_after)


def outage() -> TransientLLMError:
    return TransientLLMError("503 Service Unavailable", 503)


def bad_key() -> PermanentLLMError:
    return PermanentLLMError("401 invalid api key")
