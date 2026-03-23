"""
Rule-based classifier — categorizes errors without LLM.

Handles 70-80% of pipeline errors at zero cost.
Only unclassified events proceed to LLM analysis.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Callable


@dataclass
class ErrorType:
    name: str
    severity: str  # warning | error | critical
    description: str
    needs_llm: bool  # False = handle with template, no LLM call


# ── Rule definitions ───────────────────────────────────────────────────────

def _in_tb(event: dict, *keywords: str) -> bool:
    tb = (event.get("traceback_summary") or "").lower()
    msg = (event.get("error_message") or "").lower()
    return any(k in tb or k in msg for k in keywords)


def _metric(event: dict, key: str, default=None):
    return event.get("metrics", {}).get(key, default)


RULES: list[tuple[Callable[[dict], bool], ErrorType]] = [
    # ── Infrastructure ──────────────────────────────────────────────────────
    (
        lambda e: _in_tb(e, "timeout", "timed out", "connection refused", "connection reset"),
        ErrorType("connection_timeout", "error", "Network or DB connection timed out", needs_llm=False),
    ),
    (
        lambda e: _in_tb(e, "out of memory", "memoryerror", "cannot allocate"),
        ErrorType("oom", "critical", "Process ran out of memory", needs_llm=False),
    ),
    (
        lambda e: _in_tb(e, "no space left", "disk full", "diskfull"),
        ErrorType("disk_full", "critical", "Disk space exhausted", needs_llm=False),
    ),

    # ── Schema ──────────────────────────────────────────────────────────────
    (
        lambda e: _in_tb(
            e,
            "column", "does not exist", "no such column",
            "unknown column", "invalid column", "keyerror",
        ),
        ErrorType("schema_change", "error", "Column missing or renamed — likely upstream schema change", needs_llm=True),
    ),
    (
        lambda e: _in_tb(e, "could not convert", "invalid input syntax", "datatype mismatch", "typeerror"),
        ErrorType("type_mismatch", "error", "Data type incompatibility detected", needs_llm=True),
    ),

    # ── Data quality ────────────────────────────────────────────────────────
    (
        lambda e: (_metric(e, "max_null_spike") or 0) > 0.20,
        ErrorType("null_spike", "warning", "Null rate increased by more than 20%", needs_llm=True),
    ),
    (
        lambda e: (_metric(e, "row_count_delta") or 0) < -0.30,
        ErrorType("volume_drop", "warning", "Row count dropped more than 30%", needs_llm=True),
    ),
    (
        lambda e: (_metric(e, "loss_rate") or 0) > 0.01,
        ErrorType("data_loss", "error", "Data loss detected during load", needs_llm=True),
    ),

    # ── Source availability ─────────────────────────────────────────────────
    (
        lambda e: _in_tb(e, "404", "403", "401", "not found", "access denied", "unauthorized"),
        ErrorType("source_unavailable", "error", "Source returned access or not-found error", needs_llm=False),
    ),
    (
        lambda e: _in_tb(e, "rate limit", "too many requests", "429"),
        ErrorType("rate_limit", "warning", "Source API rate limit hit", needs_llm=False),
    ),
]

# Fallback when no rule matches
UNKNOWN = ErrorType("unknown", "error", "Unclassified error — requires LLM analysis", needs_llm=True)


# ── Public API ─────────────────────────────────────────────────────────────

def classify(event: dict) -> ErrorType:
    """
    Run rules in order and return the first match.
    Returns UNKNOWN if no rule matches.
    """
    for predicate, error_type in RULES:
        try:
            if predicate(event):
                return error_type
        except Exception:
            continue
    return UNKNOWN
