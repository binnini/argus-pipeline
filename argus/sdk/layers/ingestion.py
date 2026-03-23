"""
IngestionLayer — wraps data extraction steps.

Tracks: source type, row count, schema columns.
Does NOT capture actual record values.
"""
from __future__ import annotations

from argus.sdk.base import BaseLayer


class IngestionLayer(BaseLayer):
    def __init__(self, source_type: str = "unknown", config: dict | None = None):
        super().__init__(layer="ingestion", config=config)
        self.source_type = source_type
        self._row_count: int | None = None
        self._schema_columns: list[str] | None = None
        self._extra: dict = {}

    # ── metric helpers ──────────────────────────────────────────────────────

    def track(
        self,
        row_count: int | None = None,
        schema: dict | None = None,
        **extra,
    ) -> "IngestionLayer":
        """
        Record runtime metrics. Call this inside the watched function.

            @ingestion.watch
            def fetch(conn):
                df = pd.read_sql(query, conn)
                ingestion.track(row_count=len(df), schema=df.dtypes.to_dict())
                return df
        """
        if row_count is not None:
            self._row_count = int(row_count)
        if schema is not None:
            # Store column names only — no values
            self._schema_columns = list(schema.keys())
        self._extra.update(extra)
        return self

    def reset(self) -> None:
        """Clear state between runs (useful in long-running processes)."""
        self._row_count = None
        self._schema_columns = None
        self._extra = {}

    # ── BaseLayer override ──────────────────────────────────────────────────

    def _collect_metrics(self) -> dict:
        m = {
            "source_type": self.source_type,
            "row_count": self._row_count,
            "schema_columns": self._schema_columns,
        }
        m.update(self._extra)
        return {k: v for k, v in m.items() if v is not None}
