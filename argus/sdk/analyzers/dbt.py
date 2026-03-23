"""
DbtLogAnalyzer — extracts metrics and errors from dbt artifacts.

Reads target/run_results.json which dbt writes on every run (success and failure).
No extra DuckDB queries needed.

Usage:
    transform = TransformLayer(analyzer=DbtLogAnalyzer("/path/to/dbt/project"))

    @transform.watch
    def run_dbt():
        subprocess.run(["dbt", "run"], check=True)
"""
from __future__ import annotations

import json
import logging
from pathlib import Path

from argus.sdk.analyzers.base import LogAnalyzer

logger = logging.getLogger("argus.analyzers.dbt")


class DbtLogAnalyzer(LogAnalyzer):
    def __init__(self, project_dir: str = "."):
        self._project_dir = Path(project_dir)

    # ── LogAnalyzer interface ───────────────────────────────────────────────

    def extract_metrics(self) -> dict:
        """
        Aggregate metrics from run_results.json:
          - models_run       : number of models executed
          - rows_affected    : total rows written across all models
          - execution_time_sec: total dbt execution time
          - model_statuses   : per-model status summary {"model_name": "success"|"error"}
        """
        results = self._load_results()
        if not results:
            return {}

        model_statuses = {
            r.get("unique_id", "").split(".")[-1]: r.get("status", "unknown")
            for r in results
        }
        rows_affected = sum(
            r.get("adapter_response", {}).get("rows_affected", 0)
            for r in results
        )
        execution_time = round(sum(r.get("execution_time", 0) for r in results), 3)

        return {
            "models_run": len(results),
            "rows_affected": rows_affected,
            "execution_time_sec": execution_time,
            "model_statuses": model_statuses,
        }

    def extract_error(self) -> str | None:
        """
        Return the first model-level error message from run_results.json.
        This gives Argus classifier a meaningful message (e.g. 'column X does not exist')
        instead of the raw CalledProcessError from subprocess.
        """
        results = self._load_results()
        for r in results:
            if r.get("status") == "error":
                msg = r.get("message") or r.get("msg") or ""
                if msg:
                    logger.debug("dbt error extracted: %s", msg[:120])
                    return msg
        return None

    # ── helpers ─────────────────────────────────────────────────────────────

    def _load_results(self) -> list[dict]:
        path = self._project_dir / "target" / "run_results.json"
        if not path.exists():
            logger.debug("run_results.json not found at %s", path)
            return []
        try:
            with open(path) as f:
                return json.load(f).get("results", [])
        except Exception as e:
            logger.warning("Failed to parse run_results.json: %s", e)
            return []
