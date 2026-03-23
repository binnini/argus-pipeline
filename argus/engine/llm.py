"""
LLM caller — calls Anthropic API and tracks token usage.

Token savings are calculated by comparing actual usage
against a baseline of "paste raw logs into a chat" (~8,000 tokens).
"""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass

logger = logging.getLogger("argus.llm")

# Baseline: average tokens when a human pastes raw logs into an LLM CLI
BASELINE_TOKENS_PER_ERROR = 8_000

# claude-sonnet-4-6 pricing (per 1M tokens, as of 2026-03)
PRICE_INPUT_PER_1M = 3.0
PRICE_OUTPUT_PER_1M = 15.0


@dataclass
class LLMResult:
    diagnosis: str
    tokens_input: int
    tokens_output: int
    tokens_saved: int
    cost_usd: float
    cost_saved_usd: float
    model: str


def call_llm(prompt: str, api_key: str | None = None) -> LLMResult:
    """
    Call Claude and return diagnosis + token accounting.
    Falls back to a stub if no API key is configured.
    """
    key = api_key or os.environ.get("ANTHROPIC_API_KEY")
    if not key:
        logger.warning("No ANTHROPIC_API_KEY — returning stub diagnosis")
        return _stub_result(prompt)

    try:
        import anthropic
        client = anthropic.Anthropic(api_key=key)
        message = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=300,
            system=(
                "You are a concise data pipeline diagnostic assistant. "
                "Respond in plain text, no markdown. "
                "Maximum 5 sentences."
            ),
            messages=[{"role": "user", "content": prompt}],
        )
        diagnosis = message.content[0].text
        t_in = message.usage.input_tokens
        t_out = message.usage.output_tokens
        return _build_result(diagnosis, t_in, t_out, message.model)

    except ImportError:
        logger.error("anthropic package not installed: pip install anthropic")
        return _stub_result(prompt)
    except Exception as e:
        logger.error("LLM call failed: %s", e)
        return _stub_result(prompt)


# ── helpers ────────────────────────────────────────────────────────────────

def _build_result(diagnosis: str, t_in: int, t_out: int, model: str) -> LLMResult:
    actual_tokens = t_in + t_out
    tokens_saved = max(0, BASELINE_TOKENS_PER_ERROR - actual_tokens)

    cost = (t_in * PRICE_INPUT_PER_1M + t_out * PRICE_OUTPUT_PER_1M) / 1_000_000
    cost_saved = tokens_saved * (PRICE_INPUT_PER_1M / 1_000_000)  # conservative estimate

    return LLMResult(
        diagnosis=diagnosis,
        tokens_input=t_in,
        tokens_output=t_out,
        tokens_saved=tokens_saved,
        cost_usd=round(cost, 6),
        cost_saved_usd=round(cost_saved, 6),
        model=model,
    )


def _stub_result(prompt: str) -> LLMResult:
    estimated_tokens = len(prompt.split())
    return LLMResult(
        diagnosis="[Stub] LLM not configured. Set ANTHROPIC_API_KEY to enable diagnosis.",
        tokens_input=estimated_tokens,
        tokens_output=20,
        tokens_saved=max(0, BASELINE_TOKENS_PER_ERROR - estimated_tokens),
        cost_usd=0.0,
        cost_saved_usd=0.0,
        model="stub",
    )
