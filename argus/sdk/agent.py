"""
argus.init() — global setup.

설정 우선순위 (높은 순):
  1. init() 명시적 파라미터
  2. 환경 변수 (ANTHROPIC_API_KEY, SLACK_WEBHOOK 등 비밀값)
  3. argus.toml (LLM 설정, custom_rules 등 동작 설정)
  4. 코드 기본값

Registers sys.excepthook so unhandled exceptions are captured
even without a @watch decorator.
"""
from __future__ import annotations

import logging
import os
import sys
import tomllib
import traceback
import uuid
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger("argus.agent")

_config: dict = {}
_initialized = False


def init(
    transport: str = "local",
    endpoint: str = "http://localhost:7070/events",
    slack_webhook: str | None = None,
    llm_backend: str | None = None,
    anthropic_api_key: str | None = None,
    ollama_url: str | None = None,
    ollama_model: str | None = None,
    db_path: str | None = None,
    custom_rules: list | None = None,
    config_file: str = "argus.toml",
) -> None:
    """
    Initialize Argus globally.

    설정은 argus.toml에서 관리하고, 비밀값만 환경 변수로 주입하는 것을 권장한다:

        # argus.toml
        [llm]
        backend = "ollama"
        ollama_model = "qwen2.5:7b"

        [[rules]]
        pattern = 'row count too low'
        error_type = "volume_drop"
        ...

        # .env (비밀값만)
        ANTHROPIC_API_KEY=sk-ant-...
        SLACK_WEBHOOK=https://hooks.slack.com/...

        # 각 파이프라인 스크립트
        argus.init()  # argus.toml + 환경 변수 자동 읽기

    config_file 경로는 현재 작업 디렉토리 기준으로 탐색한다.
    명시적 파라미터는 toml/환경 변수보다 항상 우선한다.
    """
    global _config, _initialized

    toml = _load_toml(config_file)
    llm_toml = toml.get("llm", {})
    storage_toml = toml.get("storage", {})
    rules_toml = toml.get("rules", [])

    # 우선순위: 명시적 파라미터 > 환경 변수 > toml > 기본값
    _config = {
        "transport": transport,
        "endpoint": endpoint,
        "slack_webhook": (
            slack_webhook
            or os.environ.get("SLACK_WEBHOOK")
        ),
        "llm_backend": (
            llm_backend
            or os.environ.get("ARGUS_LLM_BACKEND")
            or llm_toml.get("backend", "anthropic")
        ),
        "anthropic_api_key": (
            anthropic_api_key
            or os.environ.get("ANTHROPIC_API_KEY")
        ),
        "ollama_url": (
            ollama_url
            or os.environ.get("ARGUS_OLLAMA_URL")
            or llm_toml.get("ollama_url")
        ),
        "ollama_model": (
            ollama_model
            or os.environ.get("ARGUS_OLLAMA_MODEL")
            or llm_toml.get("ollama_model")
        ),
        "db_path": (
            db_path
            or os.environ.get("ARGUS_DB_PATH")
            or storage_toml.get("db_path", "argus.db")
        ),
        # 명시적 custom_rules가 있으면 toml rules를 대체한다.
        "custom_rules": custom_rules if custom_rules is not None else _parse_rules(rules_toml),
    }

    # Bootstrap engine singleton
    from argus.engine.pipeline import EnginePipeline
    EnginePipeline.initialize(_config)

    # Register global exception hook
    _register_excepthook()
    _initialized = True


def get_config() -> dict:
    return _config


# ── toml 로더 ─────────────────────────────────────────────────────────────────

def _load_toml(config_file: str) -> dict:
    """
    config_file을 탐색해 로드한다.

    절대 경로이면 그 위치만 확인한다.
    상대 경로(기본값 "argus.toml")이면 cwd에서 시작해 루트까지
    상위 디렉토리를 순서대로 탐색한다 (pyproject.toml과 동일한 방식).
    파일이 없으면 빈 dict를 반환한다.
    """
    path = Path(config_file)

    if path.is_absolute():
        candidates = [path]
    else:
        # cwd → 부모 → ... → 루트 순으로 탐색
        candidates = [p / config_file for p in [Path.cwd(), *Path.cwd().parents]]

    for candidate in candidates:
        if candidate.exists():
            try:
                with open(candidate, "rb") as f:
                    data = tomllib.load(f)
                logger.debug("argus.toml 로드: %s", candidate)
                return data
            except Exception as e:
                logger.warning("argus.toml 로드 실패 (%s): %s", candidate, e)
                return {}

    return {}


def _parse_rules(rules_toml: list[dict]) -> list:
    """toml [[rules]] 항목을 CustomRule 객체 리스트로 변환한다."""
    if not rules_toml:
        return []
    from argus.engine.classifier import CustomRule
    rules = []
    for r in rules_toml:
        try:
            rules.append(CustomRule(
                pattern=r["pattern"],
                error_type=r["error_type"],
                severity=r.get("severity", "error"),
                description=r.get("description", ""),
                needs_llm=r.get("needs_llm", True),
            ))
        except KeyError as e:
            logger.warning("argus.toml rule에 필수 필드 누락: %s — %s", e, r)
    return rules


# ── excepthook ───────────────────────────────────────────────────────────────

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
