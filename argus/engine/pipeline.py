"""
EnginePipeline — orchestrates the full error handling flow.

Flow:
  event → classify → [rule-handled OR llm-analyzed] → store → notify
"""
from __future__ import annotations

import logging
from typing import ClassVar

logger = logging.getLogger("argus.engine")

_instance: "EnginePipeline | None" = None


class EnginePipeline:
    _instance: ClassVar["EnginePipeline | None"] = None

    def __init__(self, config: dict):
        self.config = config
        from argus.storage.sqlite import Storage
        from argus.outputs.slack import SlackNotifier
        self.storage = Storage(config.get("db_path", "argus.db"))
        self.notifier = SlackNotifier(config.get("slack_webhook"))

    # ── singleton ───────────────────────────────────────────────────────────

    @classmethod
    def initialize(cls, config: dict) -> "EnginePipeline":
        cls._instance = cls(config)
        return cls._instance

    @classmethod
    def get_instance(cls) -> "EnginePipeline":
        if cls._instance is None:
            # Auto-initialize with defaults if argus.init() was not called
            cls._instance = cls({})
        return cls._instance

    # ── main handlers ───────────────────────────────────────────────────────

    def handle_error(self, event: dict) -> dict:
        """
        Full analysis pipeline for an error event.
        Returns the enriched event record.
        """
        from argus.engine.classifier import classify
        from argus.engine.context import build_prompt
        from argus.engine.llm import call_llm

        # 1. Classify (custom rules run before built-in rules)
        error_type = classify(event, self.config.get("custom_rules"))
        event["error_type"] = error_type.name
        event["severity"] = error_type.severity

        # 2. Route: rule-handled vs LLM
        llm_result = None
        if error_type.needs_llm:
            prompt = build_prompt(event, error_type)
            llm_result = call_llm(
                prompt,
                backend=self.config.get("llm_backend", "anthropic"),
                api_key=self.config.get("anthropic_api_key"),
                ollama_url=self.config.get("ollama_url"),
                ollama_model=self.config.get("ollama_model"),
            )
            event["diagnosis"] = llm_result.diagnosis
            event["handled_by"] = "llm"
        else:
            event["diagnosis"] = error_type.description
            event["handled_by"] = "rule"

        # 3. Store
        record = self.storage.save_error(event, llm_result)

        # 4. Notify
        self.notifier.send_error(event, error_type)

        logger.info(
            "[%s] %s · %s · handled_by=%s",
            event.get("layer"), event.get("error_type"),
            event.get("error_class"), event.get("handled_by"),
        )
        return record

    def handle_success(self, event: dict) -> None:
        """Lightweight success event — stored but not analyzed."""
        self.storage.save_success(event)
