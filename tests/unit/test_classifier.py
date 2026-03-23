"""Tests for rule-based classifier."""
import pytest
from argus.engine.classifier import classify
from tests.fixtures.error_cases import (
    connection_timeout, schema_change, null_spike,
    volume_drop, data_loss, oom_error, unknown_error,
)


def test_connection_timeout():
    result = classify(connection_timeout())
    assert result.name == "connection_timeout"
    assert result.needs_llm is False


def test_schema_change():
    result = classify(schema_change())
    assert result.name == "schema_change"
    assert result.needs_llm is True


def test_null_spike():
    result = classify(null_spike())
    assert result.name == "null_spike"
    assert result.needs_llm is True


def test_volume_drop():
    result = classify(volume_drop())
    assert result.name == "volume_drop"
    assert result.needs_llm is True


def test_data_loss():
    result = classify(data_loss())
    assert result.name == "data_loss"
    assert result.needs_llm is True


def test_oom():
    result = classify(oom_error())
    assert result.name == "oom"
    assert result.needs_llm is False


def test_unknown_falls_back():
    result = classify(unknown_error())
    assert result.name == "unknown"
    assert result.needs_llm is True
