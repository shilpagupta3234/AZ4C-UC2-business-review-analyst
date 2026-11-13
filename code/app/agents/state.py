"""Run state shared by all agents, and the typed question spec.

Agents share this typed state instead of chat transcripts, so every prompt
carries only what that agent needs. Lists marked with operator.add are
append-only logs; everything else is replaced by the node that owns it.
State holds plain JSON types so the checkpointer can save a paused run.
"""

import operator
from typing import Annotated, Literal, TypedDict

from pydantic import BaseModel, Field

QuestionType = Literal[
    "value", "breakdown", "ranking", "comparison", "trend", "vs_target", "why", "write_request", "unclear"
]
Dimension = Literal["region", "channel", "category", "brand", "product", "customer", "month"]


class QuerySpec(BaseModel):
    """What the question asks, in registry terms. The orchestrator's model fills this in."""

    question_type: QuestionType
    metrics: list[str] = Field(default_factory=list, description="metric ids from the registry")
    periods: list[str] = Field(default_factory=list, description="period text exactly as written")
    regions: list[str] = Field(default_factory=list, description="region names; empty = whole company")
    channels: list[str] = Field(default_factory=list)
    categories: list[str] = Field(default_factory=list)
    group_by: Dimension | None = None
    rank: Literal["highest", "lowest"] | None = None
    top_n: int | None = Field(default=None, ge=1, le=20)
    compare_previous: bool = False
    missing_data: list[str] = Field(default_factory=list, description="keys from NOT_IN_DATA")
    reasoning: str = Field(default="", max_length=400)


class RunState(TypedDict, total=False):
    # input
    run_id: str
    case_id: str
    question: str
    auto_approve: bool
    out_path: str
    # orchestrator
    spec: dict
    plan: dict  # {"team": [...], "skipped": {...}, "source": "llm"|"rules", "notes": [...]}
    # definitions gate
    resolved: dict
    decision: str  # answered | cannot_answer
    reason_code: str
    reason_detail: str
    # specialists
    facts: list[dict]
    headline: str | None
    variance: dict
    context: dict
    verification: dict
    send_backs: int
    # writer and approval
    answer: str
    writer_source: str
    change_note: str
    approval: dict
    result: dict
    saved: bool
    # append-only logs
    queries: Annotated[list[dict], operator.add]
    model_calls: Annotated[list[dict], operator.add]
    trace: Annotated[list[dict], operator.add]
