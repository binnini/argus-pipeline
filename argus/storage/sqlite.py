"""
Storage — SQLite-backed persistence for errors and token usage.
"""
from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Generator


class Storage:
    def __init__(self, db_path: str = "argus.db"):
        self.db_path = db_path
        self._init_schema()

    # ── schema ──────────────────────────────────────────────────────────────

    def _init_schema(self) -> None:
        with self._conn() as conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS errors (
                    id           INTEGER PRIMARY KEY AUTOINCREMENT,
                    event_id     TEXT UNIQUE,
                    timestamp    TEXT,
                    layer        TEXT,
                    function     TEXT,
                    error_type   TEXT,
                    error_class  TEXT,
                    error_message TEXT,
                    severity     TEXT,
                    handled_by   TEXT,
                    diagnosis    TEXT,
                    metrics_json TEXT,
                    duration_sec REAL
                );

                CREATE TABLE IF NOT EXISTS token_usage (
                    id           INTEGER PRIMARY KEY AUTOINCREMENT,
                    event_id     TEXT,
                    timestamp    TEXT,
                    layer        TEXT,
                    handled_by   TEXT,
                    tokens_in    INTEGER DEFAULT 0,
                    tokens_out   INTEGER DEFAULT 0,
                    tokens_saved INTEGER DEFAULT 0,
                    cost_usd     REAL    DEFAULT 0,
                    cost_saved   REAL    DEFAULT 0,
                    model        TEXT
                );

                CREATE TABLE IF NOT EXISTS successes (
                    id           INTEGER PRIMARY KEY AUTOINCREMENT,
                    event_id     TEXT,
                    timestamp    TEXT,
                    layer        TEXT,
                    function     TEXT,
                    duration_sec REAL
                );

                CREATE INDEX IF NOT EXISTS idx_errors_timestamp   ON errors(timestamp);
                CREATE INDEX IF NOT EXISTS idx_errors_layer       ON errors(layer);
                CREATE INDEX IF NOT EXISTS idx_errors_error_type  ON errors(error_type);
            """)

    # ── writes ──────────────────────────────────────────────────────────────

    def save_error(self, event: dict, llm_result=None) -> dict:
        now = datetime.now(timezone.utc).isoformat()
        with self._conn() as conn:
            conn.execute(
                """INSERT OR REPLACE INTO errors
                   (event_id, timestamp, layer, function, error_type,
                    error_class, error_message, severity, handled_by,
                    diagnosis, metrics_json, duration_sec)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    event.get("event_id"),
                    event.get("timestamp", now),
                    event.get("layer"),
                    event.get("function"),
                    event.get("error_type"),
                    event.get("error_class"),
                    event.get("error_message"),
                    event.get("severity"),
                    event.get("handled_by"),
                    event.get("diagnosis"),
                    json.dumps(event.get("metrics", {})),
                    event.get("duration_sec"),
                ),
            )
            if llm_result:
                conn.execute(
                    """INSERT INTO token_usage
                       (event_id, timestamp, layer, handled_by,
                        tokens_in, tokens_out, tokens_saved,
                        cost_usd, cost_saved, model)
                       VALUES (?,?,?,?,?,?,?,?,?,?)""",
                    (
                        event.get("event_id"),
                        event.get("timestamp", now),
                        event.get("layer"),
                        "llm",
                        llm_result.tokens_input,
                        llm_result.tokens_output,
                        llm_result.tokens_saved,
                        llm_result.cost_usd,
                        llm_result.cost_saved_usd,
                        llm_result.model,
                    ),
                )
            else:
                # Rule-handled: record tokens_saved baseline
                from argus.engine.llm import BASELINE_TOKENS_PER_ERROR, PRICE_INPUT_PER_1M
                saved = BASELINE_TOKENS_PER_ERROR
                conn.execute(
                    """INSERT INTO token_usage
                       (event_id, timestamp, layer, handled_by,
                        tokens_saved, cost_saved, model)
                       VALUES (?,?,?,?,?,?,?)""",
                    (
                        event.get("event_id"),
                        event.get("timestamp", now),
                        event.get("layer"),
                        "rule",
                        saved,
                        round(saved * PRICE_INPUT_PER_1M / 1_000_000, 6),
                        "none",
                    ),
                )
        return event

    def save_success(self, event: dict) -> None:
        with self._conn() as conn:
            conn.execute(
                """INSERT OR IGNORE INTO successes
                   (event_id, timestamp, layer, function, duration_sec)
                   VALUES (?,?,?,?,?)""",
                (
                    event.get("event_id"),
                    event.get("timestamp"),
                    event.get("layer"),
                    event.get("function"),
                    event.get("duration_sec"),
                ),
            )

    # ── reads ───────────────────────────────────────────────────────────────

    def get_recent_errors(self, limit: int = 50) -> list[dict]:
        with self._conn() as conn:
            rows = conn.execute(
                """SELECT * FROM errors ORDER BY timestamp DESC LIMIT ?""",
                (limit,),
            ).fetchall()
        return [_row_to_dict(r) for r in rows]

    def get_token_summary(self) -> dict:
        with self._conn() as conn:
            row = conn.execute("""
                SELECT
                    COUNT(*)                          AS total_errors,
                    SUM(CASE WHEN handled_by='rule' THEN 1 ELSE 0 END) AS rule_handled,
                    SUM(CASE WHEN handled_by='llm'  THEN 1 ELSE 0 END) AS llm_called,
                    COALESCE(SUM(tokens_in + tokens_out), 0)            AS tokens_used,
                    COALESCE(SUM(tokens_saved), 0)                      AS tokens_saved,
                    COALESCE(SUM(cost_usd), 0)                          AS cost_usd,
                    COALESCE(SUM(cost_saved), 0)                        AS cost_saved_usd,
                    CASE WHEN SUM(CASE WHEN handled_by='llm' THEN 1 ELSE 0 END) > 0
                         THEN CAST(SUM(tokens_in+tokens_out) AS REAL)
                              / SUM(CASE WHEN handled_by='llm' THEN 1 ELSE 0 END)
                         ELSE 0
                    END                                                 AS avg_tokens_per_call
                FROM token_usage
            """).fetchone()
        return dict(row) if row else {}

    def get_token_summary_today(self) -> dict:
        today = datetime.now(timezone.utc).date().isoformat()
        with self._conn() as conn:
            row = conn.execute("""
                SELECT
                    COUNT(*)                          AS total_errors,
                    SUM(CASE WHEN handled_by='rule' THEN 1 ELSE 0 END) AS rule_handled,
                    SUM(CASE WHEN handled_by='llm'  THEN 1 ELSE 0 END) AS llm_called,
                    COALESCE(SUM(tokens_saved), 0)                      AS tokens_saved,
                    COALESCE(SUM(cost_saved), 0)                        AS cost_saved_usd
                FROM token_usage
                WHERE DATE(timestamp) = ?
            """, (today,)).fetchone()
        return dict(row) if row else {}

    # ── helpers ─────────────────────────────────────────────────────────────

    @contextmanager
    def _conn(self) -> Generator[sqlite3.Connection, None, None]:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()


def _row_to_dict(row: sqlite3.Row) -> dict:
    d = dict(row)
    if "metrics_json" in d and d["metrics_json"]:
        try:
            d["metrics"] = json.loads(d["metrics_json"])
        except Exception:
            d["metrics"] = {}
    return d
