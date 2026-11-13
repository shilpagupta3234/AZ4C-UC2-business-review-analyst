"""Shared pytest setup.

- Every test under tests/integration/ gets the integration marker.
- Every test writes state, logs and mock_system files into its own temp
  folder, so tests never touch the real outputs and never see each other's.
- No test calls a real model: the LLM transport is a fake unless a test
  installs its own scripted one with the `fake_llm` fixture.
"""

from pathlib import Path

import pytest

from app import config
from app.agents import common
from app.llm import gateway
from tests.fakes import FakeLLM

INTEGRATION_DIR = Path(__file__).parent / "integration"


def pytest_collection_modifyitems(items):
    for item in items:
        if INTEGRATION_DIR in Path(item.fspath).parents:
            item.add_marker(pytest.mark.integration)


@pytest.fixture(autouse=True)
def isolated_outputs(tmp_path, monkeypatch):
    mock = tmp_path / "mock_system"
    monkeypatch.setattr(config, "MOCK_SYSTEM_DIR", mock)
    monkeypatch.setattr(config, "REPORT_STORE_DIR", mock / "report_store")
    monkeypatch.setattr(config, "QUERY_LOG_PATH", mock / "audit" / "query_log.jsonl")
    monkeypatch.setattr(config, "STATE_DIR", tmp_path / ".state")
    monkeypatch.setattr(config, "CHECKPOINT_DB", tmp_path / ".state" / "checkpoints.db")
    monkeypatch.setattr(config, "PENDING_DIR", tmp_path / ".state" / "pending")
    monkeypatch.setattr(config, "LOG_DIR", tmp_path / "logs")
    monkeypatch.setattr(config, "LLM_LOG_PATH", tmp_path / "logs" / "llm_calls.jsonl")
    monkeypatch.setattr(config, "TRACE_LOG_PATH", tmp_path / "logs" / "trace.jsonl")
    return tmp_path


@pytest.fixture(autouse=True)
def fresh_provider_cooldowns(monkeypatch):
    monkeypatch.setattr(gateway, "_COOLDOWN_UNTIL", {})


@pytest.fixture(autouse=True)
def default_fake_llm(monkeypatch):
    fake = FakeLLM()
    monkeypatch.setattr(common, "TRANSPORT_OVERRIDE", fake)
    return fake


@pytest.fixture
def fake_llm(monkeypatch):
    """Install a scripted fake: fake_llm({"writer": [reply1, reply2], ...})."""

    def install(script: dict | None = None) -> FakeLLM:
        fake = FakeLLM(script)
        monkeypatch.setattr(common, "TRANSPORT_OVERRIDE", fake)
        return fake

    return install
