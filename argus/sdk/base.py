"""
Base layer — shared watch decorator and event emission logic.
All layer classes inherit from here.
"""
from __future__ import annotations

import functools
import time
import traceback
import uuid
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any, Callable

from argus.sdk.emitter import Emitter

if TYPE_CHECKING:
    from argus.sdk.analyzers.base import LogAnalyzer


class BaseLayer:
    def __init__(
        self,
        layer: str,
        config: dict | None = None,
        analyzer: "LogAnalyzer | None" = None,
    ):
        self.layer = layer
        self.emitter = Emitter(config or {})
        self.analyzer = analyzer

    # ── decorator ──────────────────────────────────────────────────────────

    def watch(self, fn: Callable | None = None, *, name: str | None = None):
        """
        Decorator that captures exceptions and emits structured events.

        Usage:
            @ingestion.watch
            def fetch(): ...

            @ingestion.watch(name="custom_name")
            def fetch(): ...
        """
        if fn is None:
            return lambda f: self.watch(f, name=name)

        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            start = time.monotonic()
            try:
                result = fn(*args, **kwargs)
                duration = round(time.monotonic() - start, 3)
                self._on_success(fn, result, duration)
                return result
            except Exception as exc:
                duration = round(time.monotonic() - start, 3)
                self._on_error(fn, exc, duration, name=name)
                raise

        return wrapper

    # ── event builders ─────────────────────────────────────────────────────

    def _on_error(
        self,
        fn: Callable,
        exc: Exception,
        duration: float,
        name: str | None = None,
    ) -> None:
        tb_raw = traceback.format_exc()

        # Analyzer may provide a more informative error message
        # (e.g. dbt SQL error vs raw CalledProcessError)
        error_message = str(exc)
        if self.analyzer:
            extracted = self.analyzer.extract_error()
            if extracted:
                error_message = extracted

        event = {
            "event_id": str(uuid.uuid4()),
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "layer": self.layer,
            "function": name or fn.__name__,
            "error_class": type(exc).__name__,
            "error_message": error_message,
            "traceback_raw": tb_raw,
            "traceback_summary": _summarize_traceback(tb_raw),
            "duration_sec": duration,
            "severity": "error",
            "metrics": self._merge_metrics(),
        }
        self.emitter.emit(event)

    def _on_success(self, fn: Callable, result: Any, duration: float) -> None:
        # Success events are lightweight — no LLM call needed
        event = {
            "event_id": str(uuid.uuid4()),
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "layer": self.layer,
            "function": fn.__name__,
            "severity": "info",
            "duration_sec": duration,
            "metrics": self._merge_metrics(),
        }
        self.emitter.emit_success(event)

    # ── override in subclasses ─────────────────────────────────────────────

    def _collect_metrics(self) -> dict:
        return {}

    def _merge_metrics(self) -> dict:
        """
        Merge analyzer metrics with layer metrics.
        Layer metrics (manually tracked via track()/snapshot()) take precedence
        over analyzer metrics, as they are more intentional.
        """
        metrics = {}
        if self.analyzer:
            metrics.update(self.analyzer.extract_metrics())
        metrics.update(self._collect_metrics())
        return metrics


# ── helpers ────────────────────────────────────────────────────────────────

def _summarize_traceback(tb: str) -> str:
    """
    Reduce a full traceback to the essential signal.
    Keeps: exception type line + last 2 meaningful lines.
    Raw traceback is stored separately and never sent to LLM.
    """
    lines = [l for l in tb.strip().splitlines() if l.strip()]
    if len(lines) <= 3:
        return "\n".join(lines)
    return "\n".join(lines[:1] + ["..."] + lines[-2:])
