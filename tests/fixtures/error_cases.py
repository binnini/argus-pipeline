"""
Error case simulators for testing without a real pipeline.
Each function raises or returns an event that matches a known error type.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone


def _base_event(layer: str, fn: str, error_class: str, message: str, tb: str, metrics: dict = None) -> dict:
    return {
        "event_id": str(uuid.uuid4()),
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "layer": layer,
        "function": fn,
        "error_class": error_class,
        "error_message": message,
        "traceback_raw": tb,
        "traceback_summary": tb,
        "severity": "error",
        "duration_sec": 1.23,
        "metrics": metrics or {},
    }


def connection_timeout() -> dict:
    return _base_event(
        layer="ingestion",
        fn="fetch_from_postgres",
        error_class="OperationalError",
        message="connection timed out after 30s",
        tb="Traceback (most recent call last):\n...\nOperationalError: connection timed out after 30s",
    )


def schema_change() -> dict:
    return _base_event(
        layer="transform",
        fn="run_dbt_models",
        error_class="ProgrammingError",
        message="column \"phone_number\" does not exist",
        tb="Traceback (most recent call last):\n...\nProgrammingError: column \"phone_number\" does not exist",
        metrics={"row_count_before": 50000},
    )


def null_spike() -> dict:
    return _base_event(
        layer="transform",
        fn="clean_users",
        error_class="ValueError",
        message="Null constraint violated on user_id",
        tb="Traceback (most recent call last):\n...\nValueError: Null constraint violated on user_id",
        metrics={
            "row_count_before": 50000,
            "row_count_after": 50000,
            "row_count_delta": 0.0,
            "null_rate_delta": {"user_id": 0.34, "email": 0.02},
            "max_null_spike": 0.34,
        },
    )


def volume_drop() -> dict:
    return _base_event(
        layer="ingestion",
        fn="fetch_daily_orders",
        error_class="AssertionError",
        message="Row count too low: expected ~10000, got 3200",
        tb="Traceback (most recent call last):\n...\nAssertionError: Row count too low: expected ~10000, got 3200",
        metrics={
            "row_count": 3200,
            "row_count_delta": -0.68,
            "source_type": "s3",
        },
    )


def data_loss() -> dict:
    return _base_event(
        layer="load",
        fn="write_to_bigquery",
        error_class="RuntimeError",
        message="Load job completed with errors",
        tb="Traceback (most recent call last):\n...\nRuntimeError: Load job completed with errors",
        metrics={
            "target": "bigquery://project/dataset/orders",
            "write_mode": "append",
            "expected_count": 50000,
            "loaded_count": 48100,
            "loss_rate": 0.038,
        },
    )


def oom_error() -> dict:
    return _base_event(
        layer="transform",
        fn="compute_features",
        error_class="MemoryError",
        message="cannot allocate array",
        tb="Traceback (most recent call last):\n...\nMemoryError: cannot allocate array",
    )


def unknown_error() -> dict:
    return _base_event(
        layer="transform",
        fn="custom_aggregation",
        error_class="RuntimeError",
        message="Unexpected state in aggregation loop at step 47",
        tb="Traceback (most recent call last):\n  File 'pipeline.py', line 203, in custom_aggregation\n...\nRuntimeError: Unexpected state in aggregation loop at step 47",
        metrics={"row_count_before": 12000, "row_count_after": 11800},
    )


ALL_FIXTURES = {
    "connection_timeout": connection_timeout,
    "schema_change": schema_change,
    "null_spike": null_spike,
    "volume_drop": volume_drop,
    "data_loss": data_loss,
    "oom_error": oom_error,
    "unknown_error": unknown_error,
}
