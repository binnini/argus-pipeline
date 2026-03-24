"""
LLM caller — Anthropic API 또는 로컬 Ollama를 호출하고 토큰 사용량을 추적한다.

백엔드는 argus.init(llm_backend=...) 으로 명시적으로 지정한다:
  - "anthropic" (기본값): Anthropic Claude API 사용, ANTHROPIC_API_KEY 필요
  - "ollama"            : 로컬 Ollama 사용, 비용 $0

Token savings는 "사람이 로그를 LLM에 직접 붙여넣는" 베이스라인(~8,000 토큰)과 비교해 계산한다.
"""
from __future__ import annotations

import json
import logging
import os
import urllib.error
import urllib.request
from dataclasses import dataclass

logger = logging.getLogger("argus.llm")

# Baseline: 사람이 raw 로그를 LLM CLI에 붙여넣을 때의 평균 토큰 수
BASELINE_TOKENS_PER_ERROR = 8_000

# claude-sonnet-4-6 가격 (2026-03 기준, per 1M tokens)
PRICE_INPUT_PER_1M = 3.0
PRICE_OUTPUT_PER_1M = 15.0

OLLAMA_DEFAULT_URL = "http://localhost:11434"
OLLAMA_DEFAULT_MODEL = "llama3.2"

_SYSTEM_PROMPT = (
    "You are a concise data pipeline diagnostic assistant. "
    "Respond in plain text, no markdown. "
    "Maximum 5 sentences."
)


@dataclass
class LLMResult:
    diagnosis: str
    tokens_input: int
    tokens_output: int
    tokens_saved: int
    cost_usd: float
    cost_saved_usd: float
    model: str


def call_llm(
    prompt: str,
    backend: str = "anthropic",
    api_key: str | None = None,
    ollama_url: str | None = None,
    ollama_model: str | None = None,
) -> LLMResult:
    """
    LLM을 호출하고 진단 결과와 토큰 집계를 반환한다.

    backend="anthropic" → Anthropic Claude (api_key 또는 ANTHROPIC_API_KEY 환경변수)
    backend="ollama"    → 로컬 Ollama (ollama_url, ollama_model)
    """
    if backend == "ollama":
        return _call_ollama(
            prompt,
            ollama_url or OLLAMA_DEFAULT_URL,
            ollama_model or OLLAMA_DEFAULT_MODEL,
        )

    if backend == "anthropic":
        key = api_key or os.environ.get("ANTHROPIC_API_KEY")
        if not key:
            logger.warning("ANTHROPIC_API_KEY 미설정 — stub 반환")
            return _stub_result(prompt)
        return _call_anthropic(prompt, key)

    logger.error("알 수 없는 llm_backend: %r (anthropic 또는 ollama 지정)", backend)
    return _stub_result(prompt)


# ── 백엔드 구현 ───────────────────────────────────────────────────────────────

def _call_anthropic(prompt: str, api_key: str) -> LLMResult:
    try:
        import anthropic
        client = anthropic.Anthropic(api_key=api_key)
        message = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=300,
            system=_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": prompt}],
        )
        diagnosis = message.content[0].text
        t_in = message.usage.input_tokens
        t_out = message.usage.output_tokens
        return _build_result(diagnosis, t_in, t_out, message.model)

    except ImportError:
        logger.error("anthropic 패키지 미설치: pip install anthropic")
        return _stub_result(prompt)
    except Exception as e:
        logger.error("Anthropic 호출 실패: %s", e)
        return _stub_result(prompt)


def _call_ollama(prompt: str, base_url: str, model: str) -> LLMResult:
    """
    Ollama의 OpenAI 호환 엔드포인트(/v1/chat/completions)를 호출한다.
    stdlib urllib만 사용 — 추가 의존성 없음.
    """
    url = base_url.rstrip("/") + "/v1/chat/completions"
    payload = json.dumps({
        "model": model,
        "messages": [
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
        ],
        "max_tokens": 300,
        "stream": False,
    }).encode()

    req = urllib.request.Request(
        url,
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            body = json.loads(resp.read())
        diagnosis = body["choices"][0]["message"]["content"]
        usage = body.get("usage", {})
        t_in = usage.get("prompt_tokens", len(prompt.split()))
        t_out = usage.get("completion_tokens", len(diagnosis.split()))
        return _build_result_local(diagnosis, t_in, t_out, model)

    except urllib.error.URLError as e:
        logger.error("Ollama 연결 실패 (%s): %s", url, e)
        return _stub_result(prompt)
    except Exception as e:
        logger.error("Ollama 호출 실패: %s", e)
        return _stub_result(prompt)


# ── 결과 생성 헬퍼 ────────────────────────────────────────────────────────────

def _build_result(diagnosis: str, t_in: int, t_out: int, model: str) -> LLMResult:
    actual_tokens = t_in + t_out
    tokens_saved = max(0, BASELINE_TOKENS_PER_ERROR - actual_tokens)
    cost = (t_in * PRICE_INPUT_PER_1M + t_out * PRICE_OUTPUT_PER_1M) / 1_000_000
    cost_saved = tokens_saved * (PRICE_INPUT_PER_1M / 1_000_000)
    return LLMResult(
        diagnosis=diagnosis,
        tokens_input=t_in,
        tokens_output=t_out,
        tokens_saved=tokens_saved,
        cost_usd=round(cost, 6),
        cost_saved_usd=round(cost_saved, 6),
        model=model,
    )


def _build_result_local(diagnosis: str, t_in: int, t_out: int, model: str) -> LLMResult:
    """로컬 LLM: cost_usd=0, cost_saved는 Anthropic 가격 기준으로 환산해 표시한다."""
    actual_tokens = t_in + t_out
    tokens_saved = max(0, BASELINE_TOKENS_PER_ERROR - actual_tokens)
    cost_saved = tokens_saved * (PRICE_INPUT_PER_1M / 1_000_000)
    return LLMResult(
        diagnosis=diagnosis,
        tokens_input=t_in,
        tokens_output=t_out,
        tokens_saved=tokens_saved,
        cost_usd=0.0,
        cost_saved_usd=round(cost_saved, 6),
        model=f"ollama/{model}",
    )


def _stub_result(prompt: str) -> LLMResult:
    estimated_tokens = len(prompt.split())
    return LLMResult(
        diagnosis="[Stub] LLM 미설정. llm_backend와 api_key 또는 ollama_url을 지정하세요.",
        tokens_input=estimated_tokens,
        tokens_output=20,
        tokens_saved=max(0, BASELINE_TOKENS_PER_ERROR - estimated_tokens),
        cost_usd=0.0,
        cost_saved_usd=0.0,
        model="stub",
    )
