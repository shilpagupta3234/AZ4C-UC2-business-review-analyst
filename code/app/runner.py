"""Starts runs, pauses them for approval, resumes them, and keeps the trace.

A run without --auto-approve stops at the approval step: its result is
written with approval "pending", and a small file in .state/pending/ lets
the approval screen and `python -m app approve` find it again.
"""

import json
import uuid
from pathlib import Path

from langgraph.types import Command

from . import config
from .graph import compiled_graph
from .output import build_result, write_json


class RunNotFound(Exception):
    pass


def _cfg(run_id: str) -> dict:
    return {"configurable": {"thread_id": run_id}, "recursion_limit": 60}


def _write_trace(state: dict, written: int) -> int:
    """Append this run's new trace events to logs/trace.jsonl. Returns how many are written now."""
    events = state.get("trace", [])[written:]
    if events:
        config.LOG_DIR.mkdir(parents=True, exist_ok=True)
        with config.TRACE_LOG_PATH.open("a", encoding="utf-8") as f:
            for e in events:
                f.write(json.dumps({"run_id": state["run_id"], **e}, ensure_ascii=False) + "\n")
    return len(state.get("trace", []))


def _finish(app, run_id: str, trace_written: int) -> dict:
    snapshot = app.get_state(_cfg(run_id))
    state = snapshot.values
    _write_trace(state, trace_written)
    pending_file = config.PENDING_DIR / f"{run_id}.json"
    if snapshot.next:  # paused at the approval step
        result = build_result({**state, "approval": {"status": "pending"}})
        write_json(
            pending_file,
            {
                "run_id": run_id,
                "case_id": state["case_id"],
                "question": state["question"],
                "out_path": state.get("out_path", ""),
                "result": result,
            },
        )
    else:
        pending_file.unlink(missing_ok=True)
        result = state.get("result") or build_result(state)
        if state.get("approval", {}).get("status") == "rejected":
            result = build_result(state)
    if state.get("out_path"):
        write_json(Path(state["out_path"]), result)
    return result


def start_run(case: dict, auto_approve: bool, out_path: str | None = None) -> dict:
    run_id = f"{case['case_id']}-{uuid.uuid4().hex[:8]}"
    initial = {
        "run_id": run_id,
        "case_id": case["case_id"],
        "question": case["input"]["question"],
        "auto_approve": auto_approve,
        "out_path": str(Path(out_path).resolve()) if out_path else "",
        "queries": [],
        "model_calls": [],
        "trace": [],
    }
    with compiled_graph() as app:
        app.invoke(initial, _cfg(run_id))
        return _finish(app, run_id, 0)


def resume_run(run_id: str, action: str, note: str = "", by: str = "finance controller") -> dict:
    with compiled_graph() as app:
        snapshot = app.get_state(_cfg(run_id))
        if not snapshot.values:
            raise RunNotFound(f"no run with id {run_id}")
        if not snapshot.next:
            raise RunNotFound(f"run {run_id} is not waiting for approval")
        written = len(snapshot.values.get("trace", []))
        app.invoke(Command(resume={"action": action, "note": note, "by": by}), _cfg(run_id))
        return _finish(app, run_id, written)


def pending_runs() -> list[dict]:
    if not config.PENDING_DIR.is_dir():
        return []
    runs = [json.loads(p.read_text(encoding="utf-8")) for p in sorted(config.PENDING_DIR.glob("*.json"))]
    return sorted(runs, key=lambda r: r["run_id"])
