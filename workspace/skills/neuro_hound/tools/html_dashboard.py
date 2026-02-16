"""
Dashboard HTML generator — operational view of the NewsHound agent.

Shows: source registry (with stats), config summary, run history,
cost tracking. Generated alongside the report after each run.
"""
import datetime as dt
import html
import json
import os
from typing import Any, Dict, List, Optional


def _esc(text: str) -> str:
    return html.escape(str(text or ""))


def _source_health(stats: Dict) -> str:
    """Color-coded health indicator."""
    if not stats.get("last_run_date"):
        return '<span style="color:#7f8c8d">NEW</span>'
    in_scope = stats.get("in_scope_count", 0)
    fetched = stats.get("total_fetched", 0)
    if fetched == 0:
        return '<span style="color:#e74c3c">NO DATA</span>'
    ratio = in_scope / fetched if fetched > 0 else 0
    if ratio > 0.3:
        return '<span style="color:#2ecc71">HIGH YIELD</span>'
    elif ratio > 0.05:
        return '<span style="color:#f39c12">MODERATE</span>'
    elif in_scope > 0:
        return '<span style="color:#e67e22">LOW</span>'
    else:
        return '<span style="color:#e74c3c">NO MATCHES</span>'


def generate_dashboard(
    registry: Dict[str, Any],
    config: Dict[str, Any],
    run_metadata: Optional[Dict[str, Any]] = None,
    history_summary: Optional[Dict[str, Any]] = None,
) -> str:
    """Generate the operational dashboard HTML."""

    agent_name = config.get("agent", {}).get("name", "NeuroTech NewsHound")
    agent_tagline = config.get("agent", {}).get("tagline", "")
    agent_domain = config.get("agent", {}).get("domain", "")
    defaults = config.get("defaults", {})

    sources = registry.get("sources", [])
    enabled = [s for s in sources if s.get("enabled", True)]
    disabled = [s for s in sources if not s.get("enabled", True)]

    # Group sources by category
    by_cat: Dict[str, List] = {}
    for s in enabled:
        cat = s.get("category", "other")
        by_cat.setdefault(cat, []).append(s)

    # Source table rows
    source_rows = ""
    for cat in ["database", "journal", "preprint", "press", "regulatory", "search", "discovered", "other"]:
        cat_sources = by_cat.get(cat, [])
        if not cat_sources:
            continue
        for s in cat_sources:
            stats = s.get("stats", {})
            health = _source_health(stats)
            fetched = stats.get("total_fetched", 0)
            in_scope = stats.get("in_scope_count", 0)
            high = stats.get("high_score_count", 0)
            runs = stats.get("runs", 0)
            last_hit = stats.get("last_hit_date", "—")
            curated = "Curated" if s.get("curated", True) else "Discovered"
            url = _esc(s.get("url", ""))
            url_display = f'<a href="{url}" target="_blank" class="src-link">{url[:50]}{"..." if len(url) > 50 else ""}</a>' if url else "API"

            source_rows += f"""
            <tr>
                <td><strong>{_esc(s.get('name', ''))}</strong></td>
                <td><span class="cat-chip cat-{_esc(cat)}">{_esc(cat)}</span></td>
                <td>{curated}</td>
                <td>{health}</td>
                <td class="num">{runs}</td>
                <td class="num">{fetched:,}</td>
                <td class="num">{in_scope:,}</td>
                <td class="num">{high}</td>
                <td>{last_hit}</td>
                <td class="url-cell">{url_display}</td>
            </tr>"""

    # Config summary
    model = defaults.get("model", "gpt-4o-mini")
    reviewer = defaults.get("reviewer_model", "") or model
    days = defaults.get("days", 7)
    max_items = defaults.get("max_items_per_source", 40)
    max_src = defaults.get("max_sources", 40)
    tavily_queries = config.get("tavily_queries", [])
    mlflow_cfg = config.get("mlflow", {})

    # Run metadata (from latest run)
    run_html = ""
    if run_metadata:
        run_html = f"""
        <div class="run-card">
            <h3>Latest Run — {_esc(str(run_metadata.get('date', '?')))}</h3>
            <div class="run-stats">
                <div class="rs"><span class="rv">{run_metadata.get('raw_count', 0)}</span><span class="rl">Fetched</span></div>
                <div class="rs"><span class="rv">{run_metadata.get('prefiltered_count', 0)}</span><span class="rl">In-Scope</span></div>
                <div class="rs"><span class="rv">{run_metadata.get('scored_count', 0)}</span><span class="rl">Scored</span></div>
                <div class="rs"><span class="rv" style="color:#e74c3c">{run_metadata.get('alert_count', 0)}</span><span class="rl">Alerts</span></div>
                <div class="rs"><span class="rv">{run_metadata.get('tokens', 0):,}</span><span class="rl">Tokens</span></div>
                <div class="rs"><span class="rv">${run_metadata.get('cost', 0):.4f}</span><span class="rl">Cost</span></div>
                <div class="rs"><span class="rv">{run_metadata.get('duration_seconds', 0):.0f}s</span><span class="rl">Duration</span></div>
            </div>
        </div>"""

    # Dedup summary
    dedup_html = ""
    if history_summary:
        dedup_html = f"""
        <div class="info-card">
            <h3>Deduplication History</h3>
            <p>{history_summary.get('total', 0):,} items tracked &middot;
               {history_summary.get('high_value', 0)} high-value &middot;
               {history_summary.get('low_value', 0)} low-value (will be skipped)</p>
        </div>"""

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{_esc(agent_name)} — Dashboard</title>
<style>
:root {{
    --bg: #0d1117; --surface: #161b22; --border: #30363d;
    --text: #e6edf3; --muted: #8b949e;
    --accent-gold: #f0c040; --accent-blue: #58a6ff; --accent-red: #f85149;
}}
* {{ margin: 0; padding: 0; box-sizing: border-box; }}
body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; background: var(--bg); color: var(--text); line-height: 1.6; }}
.container {{ max-width: 1300px; margin: 0 auto; padding: 24px; }}

.header {{ display: flex; justify-content: space-between; align-items: center; padding: 20px 0; border-bottom: 1px solid var(--border); margin-bottom: 24px; }}
.header h1 {{ font-size: 1.6rem; font-weight: 700; background: linear-gradient(135deg, var(--accent-gold), var(--accent-blue)); -webkit-background-clip: text; -webkit-text-fill-color: transparent; background-clip: text; }}
.header .subtitle {{ color: var(--muted); font-size: 0.9rem; }}

.nav {{ display: flex; gap: 16px; margin-bottom: 24px; }}
.nav a {{ color: var(--accent-blue); text-decoration: none; font-size: 0.9rem; padding: 6px 14px; border: 1px solid var(--border); border-radius: 6px; }}
.nav a:hover {{ background: var(--surface); }}
.nav a.active {{ background: var(--surface); border-color: var(--accent-blue); }}

h2 {{ font-size: 1.1rem; margin: 24px 0 12px; color: var(--text); }}
h3 {{ font-size: 1rem; margin-bottom: 8px; color: var(--accent-gold); }}

.config-grid {{ display: grid; grid-template-columns: repeat(auto-fill, minmax(200px, 1fr)); gap: 12px; margin-bottom: 24px; }}
.config-item {{ background: var(--surface); border: 1px solid var(--border); border-radius: 8px; padding: 12px; }}
.config-item .label {{ font-size: 0.7rem; color: var(--muted); text-transform: uppercase; letter-spacing: 0.05em; }}
.config-item .value {{ font-size: 1rem; font-weight: 600; color: var(--accent-gold); margin-top: 2px; }}

.info-card, .run-card {{ background: var(--surface); border: 1px solid var(--border); border-radius: 8px; padding: 16px; margin-bottom: 16px; }}
.run-stats {{ display: flex; gap: 20px; flex-wrap: wrap; margin-top: 10px; }}
.rs {{ text-align: center; }}
.rv {{ display: block; font-size: 1.3rem; font-weight: 700; color: var(--accent-gold); }}
.rl {{ font-size: 0.7rem; color: var(--muted); text-transform: uppercase; }}

table {{ width: 100%; border-collapse: collapse; font-size: 0.82rem; margin-bottom: 24px; }}
th {{ text-align: left; padding: 8px; border-bottom: 2px solid var(--border); color: var(--muted); font-size: 0.7rem; text-transform: uppercase; letter-spacing: 0.05em; }}
td {{ padding: 8px; border-bottom: 1px solid var(--border); vertical-align: top; }}
tr:hover {{ background: rgba(88, 166, 255, 0.04); }}
.num {{ text-align: right; font-variant-numeric: tabular-nums; }}
.url-cell {{ color: var(--muted); font-size: 0.75rem; max-width: 200px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }}
.src-link {{ color: var(--muted); text-decoration: none; }}
.src-link:hover {{ color: var(--accent-blue); }}

.cat-chip {{ font-size: 0.65rem; padding: 2px 7px; border-radius: 8px; font-weight: 600; text-transform: uppercase; color: #fff; }}
.cat-database {{ background: #3498db; }} .cat-journal {{ background: #9b59b6; }}
.cat-preprint {{ background: #2ecc71; }} .cat-press {{ background: #e67e22; }}
.cat-regulatory {{ background: #e74c3c; }} .cat-search {{ background: #1abc9c; }}
.cat-discovered {{ background: #f39c12; }} .cat-other {{ background: #7f8c8d; }}

.queries-list {{ list-style: none; padding: 0; }}
.queries-list li {{ background: var(--surface); border: 1px solid var(--border); border-radius: 6px; padding: 8px 12px; margin-bottom: 6px; font-family: monospace; font-size: 0.82rem; color: var(--muted); }}

.footer {{ text-align: center; padding: 16px 0; margin-top: 24px; border-top: 1px solid var(--border); color: var(--muted); font-size: 0.75rem; }}
.footer a {{ color: var(--accent-blue); text-decoration: none; }}
</style>
</head>
<body>
<div class="container">

<div class="header">
    <div>
        <h1>{_esc(agent_name)}</h1>
        <div class="subtitle">{_esc(agent_tagline)}</div>
    </div>
    <div class="subtitle">Dashboard</div>
</div>

<div class="nav">
    <a href="{dt.date.today().isoformat()}.html">Latest Report</a>
    <a href="dashboard.html" class="active">Dashboard</a>
</div>

{run_html}

<h2>Configuration</h2>
<div class="config-grid">
    <div class="config-item"><div class="label">Model</div><div class="value">{_esc(model)}</div></div>
    <div class="config-item"><div class="label">Reviewer</div><div class="value">{_esc(reviewer)}</div></div>
    <div class="config-item"><div class="label">Lookback</div><div class="value">{days} days</div></div>
    <div class="config-item"><div class="label">Max Items/Source</div><div class="value">{max_items}</div></div>
    <div class="config-item"><div class="label">Source Cap</div><div class="value">{max_src}</div></div>
    <div class="config-item"><div class="label">Active Sources</div><div class="value">{len(enabled)}</div></div>
    <div class="config-item"><div class="label">MLflow</div><div class="value">{'Enabled' if mlflow_cfg.get('enabled') else 'Disabled'}</div></div>
    <div class="config-item"><div class="label">Domain Focus</div><div class="value" style="font-size:0.8rem">{_esc(agent_domain)}</div></div>
</div>

{dedup_html}

<h2>Source Registry ({len(enabled)} active)</h2>
<table>
    <thead><tr>
        <th>Source</th><th>Category</th><th>Origin</th><th>Health</th>
        <th>Runs</th><th>Fetched</th><th>In-Scope</th><th>High</th><th>Last Hit</th><th>URL</th>
    </tr></thead>
    <tbody>{source_rows}</tbody>
</table>

<h2>Tavily Search Queries ({len(tavily_queries)})</h2>
<ul class="queries-list">
    {"".join(f"<li>{_esc(q)}</li>" for q in tavily_queries)}
</ul>

<div class="footer">
    {_esc(agent_name)} &middot;
    <a href="https://github.com/kgrajski/neurotech_newshound">GitHub</a> &middot;
    Config: <code>config.yaml</code>
</div>

</div>
</body>
</html>"""
