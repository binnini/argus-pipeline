"""
Integration test — full error handling flow without a real LLM.
Uses stub LLM (no API key required).
"""
import pytest
from argus.engine.pipeline import EnginePipeline
from tests.fixtures.error_cases import null_spike, connection_timeout, ALL_FIXTURES


@pytest.fixture(autouse=True)
def fresh_engine(tmp_path):
    """Reset singleton between tests."""
    EnginePipeline._instance = None
    config = {"db_path": str(tmp_path / "test.db")}
    EnginePipeline.initialize(config)
    yield
    EnginePipeline._instance = None


def test_rule_handled_no_llm():
    """connection_timeout should be handled by rule, no LLM stub called."""
    event = connection_timeout()
    result = EnginePipeline.get_instance().handle_error(event)
    assert result["handled_by"] == "rule"
    assert result["error_type"] == "connection_timeout"
    assert result["diagnosis"] == "Network or DB connection timed out"


def test_llm_stub_for_complex_error():
    """null_spike requires LLM — stub returns placeholder diagnosis."""
    event = null_spike()
    result = EnginePipeline.get_instance().handle_error(event)
    assert result["handled_by"] == "llm"
    assert result["error_type"] == "null_spike"
    assert result["diagnosis"]  # stub returns something


def test_all_fixtures_complete_without_crash():
    """Smoke test: every fixture must complete without raising."""
    engine = EnginePipeline.get_instance()
    for name, factory in ALL_FIXTURES.items():
        event = factory()
        result = engine.handle_error(event)
        assert "error_type" in result, f"Missing error_type for {name}"
        assert "diagnosis" in result, f"Missing diagnosis for {name}"


def test_token_savings_accumulate():
    engine = EnginePipeline.get_instance()
    engine.handle_error(connection_timeout())  # rule
    engine.handle_error(null_spike())          # llm (stub)

    summary = engine.storage.get_token_summary()
    assert summary["total_errors"] == 2
    assert summary["rule_handled"] == 1
    assert summary["llm_called"] == 1
    assert summary["tokens_saved"] > 0
