"""Tests for context builder — verifies prompt stays compact."""
from argus.engine.context import build_prompt
from argus.engine.classifier import classify
from tests.fixtures.error_cases import null_spike, schema_change, unknown_error


def test_prompt_under_500_words():
    event = null_spike()
    error_type = classify(event)
    prompt = build_prompt(event, error_type)
    word_count = len(prompt.split())
    assert word_count < 500, f"Prompt too long: {word_count} words"


def test_prompt_contains_layer():
    event = schema_change()
    error_type = classify(event)
    prompt = build_prompt(event, error_type)
    assert "transform" in prompt.lower()


def test_prompt_contains_error_type():
    event = null_spike()
    error_type = classify(event)
    prompt = build_prompt(event, error_type)
    assert "null_spike" in prompt


def test_prompt_no_raw_data():
    """Ensure actual record values are never included."""
    event = null_spike()
    event["traceback_raw"] = "SENSITIVE_CUSTOMER_EMAIL@example.com in traceback"
    error_type = classify(event)
    prompt = build_prompt(event, error_type)
    # traceback_raw must NOT appear in prompt
    assert "SENSITIVE_CUSTOMER_EMAIL" not in prompt


def test_metrics_formatted():
    event = null_spike()
    error_type = classify(event)
    prompt = build_prompt(event, error_type)
    assert "34%" in prompt or "0.34" in prompt  # null spike delta appears
