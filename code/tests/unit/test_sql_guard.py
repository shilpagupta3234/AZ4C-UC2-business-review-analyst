"""The SQL guard refuses anything but one read-only SELECT on known tables."""

import pytest

from app.tools.sql import SQLGuardError, check_sql, render


@pytest.mark.parametrize(
    "sql",
    [
        "DELETE FROM orders",
        "UPDATE targets SET revenue_target = 0",
        "DROP TABLE orders",
        "INSERT INTO regions VALUES ('R9', 'X', 1)",
        "CREATE TABLE x (a INT)",
        "SELECT 1; DELETE FROM orders",
        "PRAGMA table_info(orders)",
        "ATTACH DATABASE 'x.db' AS x",
        "SELECT * FROM sqlite_master",
        "SELECT * FROM secrets",
        "not sql at all (",
    ],
)
def test_guard_refuses(sql):
    with pytest.raises(SQLGuardError):
        check_sql(sql)


def test_guard_allows_select_with_cte_and_join():
    sql = "WITH t AS (SELECT region_id FROM orders) SELECT r.name FROM t JOIN regions r USING (region_id)"
    assert check_sql(sql) == ["orders", "regions"]


def test_render_fills_values_and_escapes_quotes():
    assert render("SELECT * FROM t WHERE a = ? AND b = ?", ["O'Neil", 5]) == (
        "SELECT * FROM t WHERE a = 'O''Neil' AND b = 5"
    )


def test_render_leaves_sql_alone_when_counts_differ():
    assert render("SELECT ?", []) == "SELECT ?"
