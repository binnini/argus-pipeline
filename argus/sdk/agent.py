"""
argus.init() — global setup.

Registers sys.excepthook so unhandled exceptions are captured
even without a @watch decorator.
"""
from __future__ import annotations

import sys
import traceback
import uuid
from datetime import datetime, timezone

_config: dict = {}
_initialized = False


def init(
    transport: str = "local",
    endpoint: str = "http://localhost:7070/events",
    slack_webhook: str | None = None,
    anthropic_api_key: str | None = None,
    db_path: str = "argus.db",
) -> None:
    """
    Initialize Argus globally.

        import argus
        argus.init(
            transport="local",
            slack_webhook="https://hooks.slack.com/...",
            anthropic_api_key="sk-ant-...",
        )

    After calling init(), all unhandled exceptions are automatically
    captured and analyzed — no @watch decorator needed.
    """
    global _config, _initialized

    _config = {
        "transport": transport,
        "endpoint": endpoint,
        "slack_webhook": slack_webhook,
        "anthropic_api_key": anthropic_api_key,
        "db_path": db_path,
    }

    # Bootstrap engine singleton
    from argus.engine.pipeline import EnginePipeline
    EnginePipeline.initialize(_config)

    # Register global exception hook
    _register_excepthook()
    _initialized = True


def get_config() -> dict:
    return _config


def _register_excepthook() -> None:
    original_hook = sys.excepthook

    def argus_excepthook(exc_type, exc_value, exc_tb):
        # Don't interfere with KeyboardInterrupt
        if issubclass(exc_type, KeyboardInterrupt):
            original_hook(exc_type, exc_value, exc_tb)
            return

        tb_str = "".join(traceback.format_exception(exc_type, exc_value, exc_tb))
        event = {
            "event_id": str(uuid.uuid4()),
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "layer": "unknown",
            "function": "unhandled",
            "error_class": exc_type.__name__,
            "error_message": str(exc_value),
            "traceback_raw": tb_str,
            "traceback_summary": _summarize(tb_str),
            "severity": "critical",
            "metrics": {},
        }

        try:
            from argus.engine.pipeline import EnginePipeline
            EnginePipeline.get_instance().handle_error(event)
        except Exception:
            pass  # Never suppress the original exception

        original_hook(exc_type, exc_value, exc_tb)

    sys.excepthook = argus_excepthook


def _summarize(tb: str) -> str:
    lines = [l for l in tb.strip().splitlines() if l.strip()]
    if len(lines) <= 3:
        return "\n".join(lines)
    return "\n".join(lines[:1] + ["..."] + lines[-2:])
