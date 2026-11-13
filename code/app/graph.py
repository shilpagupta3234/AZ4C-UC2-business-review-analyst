"""LangGraph wiring: who runs after whom, the approval pause, and the save.

  orchestrator -> definitions -+-> data_analyst -> [variance] -> [context] -> verifier -+-> writer
                               |        ^                                              |
                               |        +--------- send back (max 2) <-----------------+
                               +-> writer (refusals skip every specialist)
  writer -> approval (answered) -> save        writer -> save (refusals need no approval)
  approval: approve -> save, reject -> end (nothing written), change -> writer

State is checkpointed to SQLite after every node, keyed by run id, so a run
paused for approval survives the process ending and resumes later.
"""

import sqlite3
from contextlib import contextmanager

from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import interrupt

from . import config
from .agents.common import event
from .agents.context import context
from .agents.data_analyst import data_analyst
from .agents.definitions import definitions
from .agents.orchestrator import orchestrator
from .agents.state import RunState
from .agents.variance import variance
from .agents.verifier import route_after_verifier, verifier
from .agents.writer import writer
from .output import build_result, now, save_decision


def _in_team(state: dict, name: str) -> bool:
    return name in state.get("plan", {}).get("team", [])


def route_after_definitions(state: dict) -> str:
    return "data_analyst" if state.get("decision") == "answered" else "writer"


def route_after_data(state: dict) -> str:
    if state.get("decision") != "answered":
        return "writer"
    if _in_team(state, "variance"):
        return "variance"
    return route_after_variance(state)


def route_after_variance(state: dict) -> str:
    if _in_team(state, "context") and not state.get("context"):
        return "context"
    return "verifier"


def route_after_writer(state: dict) -> str:
    return "approval" if state.get("decision") == "answered" else "save"


def approval(state: dict) -> dict:
    """The finance controller approves every answer before it is saved (Part B)."""
    if state.get("auto_approve"):
        decision = {"action": "approve", "by": "auto-approve", "note": ""}
    else:
        preview = build_result(state)
        decision = interrupt({"run_id": state["run_id"], "question": state["question"], "result": preview})
    action = decision.get("action")
    if action not in ("approve", "reject", "change"):
        raise ValueError(f"unknown approval action {action!r}")
    status = {"approve": "approved", "reject": "rejected", "change": "change_requested"}[action]
    record = {
        "status": status,
        "by": decision.get("by", "finance controller"),
        "at": now(),
        "note": decision.get("note", ""),
    }
    update = {"approval": record, "trace": [event("approval", status, by=record["by"], note=record["note"])]}
    if action == "change":
        update["change_note"] = record["note"] or "Please revise the wording."
    return update


def route_after_approval(state: dict) -> str:
    status = state["approval"]["status"]
    if status == "approved":
        return "save"
    if status == "change_requested":
        return "writer"
    return END


def save(state: dict) -> dict:
    if state.get("saved"):
        return {}
    approval_record = state.get("approval") or {"status": "not_required", "by": "-", "at": now()}
    result = build_result({**state, "approval": approval_record})
    paths = save_decision(state, result)
    return {
        "result": result,
        "saved": True,
        "approval": approval_record,
        "trace": [event("save", "saved", paths=paths)],
    }


def build_graph():
    g = StateGraph(RunState)
    for name, fn in [
        ("orchestrator", orchestrator),
        ("definitions", definitions),
        ("data_analyst", data_analyst),
        ("variance", variance),
        ("context", context),
        ("verifier", verifier),
        ("writer", writer),
        ("approval", approval),
        ("save", save),
    ]:
        g.add_node(name, fn)
    g.add_edge(START, "orchestrator")
    g.add_edge("orchestrator", "definitions")
    g.add_conditional_edges("definitions", route_after_definitions, ["data_analyst", "writer"])
    g.add_conditional_edges("data_analyst", route_after_data, ["variance", "context", "verifier", "writer"])
    g.add_conditional_edges("variance", route_after_variance, ["context", "verifier"])
    g.add_edge("context", "verifier")
    g.add_conditional_edges("verifier", route_after_verifier, ["data_analyst", "writer"])
    g.add_conditional_edges("writer", route_after_writer, ["approval", "save"])
    g.add_conditional_edges("approval", route_after_approval, ["save", "writer", END])
    g.add_edge("save", END)
    return g


@contextmanager
def compiled_graph():
    """The graph with a SQLite checkpointer, so paused runs survive a restart."""
    config.STATE_DIR.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(str(config.CHECKPOINT_DB), check_same_thread=False)
    try:
        yield build_graph().compile(checkpointer=SqliteSaver(con))
    finally:
        con.close()
