"""
Slack notifier — sends formatted error summaries to a Slack webhook.
"""
from __future__ import annotations

import json
import logging
import urllib.request
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from argus.engine.classifier import ErrorType

logger = logging.getLogger("argus.slack")

SEVERITY_EMOJI = {
    "warning":  ":warning:",
    "error":    ":red_circle:",
    "critical": ":rotating_light:",
    "info":     ":white_check_mark:",
}


class SlackNotifier:
    def __init__(self, webhook_url: str | None = None):
        self.webhook_url = webhook_url

    def send_error(self, event: dict, error_type: "ErrorType") -> None:
        if not self.webhook_url:
            return

        severity = event.get("severity", "error")
        emoji = SEVERITY_EMOJI.get(severity, ":red_circle:")
        layer = event.get("layer", "unknown").upper()
        error_class = event.get("error_class", "")
        fn = event.get("function", "")
        diagnosis = event.get("diagnosis", "No diagnosis available.")
        handled_by = event.get("handled_by", "rule")
        duration = event.get("duration_sec")

        duration_str = f"  |  `{duration:.1f}s`" if duration else ""
        handled_str = "🤖 LLM" if handled_by == "llm" else "📋 Rule"

        blocks = [
            {
                "type": "header",
                "text": {
                    "type": "plain_text",
                    "text": f"{emoji}  [{layer}] {error_type.name}",
                }
            },
            {
                "type": "section",
                "fields": [
                    {"type": "mrkdwn", "text": f"*Function*\n`{fn}`"},
                    {"type": "mrkdwn", "text": f"*Exception*\n`{error_class}`"},
                    {"type": "mrkdwn", "text": f"*Handled by*\n{handled_str}{duration_str}"},
                    {"type": "mrkdwn", "text": f"*Severity*\n{severity}"},
                ],
            },
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"*Diagnosis*\n{diagnosis}",
                },
            },
            {"type": "divider"},
        ]

        self._post({"blocks": blocks})

    def _post(self, payload: dict) -> None:
        try:
            data = json.dumps(payload).encode()
            req = urllib.request.Request(
                self.webhook_url,
                data=data,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            urllib.request.urlopen(req, timeout=5)
        except Exception as e:
            logger.warning("Slack notification failed: %s", e)
