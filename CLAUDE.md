# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Argus is a **data pipeline monitoring tool** that automatically detects, classifies, and diagnoses pipeline errors using rule-based classification and LLM (Claude via Anthropic API) analysis, then notifies teams via Slack. The goal is to reduce investigation time from ~30 minutes to ~3 minutes.

## Development Commands

All commands run from the `argus/` subdirectory (where `pyproject.toml` lives):

```bash
# Install in dev mode
pip install -e ".[dev]"

# Run all tests (no API key required)
pytest

# Run a single test file
pytest tests/unit/test_classifier.py

# Start dashboard
uvicorn argus.outputs.dashboard.app:app --port 7070

# Docker-based local dev
docker-compose up -d
```

**Required environment variables** (for full functionality):
- `ANTHROPIC_API_KEY` — LLM calls; tests run in stub mode without it
- `SLACK_WEBHOOK` — Slack notifications

## Architecture

The project has two main layers:

### SDK Layer (`argus/argus/sdk/`)
User-facing decorators that wrap pipeline functions to capture events:

- **`agent.py`** — `argus.init()` global setup; registers `sys.excepthook` for unhandled errors
- **`base.py`** — `BaseLayer` with the `@watch` decorator and event builder
- **`emitter.py`** — transports events to the Engine (local call or HTTP)
- **`layers/ingestion.py`** — `IngestionLayer`: tracks source metadata, row counts, schema
- **`layers/transform.py`** — `TransformLayer`: before/after snapshots, null rate deltas
- **`layers/load.py`** — `LoadLayer`: verifies expected vs. actual loaded rows, detects data loss

### Engine Layer (`argus/argus/engine/`)
Processes incoming events through a fixed pipeline:

1. **`classifier.py`** — rule-based categorization into 10 error types; ~70-80% of errors handled here at zero LLM cost
2. **`context.py`** — compresses event to ~500 tokens; **never includes actual data values**, only metadata
3. **`llm.py`** — conditional Claude API call with token tracking; skipped for rule-handled errors
4. **`pipeline.py`** — `EnginePipeline` singleton orchestrating: classify → context → LLM → store → notify

### Error Classification (10 rules)

| Error Type | Triggers LLM? |
|---|---|
| `connection_timeout`, `oom`, `disk_full`, `source_unavailable`, `rate_limit` | No — template diagnosis |
| `schema_change`, `type_mismatch`, `null_spike`, `volume_drop`, `data_loss`, `unknown` | Yes |

Thresholds: `null_spike` >20% null rate increase; `volume_drop` >30% row count drop; `data_loss` >1% loss in load.

### Storage & Output (`argus/argus/storage/`, `argus/argus/outputs/`)

- **`storage/sqlite.py`** — SQLite with 3 tables: `errors`, `token_usage`, `successes`
- **`outputs/slack.py`** — Slack webhook with formatted block messages
- **`outputs/dashboard/app.py`** — FastAPI dashboard at port 7070 showing error history, token savings, cost

## Key Design Decisions

- **Privacy-first**: Context builder never captures actual data values — only schema column names, row counts, null rates
- **Cost optimization**: Rule-based classifier avoids LLM for simple errors; compression reduces tokens from baseline ~8,000 → ~1,200
- **Stub LLM mode**: All tests run without an API key; `EnginePipeline` auto-initializes without `argus.init()`
- **Singleton engine**: `EnginePipeline` uses a module-level singleton; tests reset it between runs

## Test Structure

```
tests/
  unit/            # Classifier, context builder, storage unit tests
  fixtures/        # 7 pre-built error event fixtures (error_cases.py)
  test_integration.py  # End-to-end flow with stub LLM
```
