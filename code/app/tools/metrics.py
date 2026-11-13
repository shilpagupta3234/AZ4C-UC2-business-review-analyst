"""compute_metric: the Data analyst's main tool.

Runs one compiled query per measure, then applies the registry formula per
group in Python. Values keep full precision here; rounding to 2 decimals
(RS8) happens only when the answer is written.
"""

from dataclasses import dataclass, field

from ..semantic.calendar import Period
from ..semantic.compiler import compile_measure
from ..semantic.metrics import METRICS
from .sql import ReadOnlyDB

GroupKey = tuple[str, ...]  # () for an ungrouped total


@dataclass
class MetricResult:
    metric_id: str
    period: Period
    filters: dict[str, list[str]]
    group_by: list[str]
    values: dict[GroupKey, float | None]  # formula result per group
    measures: dict[GroupKey, dict[str, float]]  # inputs per group, for showing working
    query_ids: list[str] = field(default_factory=list)
    tables: list[str] = field(default_factory=list)
    doc_ref: str = ""

    @property
    def total(self) -> float | None:
        """The single value of an ungrouped result."""
        return self.values.get(())


def compute_metric(
    db: ReadOnlyDB,
    metric_id: str,
    period: Period,
    filters: dict[str, list[str]] | None = None,
    group_by: list[str] | None = None,
) -> MetricResult:
    metric = METRICS[metric_id]
    filters, group_by = filters or {}, group_by or []
    per_measure: dict[str, dict[GroupKey, float]] = {}
    query_ids: list[str] = []
    tables: list[str] = []

    for measure_id in metric.measures:
        q = compile_measure(measure_id, period, filters, group_by)
        res = db.run(q.sql, q.params)
        query_ids.append(res.query_id)
        tables += [t for t in q.tables if t not in tables]
        n = len(group_by)
        per_measure[measure_id] = {tuple(str(x) for x in row[:n]): float(row[n] or 0.0) for row in res.rows}

    keys = sorted({k for vals in per_measure.values() for k in vals}) if group_by else [()]
    measures = {k: {m: per_measure[m].get(k, 0.0) for m in metric.measures} for k in keys}
    values = {k: metric.formula(v) for k, v in measures.items()}
    return MetricResult(
        metric_id, period, filters, group_by, values, measures, query_ids, tables, metric.doc_ref
    )


def run_measures(
    db: ReadOnlyDB, measure_ids: list[str], period: Period, filters: dict[str, list[str]] | None = None
) -> tuple[dict[str, float], list[str], list[str]]:
    """Ungrouped totals for several measures: (values, query_ids, tables)."""
    values: dict[str, float] = {}
    query_ids: list[str] = []
    tables: list[str] = []
    for measure_id in measure_ids:
        q = compile_measure(measure_id, period, filters)
        res = db.run(q.sql, q.params)
        values[measure_id] = float(res.rows[0][0] or 0.0) if res.rows else 0.0
        query_ids.append(res.query_id)
        tables += [t for t in q.tables if t not in tables]
    return values, query_ids, tables
