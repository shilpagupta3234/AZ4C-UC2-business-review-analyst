"""Small helpers shared by the agents: formatting, trace events, tool access."""

from datetime import UTC, datetime

from ..llm.gateway import LLMGateway
from ..tools.sql import QueryLog, ReadOnlyDB

# Tests replace this with a fake transport (see tests/fakes.py).
TRANSPORT_OVERRIDE = None


def gateway(state: dict) -> LLMGateway:
    if TRANSPORT_OVERRIDE is not None:
        return LLMGateway(
            state["run_id"], transport=TRANSPORT_OVERRIDE, sleep=lambda s: None, require_keys=False
        )
    return LLMGateway(state["run_id"])


def open_db(state: dict) -> ReadOnlyDB:
    """A read-only connection whose query ids continue from earlier nodes in this run."""
    return ReadOnlyDB(log=QueryLog(offset=len(state.get("queries", []))))


_COVERAGE_CACHE: dict = {}


def coverage_for(db: ReadOnlyDB):
    """Data coverage, read once per process and data file (it cannot change mid-run)."""
    from .. import config
    from ..tools.coverage import data_coverage

    key = (str(config.DB_PATH), config.DB_PATH.stat().st_mtime)
    if key not in _COVERAGE_CACHE:
        _COVERAGE_CACHE[key] = data_coverage(db)
    return _COVERAGE_CACHE[key]


def query_records(db: ReadOnlyDB, purpose: str) -> list[dict]:
    from dataclasses import asdict

    return [{**asdict(r), "purpose": purpose} for r in db.log.records]


def event(node: str, message: str, **detail) -> dict:
    return {"ts": datetime.now(UTC).isoformat(timespec="seconds"), "node": node, "event": message, **detail}


def fmt(value: float | None, unit: str) -> str:
    """RS8: rupees and percentages to 2 decimal places."""
    if value is None:
        return "n/a"
    if unit == "INR":
        sign = "-" if value < 0 else ""
        return f"{sign}\u20b9{abs(value):,.2f}"  # \u20b9 is the rupee sign
    if unit == "PP":
        return f"{value:+.2f} pp"
    if unit == "UNITS":
        return f"{value:,.0f} units"
    return f"{value:.2f}%"
