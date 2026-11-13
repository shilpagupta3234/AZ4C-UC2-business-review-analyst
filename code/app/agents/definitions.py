"""Definitions and period agent: the answerability gate.

Plain code, no model. Before any metric query runs it decides whether the
data can answer the question, so a refusal costs no SQL and no tokens:

  RS6 write request          -> WRITE_REQUEST_REFUSED
  RS5 data we don't hold     -> DATA_NOT_AVAILABLE
  RS7 no measure or period   -> AMBIGUOUS_QUESTION
  period outside the data    -> DATA_NOT_AVAILABLE
  unknown region             -> DATA_NOT_AVAILABLE

Otherwise it resolves names to exact ids and dates for the specialists.
"""

from ..semantic import calendar as cal
from ..semantic.metrics import METRICS, NOT_IN_DATA
from .common import coverage_for, event, open_db, query_records
from .orchestrator import _RELATIVE_PERIOD_RE

_TARGET_DIMS = {None, "region", "month"}


def _period_dict(p: cal.Period) -> dict:
    return {"label": p.label, "start": p.start.isoformat(), "end": p.end.isoformat(), "grain": p.grain}


def _refuse(code: str, detail: str, citations: list[str] | None = None) -> dict:
    return {
        "decision": "cannot_answer",
        "reason_code": code,
        "reason_detail": detail,
        "resolved": {"citations": citations or []},
    }


def gate(spec: dict, question: str, cov) -> dict:
    qtype = spec["question_type"]
    first, last = cov.first_date.strftime("%B %Y"), cov.last_date.strftime("%B %Y")

    if qtype == "write_request":
        return _refuse(
            "WRITE_REQUEST_REFUSED",
            "Analysis is read-only and never changes source data. Targets are set by the CFO's office "
            "in the planning system; data corrections go through the owners of the sales system.",
            citations=["reporting_standards.md#RS6"],
        )
    if spec["missing_data"]:
        missing = "; ".join(NOT_IN_DATA[k] for k in spec["missing_data"])
        return _refuse(
            "DATA_NOT_AVAILABLE",
            f"The sales data does not hold {missing}. "
            "Finance does not estimate or use proxies for missing data.",
            citations=["reporting_standards.md#RS5"],
        )
    if not spec["metrics"] or qtype == "unclear":
        return _refuse(
            "AMBIGUOUS_QUESTION",
            "The question does not name a measure finance defines (for example net revenue or gross margin). "
            "Please say which measure you mean.",
            citations=["reporting_standards.md#RS7", "metric_definitions.md"],
        )
    span = cal.month_span(question)
    if span and qtype not in ("comparison", "why"):
        return _refuse(
            "AMBIGUOUS_QUESTION",
            f"'{span}' is a span of months, which finance does not report as one period. "
            "Please ask for a quarter (for example 'Q1 FY27' for April to June 2026), a financial year "
            f"(for example 'FY26') or a single month (data covers {first} to {last}).",
            citations=["reporting_standards.md#RS7", "finance_calendar.md"],
        )
    periods = [p for text in spec["periods"] for p in cal.parse_periods(text)]
    year = cal.bare_year(question)
    if not periods and year:
        return _refuse(
            "AMBIGUOUS_QUESTION",
            f"'{year}' could mean financial year FY{year % 100:02d} (April {year - 1} to March {year}), "
            f"FY{(year + 1) % 100:02d} (April {year} to March {year + 1}) or calendar year {year}. "
            f"Please say which, for example 'FY{year % 100:02d}' or 'Q2 FY{(year + 1) % 100:02d}' "
            f"(data covers {first} to {last}).",
            citations=["reporting_standards.md#RS7", "finance_calendar.md"],
        )
    if not periods or _RELATIVE_PERIOD_RE.search(question):
        return _refuse(
            "AMBIGUOUS_QUESTION",
            "The question does not name a specific month, quarter or financial year. "
            f"Please give one, for example 'August 2026' or 'Q2 FY27' (data covers {first} to {last}).",
            citations=["reporting_standards.md#RS7", "finance_calendar.md"],
        )
    outside = [p.label for p in periods if not cov.covers(p.start, p.end)]
    if outside:
        return _refuse(
            "DATA_NOT_AVAILABLE",
            f"No sales data is held for {', '.join(outside)}. Data covers {first} to {last}; "
            "finance does not estimate or extrapolate missing periods.",
            citations=["finance_calendar.md", "reporting_standards.md#RS5"],
        )
    region_ids, unknown = [], []
    for name in spec["regions"]:
        rid = cov.region_id(name)
        (region_ids.append(rid) if rid else unknown.append(name))
    if unknown:
        return _refuse(
            "DATA_NOT_AVAILABLE",
            f"There is no region called {', '.join(unknown)}. Data is held for "
            f"{', '.join(cov.regions.values())}.",
            citations=["regions"],
        )
    if qtype == "vs_target" and (
        spec["channels"] or spec["categories"] or spec["group_by"] not in _TARGET_DIMS
    ):
        return _refuse(
            "DATA_NOT_AVAILABLE",
            "Targets are set per region and calendar month only, so they cannot be compared by "
            "channel, category, brand, product or customer.",
            citations=["metric_definitions.md#M7", "targets"],
        )

    periods.sort(key=lambda p: p.start)
    filters = {}
    if region_ids:
        filters["region"] = region_ids
    if spec["channels"]:
        filters["channel"] = [c for c in spec["channels"] if c in cov.channels]
    if spec["categories"]:
        filters["category"] = [c for c in spec["categories"] if c in cov.categories]
    resolved = {
        "question_type": qtype,
        "metrics": [m for m in spec["metrics"] if m in METRICS],
        "periods": [_period_dict(p) for p in periods],
        "region_ids": region_ids,
        "region_names": {rid: cov.regions[rid] for rid in cov.regions},
        "filters": filters,
        "group_by": spec["group_by"],
        "rank": spec["rank"],
        "top_n": spec["top_n"],
        "compare_previous": spec["compare_previous"],
        "data_start": cov.first_date.isoformat(),
        "citations": ["finance_calendar.md", *(METRICS[m].doc_ref for m in spec["metrics"] if m in METRICS)],
    }
    return {"decision": "answered", "reason_code": "ANSWERED", "reason_detail": "", "resolved": resolved}


def definitions(state: dict) -> dict:
    db = open_db(state)
    try:
        cov = coverage_for(db)
    finally:
        db.close()
    out = gate(state["spec"], state["question"], cov)
    trace = event(
        "definitions",
        "gate",
        decision=out["decision"],
        reason_code=out["reason_code"],
        detail=out["reason_detail"],
    )
    update = {
        **out,
        "facts": [],
        "headline": None,
        "queries": query_records(db, "coverage"),
        "trace": [trace],
    }
    if out["decision"] != "answered":
        plan = dict(state["plan"])
        reason = f"stopped at the gate: {out['reason_code']}"
        plan["skipped"] = {
            **plan["skipped"],
            **{a: reason for a in plan["team"] if a not in ("definitions", "writer")},
        }
        plan["team"] = ["definitions", "writer"]
        update["plan"] = plan
    return update
