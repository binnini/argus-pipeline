"""
LogAnalyzer — abstract interface for log/artifact-based metric extraction.

Implementations provide stack-specific parsing logic (dbt, Airflow, Kafka, etc.)
while BaseLayer consumes a uniform interface.

Implementors must provide:
  extract_metrics() → dict   : data quality metrics after a run (row counts, timing, etc.)
  extract_error()   → str|None: structured error message better than the raw exception,
                                or None to fall back to the original exception message
"""
from __future__ import annotations

from abc import ABC, abstractmethod


class LogAnalyzer(ABC):

    @abstractmethod
    def extract_metrics(self) -> dict:
        """
        Return data quality metrics derived from logs or artifacts.
        Called after every run (success and failure).

        Examples:
            {"rows_affected": 200_000, "execution_time_sec": 3.2, "models_run": 2}
        """

    @abstractmethod
    def extract_error(self) -> str | None:
        """
        Return a structured error message extracted from logs or artifacts.
        Called only on failure, before the error event is emitted.

        Return None to keep the original exception message unchanged.

        Examples:
            'column "price" does not exist'   ← dbt SQL error
            'Task fetch_orders failed: ...'   ← Airflow task log
        """
