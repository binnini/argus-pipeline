"""
TransformLayer — wraps data transformation steps.

Tracks: row count delta, null rate delta (before vs after).
Does NOT store actual data values.
"""
from __future__ import annotations

from argus.sdk.base import BaseLayer


class TransformLayer(BaseLayer):
    def __init__(self, config: dict | None = None, analyzer=None):
        super().__init__(layer="transform", config=config, analyzer=analyzer)
        self._before: dict = {}
        self._after: dict = {}

    # ── metric helpers ──────────────────────────────────────────────────────

    def snapshot(self, df, stage: str = "before") -> object:
        """
        Capture a statistical snapshot of a DataFrame.
        Works with pandas and polars DataFrames.
        Returns the DataFrame unchanged for chaining.

            @transform.watch
            def clean(df):
                transform.snapshot(df, "before")
                df = df.dropna(subset=["user_id"])
                transform.snapshot(df, "after")
                return df
        """
        stats = _dataframe_stats(df)
        if stage == "before":
            self._before = stats
        else:
            self._after = stats
        return df

    def reset(self) -> None:
        self._before = {}
        self._after = {}

    # ── BaseLayer override ──────────────────────────────────────────────────

    def _collect_metrics(self) -> dict:
        if not self._before:
            return {}

        m: dict = {
            "row_count_before": self._before.get("row_count"),
        }

        if self._after:
            before_n = self._before.get("row_count", 0)
            after_n = self._after.get("row_count", 0)
            row_delta = (after_n - before_n) / max(before_n, 1)
            m["row_count_after"] = after_n
            m["row_count_delta"] = round(row_delta, 4)

            # Per-column null rate delta
            null_deltas = {}
            for col in self._before.get("columns", []):
                before_null = self._before["null_rates"].get(col, 0)
                after_null = self._after["null_rates"].get(col, 0)
                delta = round(after_null - before_null, 4)
                if abs(delta) > 0.001:  # only report meaningful changes
                    null_deltas[col] = delta

            if null_deltas:
                m["null_rate_delta"] = null_deltas
                m["max_null_spike"] = max(null_deltas.values(), default=0)

        return m


# ── helpers ────────────────────────────────────────────────────────────────

def _dataframe_stats(df) -> dict:
    """Extract stats from pandas or polars DataFrame. No actual values stored."""
    try:
        # pandas
        return {
            "row_count": len(df),
            "columns": list(df.columns),
            "null_rates": {
                col: float(df[col].isnull().mean())
                for col in df.columns
            },
        }
    except AttributeError:
        pass

    try:
        # polars
        import polars as pl
        null_rates = {
            col: df[col].null_count() / max(len(df), 1)
            for col in df.columns
        }
        return {
            "row_count": len(df),
            "columns": list(df.columns),
            "null_rates": null_rates,
        }
    except Exception:
        pass

    # Fallback: only row count
    try:
        return {"row_count": len(df), "columns": [], "null_rates": {}}
    except Exception:
        return {}
