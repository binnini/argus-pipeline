"""
Emitter — delivers events from SDK to the Engine.

Transport options (configured via argus.init):
  - "local"  : in-process call (default, no network)
  - "http"   : POST to a running Argus server
  - "queue"  : put on an asyncio queue (for async pipelines)
"""
from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING

logger = logging.getLogger("argus.emitter")

# Lazy import to avoid circular dependency
_engine = None


def _get_engine():
    global _engine
    if _engine is None:
        from argus.engine.pipeline import EnginePipeline
        _engine = EnginePipeline.get_instance()
    return _engine


class Emitter:
    def __init__(self, config: dict):
        self.transport = config.get("transport", "local")
        self.endpoint = config.get("endpoint", "http://localhost:7070/events")

    def emit(self, event: dict) -> None:
        """Emit an error event for analysis."""
        if self.transport == "local":
            self._emit_local(event)
        elif self.transport == "http":
            self._emit_http(event)
        else:
            logger.warning("Unknown transport: %s — falling back to local", self.transport)
            self._emit_local(event)

    def emit_success(self, event: dict) -> None:
        """Emit a success event (lightweight, no LLM)."""
        if self.transport == "local":
            try:
                _get_engine().handle_success(event)
            except Exception:
                logger.debug("Engine not available for success event")
        # HTTP transport: success events are best-effort, no retry

    def emit_warning(self, event: dict) -> None:
        """Emit a warning event (e.g. data loss detected before exception)."""
        event.setdefault("severity", "warning")
        self.emit(event)

    # ── transports ──────────────────────────────────────────────────────────

    def _emit_local(self, event: dict) -> None:
        try:
            _get_engine().handle_error(event)
        except Exception as e:
            logger.error("Engine failed to handle event: %s", e)
            logger.debug("Dropped event: %s", json.dumps(event, default=str))

    def _emit_http(self, event: dict) -> None:
        try:
            import urllib.request
            data = json.dumps(event, default=str).encode()
            req = urllib.request.Request(
                self.endpoint,
                data=data,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            urllib.request.urlopen(req, timeout=3)
        except Exception as e:
            logger.warning("HTTP emit failed (%s) — event dropped", e)
