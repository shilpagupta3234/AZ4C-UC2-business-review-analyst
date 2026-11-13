"""The result (schema/result.schema.json) and the writes to mock_system/.

Writes happen only after the decision is final: approved by a person, or
auto-approved, or a refusal that needs no approval. A rejected run writes
nothing. Files are written atomically (temp file, then rename), so a crash
never leaves a half-written report.
"""

import json
import os
import tempfile
from datetime import UTC, datetime
from pathlib import Path

from . import config
from .agents.common import fmt

_SKIP_IN_FIGURES = {"support"}


def figures(state: dict) -> dict[str, float]:
    out = {}
    for f in state.get("facts", []):
        if f.get("value") is None or (f["role"] in _SKIP_IN_FIGURES and f["unit"] == "UNITS"):
            continue
        out[f["label"]] = round(f["value"], 2)
    return out


def amount(state: dict) -> float | None:
    """The rupee amount the answer is about: the headline figure, if it is in rupees."""
    if state.get("decision") != "answered":
        return None
    head = next((f for f in state.get("facts", []) if f["id"] == state.get("headline")), None)
    if head is None or head["unit"] != "INR" or head["value"] is None:
        return None
    return round(head["value"], 2)


def citations(state: dict) -> list[str]:
    cites: list[str] = []
    for f in state.get("facts", []):
        cites += f.get("tables", [])
    cites += state.get("variance", {}).get("tables", [])
    cites += state.get("resolved", {}).get("citations", [])
    ctx = state.get("context") or {}
    for doc in ctx.get("documents", []):
        cites.append(doc["doc_id"])
        if doc["doc_id"].startswith("promo_briefs/"):
            cites.append(Path(doc["doc_id"]).stem)
    if any(c["verdict"] == "disagrees" for c in ctx.get("claim_checks", [])):
        cites.append("reporting_standards.md#RS4")
    if state.get("variance", {}).get("bridges"):
        cites.append("reporting_standards.md#RS2")
    return list(dict.fromkeys(cites))


def build_result(state: dict) -> dict:
    answered = state.get("decision") == "answered"
    calls = state.get("model_calls", [])
    return {
        "case_id": state["case_id"],
        "decision": state.get("decision", "cannot_answer"),
        "reason_code": state.get("reason_code", "DATA_NOT_AVAILABLE"),
        "amount": amount(state),
        "citations": citations(state),
        "needs_human": answered,
        "trace_id": state["run_id"],
        "answer": state.get("answer", ""),
        "answer_source": state.get("writer_source", ""),
        "figures": figures(state) if answered else {},
        "queries": [q["rendered"] for q in state.get("queries", [])],
        "plan": state.get("plan", {}),
        "verification": state.get("verification", {}),
        "approval": state.get("approval", {"status": "not_required" if not answered else "pending"}),
        "model_calls": {
            "count": len(calls),
            "input_tokens": sum(c["input_tokens"] for c in calls),
            "output_tokens": sum(c["output_tokens"] for c in calls),
            "cost_usd": round(sum(c["cost_usd"] or 0 for c in calls), 6),
        },
    }


def _atomic_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(text)
    os.replace(tmp, path)


def report_markdown(state: dict, result: dict) -> str:
    approval = result["approval"]
    lines = [
        f"# {result['case_id']}: {state['question']}",
        "",
        f"- Decision: **{result['decision']}** ({result['reason_code']})",
        f"- Run: `{result['trace_id']}`",
        f"- Approval: {approval.get('status')} by {approval.get('by', '-')} at {approval.get('at', '-')}",
        "",
        "## Answer",
        "",
        result["answer"],
        "",
    ]
    if result["figures"]:
        lines += ["## Figures", "", "| Figure | Value |", "| --- | --- |"]
        units = {f["label"]: f["unit"] for f in state.get("facts", [])}
        lines += [f"| {k} | {fmt(v, units.get(k, ''))} |" for k, v in result["figures"].items()]
        lines.append("")
    lines += ["## Sources", "", *[f"- {c}" for c in result["citations"]], ""]
    lines += ["## Queries (RS3: rerun these to check)", ""]
    for q in state.get("queries", []):
        lines += [f"**{q['query_id']}** ({q['purpose']})", "```sql", q["rendered"], "```", ""]
    return "\n".join(lines)


def save_decision(state: dict, result: dict) -> list[str]:
    """Write the report and append this run's queries to the audit log."""
    report = config.REPORT_STORE_DIR / f"{result['case_id']}.md"
    _atomic_write(report, report_markdown(state, result))
    config.QUERY_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    with config.QUERY_LOG_PATH.open("a", encoding="utf-8") as f:
        for q in state.get("queries", []):
            entry = {"run_id": state["run_id"], "case_id": state["case_id"], **q}
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    return [str(report), str(config.QUERY_LOG_PATH)]


def write_json(path: Path, data: dict) -> None:
    _atomic_write(path, json.dumps(data, indent=2, ensure_ascii=False))


def now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")
