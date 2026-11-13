"""Read-only SQL with guards, and a log of every query a run executes.

Four layers, so no single check has to be perfect:
1. The database file is opened with mode=ro and PRAGMA query_only.
2. sqlglot parses each statement: exactly one SELECT, no writes, PRAGMA,
   ATTACH or similar, and only known tables.
3. Values are passed as bound parameters, never pasted into SQL.
4. A row cap and a time limit stop runaway queries.
"""

import hashlib
import json
import sqlite3
import time
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path

import sqlglot
from sqlglot import exp

from .. import config

ALLOWED_TABLES = {
    "regions",
    "customers",
    "products",
    "orders",
    "order_lines",
    "returns",
    "promotions",
    "targets",
}

_FORBIDDEN = (
    exp.Insert,
    exp.Update,
    exp.Delete,
    exp.Drop,
    exp.Create,
    exp.Alter,
    exp.Command,
    exp.Pragma,
    exp.Attach,
    exp.Detach,
    exp.Merge,
    exp.TruncateTable,
)


class SQLGuardError(Exception):
    """The statement was refused before it reached the database."""


class SQLExecutionError(Exception):
    """The database rejected or timed out the statement."""


@dataclass
class QueryRecord:
    query_id: str
    sql: str
    params: list
    rendered: str  # the same query with values filled in, so it can be rerun (RS3)
    tables: list[str]
    row_count: int
    result_hash: str
    duration_ms: float
    executed_at: str


@dataclass
class QueryResult:
    query_id: str
    columns: list[str]
    rows: list[tuple]


@dataclass
class QueryLog:
    """Every query one run executes, in order. Saved to the audit log after approval."""

    records: list[QueryRecord] = field(default_factory=list)
    offset: int = 0  # queries already run earlier in the same run (ids continue from here)

    def next_id(self) -> str:
        return f"Q{self.offset + len(self.records) + 1:02d}"

    def to_jsonl(self, run_id: str) -> str:
        return "".join(
            json.dumps({"run_id": run_id, **asdict(r)}, ensure_ascii=False) + "\n" for r in self.records
        )


def check_sql(sql: str) -> list[str]:
    """Refuse anything but one read-only SELECT on known tables. Returns tables used."""
    try:
        statements = [s for s in sqlglot.parse(sql, read="sqlite") if s is not None]
    except sqlglot.errors.ParseError as e:
        raise SQLGuardError(f"could not parse SQL: {e}") from e
    if len(statements) != 1:
        raise SQLGuardError("exactly one statement is allowed")
    tree = statements[0]
    if not isinstance(tree, (exp.Select, exp.Union, exp.Intersect, exp.Except)):
        raise SQLGuardError(f"only SELECT is allowed, got {type(tree).__name__}")
    if any(isinstance(node, _FORBIDDEN) for node in tree.walk()):
        raise SQLGuardError("statement contains a write or admin command")
    ctes = {c.alias_or_name.lower() for c in tree.find_all(exp.CTE)}
    tables = {t.name.lower() for t in tree.find_all(exp.Table)} - ctes
    unknown = tables - ALLOWED_TABLES
    if unknown:
        raise SQLGuardError(f"unknown table(s): {sorted(unknown)}")
    return sorted(tables)


def render(sql: str, params: tuple | list) -> str:
    """Fill in bound values for display. Only used for logs, never executed."""
    parts = sql.split("?")
    if len(parts) - 1 != len(params):
        return sql
    out = [parts[0]]
    for value, rest in zip(params, parts[1:], strict=True):
        lit = str(value) if isinstance(value, (int, float)) else "'" + str(value).replace("'", "''") + "'"
        out += [lit, rest]
    return "".join(out)


class ReadOnlyDB:
    def __init__(self, db_path: Path = config.DB_PATH, log: QueryLog | None = None):
        if not db_path.is_file():
            raise FileNotFoundError(f"sales database not found at {db_path}; check DATA_DIR")
        self.log = log if log is not None else QueryLog()
        self._con = sqlite3.connect(f"{db_path.resolve().as_uri()}?mode=ro", uri=True)
        self._con.execute("PRAGMA query_only = ON")

    def close(self) -> None:
        self._con.close()

    def run(
        self,
        sql: str,
        params: tuple | list = (),
        *,
        max_rows: int = config.SQL_MAX_ROWS,
        timeout_s: float = config.SQL_TIMEOUT_S,
    ) -> QueryResult:
        tables = check_sql(sql)
        deadline = time.monotonic() + timeout_s
        self._con.set_progress_handler(lambda: 1 if time.monotonic() > deadline else 0, 10_000)
        started = time.perf_counter()
        try:
            cur = self._con.execute(sql, tuple(params))
            rows = cur.fetchmany(max_rows + 1)
        except sqlite3.Error as e:
            raise SQLExecutionError(str(e)) from e
        finally:
            self._con.set_progress_handler(None, 0)
        if len(rows) > max_rows:
            raise SQLExecutionError(f"query returned more than {max_rows} rows; aggregate it")
        columns = [d[0] for d in cur.description]
        record = QueryRecord(
            query_id=self.log.next_id(),
            sql=sql,
            params=list(params),
            rendered=render(sql, params),
            tables=tables,
            row_count=len(rows),
            result_hash=hashlib.sha256(repr(rows).encode()).hexdigest()[:16],
            duration_ms=round((time.perf_counter() - started) * 1000, 2),
            executed_at=datetime.now(UTC).isoformat(timespec="seconds"),
        )
        self.log.records.append(record)
        return QueryResult(record.query_id, columns, rows)
