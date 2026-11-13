"""One gateway for every model call: retries, rate limits, fallback, logging.

Each role has a primary and a fallback model on different providers:
  orchestrator: Groq -> Gemini        specialist: Gemini -> Groq

Every reply must be JSON that validates against a Pydantic model. A bad reply
is sent back once with the validation error; a rate limit or timeout is
retried with backoff; after that the next provider is tried. A provider that
keeps rate-limiting is rested for a while (shared by every run in the
process), so later calls go straight to the other provider. If nothing
works the gateway returns None and the caller uses its deterministic
fallback, so a run never guesses a number because a model failed.

Every attempt, good or bad, is one line in logs/llm_calls.jsonl.
"""

import json
import os
import re
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import TypeVar

from pydantic import BaseModel, ValidationError

from .. import config

T = TypeVar("T", bound=BaseModel)


class TransientLLMError(Exception):
    """Rate limit, timeout or server error: worth retrying."""

    def __init__(self, message: str, status: int | None = None, retry_after: float | None = None):
        super().__init__(message)
        self.status = status
        self.retry_after = retry_after


class PermanentLLMError(Exception):
    """Bad key, unknown model, bad request: move to the next provider."""


@dataclass
class Route:
    provider: str  # groq | gemini
    model: str


# transport(provider, model, messages) -> (reply_text, {"input_tokens": n, "output_tokens": n})
Transport = Callable[[str, str, list[dict]], tuple[str, dict]]

_PROVIDERS = {
    "groq": ("GROQ_API_KEY", "GROQ_BASE_URL", "/openai/v1"),
    "gemini": ("GEMINI_API_KEY", "GEMINI_BASE_URL", "/v1beta/openai/"),
}


# provider -> monotonic time until which it is skipped after repeated rate limits
_COOLDOWN_UNTIL: dict[str, float] = {}


def routes_for(role: str) -> list[Route]:
    if role == "orchestrator":
        return [Route("groq", config.ORCHESTRATOR_MODEL), Route("gemini", config.ORCHESTRATOR_FALLBACK_MODEL)]
    return [Route("gemini", config.SPECIALIST_MODEL), Route("groq", config.SPECIALIST_FALLBACK_MODEL)]


def provider_configured(provider: str) -> bool:
    key_var, _, _ = _PROVIDERS[provider]
    return bool(os.environ.get(key_var, "").strip())


def openai_transport(provider: str, model: str, messages: list[dict]) -> tuple[str, dict]:
    """Calls Groq or Gemini through their OpenAI-compatible endpoints."""
    import openai  # imported here so tests and offline runs never need it

    key_var, url_var, suffix = _PROVIDERS[provider]
    client = openai.OpenAI(
        api_key=os.environ[key_var],
        base_url=os.environ.get(url_var, "").rstrip("/") + suffix,
        timeout=config.LLM_TIMEOUT_S,
        max_retries=0,  # retries are handled here, once, for both providers
    )
    try:
        resp = client.chat.completions.create(
            model=model, messages=messages, temperature=0, response_format={"type": "json_object"}
        )
    except openai.RateLimitError as e:
        retry_after = e.response.headers.get("retry-after") if e.response is not None else None
        raise TransientLLMError(str(e), 429, float(retry_after) if retry_after else None) from e
    except (openai.APITimeoutError, openai.APIConnectionError, openai.InternalServerError) as e:
        raise TransientLLMError(str(e), getattr(e, "status_code", None)) from e
    except openai.APIStatusError as e:
        raise PermanentLLMError(f"{e.status_code}: {e}") from e
    usage = resp.usage
    return resp.choices[0].message.content or "", {
        "input_tokens": getattr(usage, "prompt_tokens", 0) or 0,
        "output_tokens": getattr(usage, "completion_tokens", 0) or 0,
    }


def _extract_json(text: str) -> dict:
    """Parse a JSON object, tolerating code fences or text around it."""
    text = text.strip()
    fenced = re.search(r"```(?:json)?\s*(\{.*\})\s*```", text, re.S)
    if fenced:
        text = fenced.group(1)
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end <= start:
        raise ValueError("no JSON object in reply")
    return json.loads(text[start : end + 1])


def _cost_usd(model: str, usage: dict) -> float | None:
    price = config.PRICES_PER_M_TOKENS.get(model)
    if price is None:
        return None
    return round(
        (usage.get("input_tokens", 0) * price[0] + usage.get("output_tokens", 0) * price[1]) / 1e6, 6
    )


@dataclass
class LLMGateway:
    run_id: str
    transport: Transport = openai_transport
    sleep: Callable[[float], None] = time.sleep
    max_calls: int = config.LLM_MAX_CALLS_PER_RUN
    calls: list[dict] = field(default_factory=list)  # this run's call log, also kept in run state
    require_keys: bool = True  # tests with a fake transport set this to False
    clock: Callable[[], float] = time.monotonic

    def json_call(self, role: str, node: str, system: str, user: str, schema: type[T]) -> T | None:
        """Ask for JSON matching schema. Returns None when no model gives a valid reply."""
        for route in routes_for(role):
            if self.require_keys and not provider_configured(route.provider):
                self._log(node, route, 0, "skipped", 0.0, {}, "no API key configured")
                continue
            rest = _COOLDOWN_UNTIL.get(route.provider, 0.0) - self.clock()
            if rest > 0:
                self._log(node, route, 0, "cooling_down", 0.0, {}, f"rate-limited, resting {rest:.0f}s more")
                continue
            result = self._try_route(node, route, system, user, schema)
            if result is not None:
                return result
        return None

    def _try_route(self, node: str, route: Route, system: str, user: str, schema: type[T]) -> T | None:
        messages = [{"role": "system", "content": system}, {"role": "user", "content": user}]
        bad_replies, transient_failures, attempt = 0, 0, 0
        while bad_replies < 2 and transient_failures < 3:
            if len(self.calls) >= self.max_calls:
                self._log(node, route, attempt, "budget_exceeded", 0.0, {}, f"max {self.max_calls} calls/run")
                return None
            attempt += 1
            started = time.perf_counter()
            try:
                text, usage = self.transport(route.provider, route.model, messages)
            except TransientLLMError as e:
                transient_failures += 1
                status = "rate_limited" if e.status == 429 else "transient_error"
                self._log(node, route, attempt, status, started, {}, str(e)[:300])
                wait = e.retry_after if e.retry_after is not None else 2 ** (transient_failures - 1)
                if e.status == 429 and (wait > config.LLM_MAX_RATE_LIMIT_WAIT_S or transient_failures >= 3):
                    # Rest this provider so the next calls don't spend time and budget on it.
                    rest_for = max(wait, config.LLM_RATE_LIMIT_COOLDOWN_S)
                    _COOLDOWN_UNTIL[route.provider] = self.clock() + rest_for
                    return None
                if wait > config.LLM_MAX_RATE_LIMIT_WAIT_S:
                    return None  # waiting this long is worse than switching provider
                self.sleep(wait)
                continue
            except PermanentLLMError as e:
                self._log(node, route, attempt, "error", started, {}, str(e)[:300])
                return None
            try:
                parsed = schema.model_validate(_extract_json(text))
            except (ValueError, ValidationError) as e:
                bad_replies += 1
                self._log(node, route, attempt, "invalid_reply", started, usage, str(e)[:300])
                messages += [
                    {"role": "assistant", "content": text[:2000]},
                    {
                        "role": "user",
                        "content": f"That reply was not valid: {str(e)[:500]}. "
                        "Reply again with only the JSON object.",
                    },
                ]
                continue
            self._log(node, route, attempt, "ok", started, usage, None)
            return parsed
        return None

    def _log(
        self,
        node: str,
        route: Route,
        attempt: int,
        status: str,
        started: float,
        usage: dict,
        error: str | None,
    ) -> None:
        entry = {
            "ts": datetime.now(UTC).isoformat(timespec="seconds"),
            "run_id": self.run_id,
            "node": node,
            "provider": route.provider,
            "model": route.model,
            "attempt": attempt,
            "status": status,
            "latency_ms": round((time.perf_counter() - started) * 1000, 1) if started else 0.0,
            "input_tokens": usage.get("input_tokens", 0),
            "output_tokens": usage.get("output_tokens", 0),
            "cost_usd": _cost_usd(route.model, usage),
            "error": error,
        }
        if status not in ("skipped", "cooling_down"):
            self.calls.append(entry)  # only real attempts count toward the run's budget
        config.LOG_DIR.mkdir(parents=True, exist_ok=True)
        with config.LLM_LOG_PATH.open("a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
