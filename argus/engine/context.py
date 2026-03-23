"""
Context builder — builds a compact, structured prompt for LLM analysis.

Goal: ≤ 500 input tokens per call.
Rule: never include actual data values, only metadata and metrics.
"""
from __future__ import annotations

from argus.engine.classifier import ErrorType


def build_prompt(event: dict, error_type: ErrorType) -> str:
    """
    Construct a concise diagnostic prompt.
    The LLM is asked for cause hypotheses and what to check first.
    """
    layer = event.get("layer", "unknown")
    fn = event.get("function", "unknown")
    error_class = event.get("error_class", "")
    tb_summary = event.get("traceback_summary", "")
    metrics = event.get("metrics", {})

    metrics_lines = _format_metrics(metrics)

    prompt = f"""You are a data pipeline diagnostic assistant.
Analyze the following pipeline error and provide:
1. 1-2 most likely root causes
2. 2-3 specific things the on-call engineer should check first

Keep your response under 5 sentences. Be concrete and actionable.

--- Error Context ---
Layer: {layer}
Function: {fn}
Error type: {error_type.name} — {error_type.description}
Exception: {error_class}
Traceback summary:
{tb_summary}
{metrics_lines}
--- End Context ---"""

    return prompt.strip()


def _format_metrics(metrics: dict) -> str:
    if not metrics:
        return ""

    interesting = {
        "row_count": "Row count",
        "row_count_delta": "Row count delta",
        "row_count_before": "Row count (before transform)",
        "row_count_after": "Row count (after transform)",
        "max_null_spike": "Max null rate increase",
        "null_rate_delta": "Null rate delta by column",
        "source_type": "Source type",
        "target": "Load target",
        "write_mode": "Write mode",
        "expected_count": "Expected rows",
        "loaded_count": "Loaded rows",
        "loss_rate": "Data loss rate",
        "duration_sec": "Duration (sec)",
    }

    lines = ["\nMetrics:"]
    for key, label in interesting.items():
        val = metrics.get(key)
        if val is None:
            continue
        if isinstance(val, float):
            val = f"{val:.2%}" if key.endswith(("delta", "rate", "spike")) else f"{val:.2f}"
        lines.append(f"  {label}: {val}")

    return "\n".join(lines) if len(lines) > 1 else ""
