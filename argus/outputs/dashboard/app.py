"""
Dashboard — FastAPI app with minimal UI.
Run: uvicorn argus.outputs.dashboard.app:app --port 7070
"""
from __future__ import annotations

from fastapi import FastAPI
from fastapi.responses import HTMLResponse

app = FastAPI(title="Argus Dashboard", version="0.1.0")


def _get_storage():
    from argus.engine.pipeline import EnginePipeline
    return EnginePipeline.get_instance().storage


@app.get("/", response_class=HTMLResponse)
def index():
    storage = _get_storage()
    errors = storage.get_recent_errors(limit=50)
    summary = storage.get_token_summary()
    today = storage.get_token_summary_today()
    return HTMLResponse(_render(errors, summary, today))


@app.get("/api/errors")
def api_errors(limit: int = 50):
    return _get_storage().get_recent_errors(limit=limit)


@app.get("/api/tokens")
def api_tokens():
    return {
        "all_time": _get_storage().get_token_summary(),
        "today":    _get_storage().get_token_summary_today(),
    }


# ── Server-side event endpoint (for Emitter HTTP transport) ────────────────

@app.post("/events")
async def receive_event(payload: dict):
    from argus.engine.pipeline import EnginePipeline
    if payload.get("severity") == "info":
        EnginePipeline.get_instance().handle_success(payload)
    else:
        EnginePipeline.get_instance().handle_error(payload)
    return {"ok": True}


# ── HTML renderer ──────────────────────────────────────────────────────────

def _render(errors: list[dict], summary: dict, today: dict) -> str:
    error_rows = ""
    for e in errors:
        sev = e.get("severity", "error")
        color = {"warning": "#b45309", "error": "#b91c1c", "critical": "#7c3aed", "info": "#15803d"}.get(sev, "#374151")
        handled = "🤖" if e.get("handled_by") == "llm" else "📋"
        diagnosis = (e.get("diagnosis") or "")[:120]
        error_rows += f"""
        <tr>
          <td style="color:{color};font-weight:600">{e.get('severity','')}</td>
          <td><code>{e.get('layer','')}</code></td>
          <td><code>{e.get('error_type','')}</code></td>
          <td><code>{e.get('error_class','')}</code></td>
          <td style="font-family:monospace;font-size:12px">{e.get('function','')}</td>
          <td style="font-size:12px;color:#6b7280">{diagnosis}{"…" if len(e.get("diagnosis") or "") > 120 else ""}</td>
          <td style="text-align:center">{handled}</td>
          <td style="font-size:11px;color:#9ca3af">{(e.get('timestamp') or '')[:19]}</td>
        </tr>"""

    t = summary
    td = today
    llm_pct = round(t.get("llm_called", 0) / max(t.get("total_errors", 1), 1) * 100, 1)

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Argus — Pipeline Monitor</title>
<style>
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
         background: #f9fafb; color: #111827; }}
  header {{ background: #1e3a5f; color: white; padding: 16px 32px;
            display: flex; align-items: center; gap: 12px; }}
  header h1 {{ font-size: 20px; font-weight: 600; }}
  header span {{ font-size: 13px; opacity: .7; }}
  .main {{ padding: 24px 32px; }}
  .cards {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
            gap: 16px; margin-bottom: 28px; }}
  .card {{ background: white; border: 1px solid #e5e7eb; border-radius: 10px;
           padding: 18px 22px; }}
  .card-label {{ font-size: 12px; color: #6b7280; margin-bottom: 6px; }}
  .card-value {{ font-size: 26px; font-weight: 700; color: #1e3a5f; }}
  .card-sub {{ font-size: 12px; color: #9ca3af; margin-top: 4px; }}
  .savings-banner {{ background: #ecfdf5; border: 1px solid #6ee7b7;
                     border-radius: 10px; padding: 14px 22px; margin-bottom: 24px;
                     display: flex; gap: 32px; align-items: center; flex-wrap: wrap; }}
  .savings-banner .item {{ font-size: 13px; color: #065f46; }}
  .savings-banner .item strong {{ font-size: 18px; font-weight: 700; }}
  h2 {{ font-size: 15px; font-weight: 600; color: #374151; margin-bottom: 12px; }}
  table {{ width: 100%; border-collapse: collapse; background: white;
           border: 1px solid #e5e7eb; border-radius: 10px; overflow: hidden;
           font-size: 13px; }}
  th {{ background: #f3f4f6; text-align: left; padding: 10px 14px;
        font-size: 11px; font-weight: 600; color: #6b7280; text-transform: uppercase;
        letter-spacing: .05em; }}
  td {{ padding: 10px 14px; border-top: 1px solid #f3f4f6; vertical-align: top; }}
  tr:hover td {{ background: #f9fafb; }}
  code {{ background: #f3f4f6; padding: 1px 5px; border-radius: 4px; font-size: 12px; }}
</style>
</head>
<body>
<header>
  <div>
    <h1>Argus</h1>
    <span>Pipeline monitoring agent</span>
  </div>
</header>
<div class="main">

  <!-- Token savings banner -->
  <div class="savings-banner">
    <div class="item">Today &nbsp;
      <strong>{td.get('tokens_saved', 0):,}</strong> tokens saved &nbsp;
      <strong>${td.get('cost_saved_usd', 0):.2f}</strong> saved
    </div>
    <div class="item">All-time &nbsp;
      <strong>{t.get('tokens_saved', 0):,}</strong> tokens saved &nbsp;
      <strong>${t.get('cost_saved_usd', 0):.2f}</strong> saved
    </div>
    <div class="item" style="color:#374151">
      LLM call rate: <strong style="color:#1e3a5f">{llm_pct}%</strong> of errors
    </div>
  </div>

  <!-- Summary cards -->
  <div class="cards">
    <div class="card">
      <div class="card-label">Total errors</div>
      <div class="card-value">{t.get('total_errors', 0)}</div>
      <div class="card-sub">all time</div>
    </div>
    <div class="card">
      <div class="card-label">Rule-handled</div>
      <div class="card-value">{t.get('rule_handled', 0)}</div>
      <div class="card-sub">no LLM needed</div>
    </div>
    <div class="card">
      <div class="card-label">LLM analyzed</div>
      <div class="card-value">{t.get('llm_called', 0)}</div>
      <div class="card-sub">avg {t.get('avg_tokens_per_call', 0):.0f} tokens/call</div>
    </div>
    <div class="card">
      <div class="card-label">Total LLM cost</div>
      <div class="card-value">${t.get('cost_usd', 0):.4f}</div>
      <div class="card-sub">USD</div>
    </div>
  </div>

  <!-- Error table -->
  <h2>Recent errors</h2>
  <table>
    <thead>
      <tr>
        <th>Severity</th><th>Layer</th><th>Type</th><th>Exception</th>
        <th>Function</th><th>Diagnosis</th><th>By</th><th>Time</th>
      </tr>
    </thead>
    <tbody>
      {error_rows if error_rows else '<tr><td colspan="8" style="text-align:center;color:#9ca3af;padding:32px">No errors recorded yet</td></tr>'}
    </tbody>
  </table>
</div>
</body>
</html>"""
