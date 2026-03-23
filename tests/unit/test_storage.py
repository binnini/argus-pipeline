"""Tests for SQLite storage and token savings accounting."""
import os
import pytest
from argus.storage.sqlite import Storage
from argus.engine.llm import LLMResult, BASELINE_TOKENS_PER_ERROR
from tests.fixtures.error_cases import null_spike, connection_timeout


@pytest.fixture
def storage(tmp_path):
    db = str(tmp_path / "test.db")
    return Storage(db_path=db)


def test_save_and_retrieve_error(storage):
    event = null_spike()
    event["error_type"] = "null_spike"
    event["handled_by"] = "llm"
    event["diagnosis"] = "Likely upstream schema change."
    storage.save_error(event)
    errors = storage.get_recent_errors(limit=10)
    assert len(errors) == 1
    assert errors[0]["error_type"] == "null_spike"


def test_token_summary_rule_handled(storage):
    event = connection_timeout()
    event["error_type"] = "connection_timeout"
    event["handled_by"] = "rule"
    event["diagnosis"] = "Connection timed out."
    storage.save_error(event, llm_result=None)

    summary = storage.get_token_summary()
    assert summary["rule_handled"] == 1
    assert summary["llm_called"] == 0
    # Rule-handled saves full baseline
    assert summary["tokens_saved"] == BASELINE_TOKENS_PER_ERROR


def test_token_summary_llm_handled(storage):
    event = null_spike()
    event["error_type"] = "null_spike"
    event["handled_by"] = "llm"
    event["diagnosis"] = "Null spike in user_id."

    llm_result = LLMResult(
        diagnosis="Null spike in user_id.",
        tokens_input=480,
        tokens_output=120,
        tokens_saved=BASELINE_TOKENS_PER_ERROR - 600,
        cost_usd=0.0023,
        cost_saved_usd=0.021,
        model="claude-sonnet-4-6",
    )
    storage.save_error(event, llm_result=llm_result)

    summary = storage.get_token_summary()
    assert summary["llm_called"] == 1
    assert summary["tokens_used"] == 600
    assert summary["tokens_saved"] == BASELINE_TOKENS_PER_ERROR - 600


def test_token_summary_today(storage):
    event = null_spike()
    event["error_type"] = "null_spike"
    event["handled_by"] = "rule"
    event["diagnosis"] = "test"
    storage.save_error(event)

    today = storage.get_token_summary_today()
    assert today["total_errors"] == 1
