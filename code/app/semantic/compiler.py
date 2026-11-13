"""Compiles one measure + period + filters + grouping into parameterised SQL.

The joins, date columns and region rules live here, once, and are unit
tested. Agents never write these joins themselves.
"""

from dataclasses import dataclass

from .calendar import Period
from .metrics import MEASURES


class NotAvailable(Exception):
    """The data cannot be cut this way (e.g. targets by channel)."""


@dataclass(frozen=True)
class Source:
    from_sql: str
    date_col: str  # the column that decides the month
    tables: tuple[str, ...]  # cited when this source is used
    month_grain: bool = False  # targets are stored per 'YYYY-MM', not per day


SOURCES = {
    "lines": Source(
        "order_lines l JOIN orders o ON o.order_id = l.order_id", "o.order_date", ("order_lines", "orders")
    ),
    # Refunds and reversed COGS count in the return month, but the region is
    # the one recorded on the original order (M3).
    "returns": Source(
        "returns r JOIN orders o ON o.order_id = r.order_id "
        "JOIN order_lines l ON l.order_id = r.order_id AND l.line_no = r.line_no",
        "r.return_date",
        ("returns", "orders"),
    ),
    "orders": Source("orders o", "o.order_date", ("orders",)),
    "promo": Source(
        "order_lines l JOIN orders o ON o.order_id = l.order_id "
        "JOIN promotions pr ON pr.region_id = o.region_id "
        "AND o.order_date BETWEEN pr.start_date AND pr.end_date",
        "o.order_date",
        ("order_lines", "orders", "promotions"),
    ),
    "targets": Source("targets t", "t.month", ("targets",), month_grain=True),
}

# Dimension -> SQL column per source. A missing source means that cut is
# not available for that measure (freight has no product; targets no channel).
_CUSTOMER_JOIN = "JOIN customers c ON c.customer_id = o.customer_id"
_PRODUCT_JOIN = "JOIN products p ON p.product_id = l.product_id"

DIMENSIONS: dict[str, dict[str, str]] = {
    "region": {
        "lines": "o.region_id",
        "returns": "o.region_id",
        "orders": "o.region_id",
        "promo": "o.region_id",
        "targets": "t.region_id",
    },
    "channel": {"lines": "c.channel", "returns": "c.channel", "orders": "c.channel", "promo": "c.channel"},
    "customer": {
        "lines": "o.customer_id",
        "returns": "o.customer_id",
        "orders": "o.customer_id",
        "promo": "o.customer_id",
    },
    "product": {"lines": "l.product_id", "returns": "l.product_id", "promo": "l.product_id"},
    "category": {"lines": "p.category", "returns": "p.category", "promo": "p.category"},
    "brand": {"lines": "p.brand", "returns": "p.brand", "promo": "p.brand"},
    "promotion": {"promo": "pr.promo_id"},
    "month": {},  # derived from the source's date column, see _dim_col
}
_DIM_JOINS = {
    "channel": (_CUSTOMER_JOIN, "customers"),
    "category": (_PRODUCT_JOIN, "products"),
    "brand": (_PRODUCT_JOIN, "products"),
}


@dataclass(frozen=True)
class CompiledQuery:
    sql: str
    params: tuple
    tables: tuple[str, ...]
    group_by: tuple[str, ...]


def _dim_col(dim: str, source_key: str) -> str:
    src = SOURCES[source_key]
    if dim == "month":
        return src.date_col if src.month_grain else f"substr({src.date_col}, 1, 7)"
    col = DIMENSIONS.get(dim, {}).get(source_key)
    if col is None:
        raise NotAvailable(f"'{dim}' is not available for {source_key} data")
    return col


def compile_measure(
    measure_id: str,
    period: Period,
    filters: dict[str, list[str]] | None = None,
    group_by: list[str] | None = None,
) -> CompiledQuery:
    filters, group_by = filters or {}, group_by or []
    m = MEASURES[measure_id]
    src = SOURCES[m.source]
    tables = list(src.tables)
    joins: list[str] = []

    for dim in [*filters, *group_by]:
        _dim_col(dim, m.source)  # raises NotAvailable early
        if dim in _DIM_JOINS and m.source != "targets":
            join, table = _DIM_JOINS[dim]
            if join not in joins:
                joins.append(join)
                tables.append(table)

    where = [f"{src.date_col} BETWEEN ? AND ?"]
    if src.month_grain:
        params: list = [period.start.strftime("%Y-%m"), period.end.strftime("%Y-%m")]
    else:
        params = [period.start.isoformat(), period.end.isoformat()]

    for dim, values in filters.items():
        if not values:
            continue
        where.append(f"{_dim_col(dim, m.source)} IN ({', '.join('?' for _ in values)})")
        params.extend(values)

    cols = [_dim_col(d, m.source) for d in group_by]
    select = ", ".join([*(f"{c} AS {d}" for c, d in zip(cols, group_by, strict=True)), f"{m.expr} AS value"])
    sql = f"SELECT {select} FROM {src.from_sql}"
    if joins:
        sql += " " + " ".join(joins)
    sql += " WHERE " + " AND ".join(where)
    if group_by:
        sql += " GROUP BY " + ", ".join(cols) + " ORDER BY " + ", ".join(cols)
    return CompiledQuery(sql, tuple(params), tuple(dict.fromkeys(tables)), tuple(group_by))
