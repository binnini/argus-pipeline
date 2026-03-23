"""
LoadLayer — wraps data loading steps.

Tracks: target, write mode, expected vs loaded row counts.
Emits a warning event if data loss is detected even without an exception.
"""
from __future__ import annotations

from argus.sdk.base import BaseLayer


class LoadLayer(BaseLayer):
    def __init__(
        self,
        target: str = "unknown",
        write_mode: str = "append",
        config: dict | None = None,
        analyzer=None,
    ):
        super().__init__(layer="load", config=config, analyzer=analyzer)
        self.target = target
        self.write_mode = write_mode
        self._expected_count: int | None = None
        self._loaded_count: int | None = None
        self._extra: dict = {}

    # ── metric helpers ──────────────────────────────────────────────────────

    def verify(
        self,
        expected: int,
        loaded: int,
        loss_threshold: float = 0.01,
    ) -> bool:
        """
        Compare expected vs actually loaded row count.
        Emits a warning event if loss exceeds threshold.
        Returns True if within threshold.

            @load.watch
            def write_to_bq(df, client):
                job = client.load_table(df, TABLE)
                load.verify(expected=len(df), loaded=job.output_rows)
        """
        self._expected_count = int(expected)
        self._loaded_count = int(loaded)

        loss_rate = (expected - loaded) / max(expected, 1)
        if loss_rate > loss_threshold:
            self._extra["loss_rate"] = round(loss_rate, 4)
            self.emitter.emit_warning({
                "layer": "load",
                "issue": "data_loss_detected",
                "target": self.target,
                "metrics": {
                    "target": self.target,
                    "write_mode": self.write_mode,
                    "expected_count": expected,
                    "loaded_count": loaded,
                    "loss_rate": round(loss_rate, 4),
                },
            })
            return False
        return True

    def track(self, **extra) -> "LoadLayer":
        """Attach arbitrary metadata to the load event."""
        self._extra.update(extra)
        return self

    def reset(self) -> None:
        self._expected_count = None
        self._loaded_count = None
        self._extra = {}

    # ── BaseLayer override ──────────────────────────────────────────────────

    def _collect_metrics(self) -> dict:
        m = {
            "target": self.target,
            "write_mode": self.write_mode,
            "expected_count": self._expected_count,
            "loaded_count": self._loaded_count,
        }
        if self._expected_count and self._loaded_count is not None:
            loss_rate = (self._expected_count - self._loaded_count) / max(self._expected_count, 1)
            m["loss_rate"] = round(loss_rate, 4)
        m.update(self._extra)
        return {k: v for k, v in m.items() if v is not None}
