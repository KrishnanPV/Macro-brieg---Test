"""Cost-tracking dashboard and API endpoint."""
from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import HTMLResponse, JSONResponse

from backend.services.cost_tracker import get_recent_log, get_summary

router = APIRouter(tags=["costs"])


def _fmt_cost(v: float) -> str:
    if v < 0.01:
        return f"${v:.6f}"
    return f"${v:.4f}"


def _fmt_tokens(v: int) -> str:
    if v >= 1_000_000:
        return f"{v / 1_000_000:.2f}M"
    if v >= 1_000:
        return f"{v / 1_000:.1f}K"
    return str(v)


def _build_html() -> str:
    summary = get_summary()
    recent = get_recent_log(200)

    model_rows = ""
    for m in summary["by_model"]:
        model_rows += (
            f"<tr><td>{m['model']}</td><td>{m['calls']}</td>"
            f"<td>{_fmt_tokens(m['input_tokens'])}</td>"
            f"<td>{_fmt_tokens(m['output_tokens'])}</td>"
            f"<td class='cost'>{_fmt_cost(m['cost'])}</td></tr>\n"
        )

    caller_rows = ""
    for c in summary["by_caller"]:
        caller_rows += (
            f"<tr><td>{c['caller']}</td><td>{c['calls']}</td>"
            f"<td>{_fmt_tokens(c['input_tokens'])}</td>"
            f"<td>{_fmt_tokens(c['output_tokens'])}</td>"
            f"<td class='cost'>{_fmt_cost(c['cost'])}</td></tr>\n"
        )

    log_rows = ""
    for r in recent:
        ts = r["timestamp"][:19].replace("T", " ")
        log_rows += (
            f"<tr><td class='ts'>{ts}</td>"
            f"<td>{r['caller']}</td>"
            f"<td>{r['model']}</td>"
            f"<td>{r['input_tokens']:,}</td>"
            f"<td>{r['output_tokens']:,}</td>"
            f"<td class='cost'>{_fmt_cost(r['total_cost'])}</td></tr>\n"
        )

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta http-equiv="refresh" content="30">
<title>Macrobrief — API Cost Dashboard</title>
<style>
  :root {{
    --bg: #0f1117; --surface: #1a1d27; --border: #2a2d3a;
    --text: #e1e4ed; --muted: #8b8fa3; --accent: #6c8cff;
    --green: #4ade80; --red: #f87171;
  }}
  * {{ margin: 0; padding: 0; box-sizing: border-box; }}
  body {{
    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
    background: var(--bg); color: var(--text); padding: 24px;
    line-height: 1.5;
  }}
  h1 {{ font-size: 1.4rem; margin-bottom: 4px; }}
  .subtitle {{ color: var(--muted); font-size: 0.85rem; margin-bottom: 24px; }}
  .cards {{
    display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
    gap: 12px; margin-bottom: 28px;
  }}
  .card {{
    background: var(--surface); border: 1px solid var(--border);
    border-radius: 8px; padding: 16px;
  }}
  .card .label {{ color: var(--muted); font-size: 0.75rem; text-transform: uppercase; letter-spacing: 0.05em; }}
  .card .value {{ font-size: 1.5rem; font-weight: 700; font-family: 'SF Mono', 'Cascadia Code', monospace; margin-top: 4px; }}
  .card .value.cost {{ color: var(--accent); }}
  h2 {{ font-size: 1.1rem; margin: 20px 0 10px; }}
  table {{
    width: 100%; border-collapse: collapse; font-size: 0.85rem;
    background: var(--surface); border-radius: 8px; overflow: hidden;
  }}
  th {{
    text-align: left; padding: 10px 12px; background: var(--border);
    color: var(--muted); font-weight: 600; font-size: 0.75rem;
    text-transform: uppercase; letter-spacing: 0.04em;
  }}
  td {{ padding: 8px 12px; border-bottom: 1px solid var(--border); }}
  tr:last-child td {{ border-bottom: none; }}
  tr:hover td {{ background: rgba(108, 140, 255, 0.05); }}
  .cost {{ font-family: 'SF Mono', 'Cascadia Code', monospace; color: var(--accent); }}
  .ts {{ color: var(--muted); font-family: 'SF Mono', 'Cascadia Code', monospace; font-size: 0.8rem; }}
  td:nth-child(4), td:nth-child(5), th:nth-child(4), th:nth-child(5) {{
    text-align: right; font-family: 'SF Mono', 'Cascadia Code', monospace;
  }}
  .grid2 {{ display: grid; grid-template-columns: 1fr 1fr; gap: 20px; }}
  @media (max-width: 900px) {{ .grid2 {{ grid-template-columns: 1fr; }} }}
  .empty {{ color: var(--muted); padding: 32px; text-align: center; }}
</style>
</head>
<body>
<h1>API Cost Dashboard</h1>
<p class="subtitle">Auto-refreshes every 30 s &middot; All costs in USD via QB AI Gateway pricing</p>

<div class="cards">
  <div class="card">
    <div class="label">Total Cost</div>
    <div class="value cost">{_fmt_cost(summary['total_cost'])}</div>
  </div>
  <div class="card">
    <div class="label">API Calls</div>
    <div class="value">{summary['total_calls']:,}</div>
  </div>
  <div class="card">
    <div class="label">Input Tokens</div>
    <div class="value">{_fmt_tokens(summary['total_input_tokens'])}</div>
  </div>
  <div class="card">
    <div class="label">Output Tokens</div>
    <div class="value">{_fmt_tokens(summary['total_output_tokens'])}</div>
  </div>
</div>

<div class="grid2">
<div>
<h2>Cost by Model</h2>
{f'<table><tr><th>Model</th><th>Calls</th><th>Input</th><th>Output</th><th>Cost</th></tr>{model_rows}</table>' if model_rows else '<div class="empty">No data yet</div>'}
</div>
<div>
<h2>Cost by Caller</h2>
{f'<table><tr><th>Caller</th><th>Calls</th><th>Input</th><th>Output</th><th>Cost</th></tr>{caller_rows}</table>' if caller_rows else '<div class="empty">No data yet</div>'}
</div>
</div>

<h2>Recent Calls</h2>
{f'<table><tr><th>Timestamp (UTC)</th><th>Caller</th><th>Model</th><th>Input Tok</th><th>Output Tok</th><th>Cost</th></tr>{log_rows}</table>' if log_rows else '<div class="empty">No API calls logged yet. Run a pipeline to see data here.</div>'}

</body>
</html>"""


@router.get("/costs", response_class=HTMLResponse)
async def costs_dashboard():
    return HTMLResponse(_build_html())


@router.get("/api/costs")
async def costs_json():
    summary = get_summary()
    summary["recent"] = get_recent_log(200)
    return JSONResponse(summary)
