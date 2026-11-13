"""The read-only database tool, query log and coverage map on the real data."""

import json
import sqlite3
from datetime import date

import pytest

from app.semantic import calendar as cal
from app.tools.coverage import data_coverage
from app.tools.metrics import compute_metric
from app.tools.sql import SQLExecutionError, SQLGuardError


def test_connection_is_read_only(db):
    with pytest.raises(sqlite3.OperationalError):
        db._con.execute("DELETE FROM regions")


def test_guard_runs_before_the_database(db):
    with pytest.raises(SQLGuardError):
        db.run("DELETE FROM regions")
    assert db.log.records == []


def test_row_cap(db):
    with pytest.raises(SQLExecutionError, match="more than 100 rows"):
        db.run("SELECT * FROM order_lines", max_rows=100)


def test_timeout(db):
    slow = "SELECT COUNT(*) FROM order_lines a, order_lines b"
    with pytest.raises(SQLExecutionError):
        db.run(slow, timeout_s=0.05)


def test_every_query_is_logged_and_rerunnable(db, raw):
    r = compute_metric(db, "net_revenue", cal.month(2026, 7), {"region": ["R1"]})
    assert r.query_ids == ["Q01", "Q02"]
    rec = db.log.records[0]
    assert "'R1'" in rec.rendered
    assert "?" not in rec.rendered
    assert raw(rec.rendered)[0][0] == pytest.approx(r.measures[()]["line_net_revenue"])


def test_query_log_jsonl_has_run_id(db):
    db.run("SELECT COUNT(*) FROM regions")
    line = json.loads(db.log.to_jsonl("run-123").splitlines()[0])
    assert line["run_id"] == "run-123"
    assert line["query_id"] == "Q01"
    assert line["tables"] == ["regions"]


def test_coverage_reads_data_range(db):
    cov = data_coverage(db)
    assert (cov.first_date, cov.last_date) == (date(2025, 4, 1), date(2026, 9, 30))
    assert cov.target_months == ("2025-04", "2026-09")
    assert not cov.covers(date(2026, 10, 1), date(2026, 10, 31))
    assert cov.covers(date(2026, 4, 1), date(2026, 6, 30))


def test_coverage_region_lookup(db):
    cov = data_coverage(db)
    assert cov.region_id("west") == "R4"
    assert cov.region_id("R2") == "R2"
    assert cov.region_id("Atlantis") is None
    assert set(cov.channels) == {"E-commerce", "General Trade", "Modern Trade"}
