"""Fixtures for tests that read the real data pack."""

import sqlite3

import pytest

from app import config
from app.tools.sql import ReadOnlyDB


@pytest.fixture(scope="session", autouse=True)
def _data_pack_present():
    if not config.DB_PATH.is_file():
        pytest.exit(f"Data pack not found at {config.DB_PATH}. Set DATA_DIR.", returncode=2)


@pytest.fixture
def db():
    d = ReadOnlyDB()
    yield d
    d.close()


@pytest.fixture
def raw():
    """Hand-written SQL for expected values, independent of the code under test."""

    def run(sql, *params):
        con = sqlite3.connect(f"{config.DB_PATH.resolve().as_uri()}?mode=ro", uri=True)
        try:
            return con.execute(sql, params).fetchall()
        finally:
            con.close()

    return run
