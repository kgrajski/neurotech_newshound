"""
HTML report generator — produces a polished single-page intelligence briefing.

Dark neural theme with accent gold for alerts. Designed to be:
- Viewable in any browser without dependencies
- Embeddable on nurosci.com as a static page
- Minimal scrolling: TL;DR + themes visible above the fold
"""
import datetime as dt
import html
import json
import os
import re
from typing import Any, Dict, List, Optional

CATEGORY_COLORS = {
    "implantable_bci": "#e74c3c",
    "ecog_seeg": "#3498db",
    "stimulation": "#9b59b6",
    "materials": "#1abc9c",
    "regulatory": "#e67e22",
    "funding": "#f1c40f",
    "animal_study": "#95a5a6",
    "methods": "#2ecc71",
    "out_of_scope": "#7f8c8d",
    "unknown": "#95a5a6",
    "error": "#c0392b",
}

SIGNIFICANCE_BADGES = {
    "breakthrough": ("BREAKTHROUGH", "#e74c3c"),
    "notable": ("NOTABLE", "#f39c12"),
    "routine": ("ROUTINE", "#7f8c8d"),
}


def _esc(text: str) -> str:
    return html.escape(str(text or ""))


def _score_color(score: int) -> str:
    if score >= 9:
        return "#e74c3c"
    elif score >= 7:
        return "#f39c12"
    elif score >= 5:
        return "#3498db"
    else:
        return "#7f8c8d"


def _md_to_html(md: str) -> str:
    """Convert markdown from LLM briefs to HTML. Handles headers, bold, italic, lists."""
    lines = md.strip().split("\n")
    out = []
    in_list = False
    for raw in lines:
        line = raw.strip()
        if not line:
            if in_list:
                out.append("</ul>")
                in_list = False
            continue

        # Headers: ### → h4, ## → h3, # → h2
        m = re.match(r'^(#{1,4})\s+(.*)', line)
        if m:
            if in_list:
                out.append("</ul>")
                in_list = False
            level = min(len(m.group(1)) + 1, 5)  # # → h2, ## → h3, etc.
            text = _esc(m.group(2))
            text = _inline_md(text)
            out.append(f"<h{level}>{text}</h{level}>")
            continue

        # Unordered list items: - or *
        m = re.match(r'^[-*]\s+(.*)', line)
        if m:
            if not in_list:
                out.append("<ul>")
                in_list = True
            text = _esc(m.group(1))
            text = _inline_md(text)
            out.append(f"<li>{text}</li>")
            continue

        # Regular paragraph
        if in_list:
            out.append("</ul>")
            in_list = False
        text = _esc(line)
        text = _inline_md(text)
        out.append(f"<p>{text}</p>")

    if in_list:
        out.append("</ul>")
    return "\n".join(out)


def _inline_md(text: str) -> str:
    """Convert inline markdown (bold, italic) in already-escaped text."""
    # **bold** → <strong>
    text = re.sub(r'\*\*(.+?)\*\*', r'<strong>\1</strong>', text)
    # *italic* → <em>
    text = re.sub(r'\*(.+?)\*', r'<em>\1</em>', text)
    return text


def generate_html_report(
    scored_items: List[Dict[str, Any]],
    themes: List[Dict[str, Any]],
    executive_brief: str,
    review: Dict[str, Any],
    alerts: List[Dict[str, Any]],
    metadata: Dict[str, Any],
) -> str:
    """Generate a self-contained HTML intelligence briefing."""

    agent_name = metadata.get("agent_name", "NeuroTech NewsHound")
    date = metadata.get("date", dt.date.today().isoformat())
    model = metadata.get("model", "?")
    raw_count = metadata.get("raw_count", 0)
    prefiltered_count = metadata.get("prefiltered_count", 0)
    scored_count = metadata.get("scored_count", len(scored_items))
    alert_count = metadata.get("alert_count", len(alerts))
    duration = metadata.get("duration_seconds", 0)
    cost = metadata.get("cost", 0)
    tokens = metadata.get("tokens", 0)
    source_breakdown = metadata.get("source_breakdown", {})

    # Theme cards
    theme_html = ""
    for t in themes:
        name = _esc(t.get("name", ""))
        narrative = _esc(t.get("narrative", ""))
        sig = t.get("significance", "routine")
        badge_label, badge_color = SIGNIFICANCE_BADGES.get(sig, ("", "#7f8c8d"))
        item_count = len(t.get("items", []))
        theme_html += f"""
        <div class="theme-card">
            <div class="theme-header">
                <span class="theme-name">{name}</span>
                <span class="badge" style="background:{badge_color}">{badge_label}</span>
            </div>
            <p class="theme-narrative">{narrative}</p>
            <span class="theme-items">{item_count} items</span>
        </div>"""

    # Alert cards
    alert_html = ""
    if alerts:
        for a in alerts:
            score = a.get("llm_score", "?")
            title = _esc(a.get("title", "")[:120])
            cat = a.get("category", "?")
            assessment = _esc(a.get("assessment", ""))
            url = a.get("url", "")
            source = _esc(a.get("source", ""))
            cat_color = CATEGORY_COLORS.get(cat, "#95a5a6")
            link = f'<a href="{_esc(url)}" target="_blank" class="alert-link">{source} &rarr;</a>' if url else ""
            alert_html += f"""
            <div class="alert-card">
                <div class="alert-score" style="background:{_score_color(int(score) if str(score).isdigit() else 0)}">{score}</div>
                <div class="alert-body">
                    <div class="alert-title">{title}</div>
                    <span class="cat-badge" style="background:{cat_color}">{_esc(cat)}</span>
                    <p class="alert-assessment">{assessment}</p>
                    {link}
                </div>
            </div>"""
    else:
        alert_html = '<p class="muted">No priority alerts this week.</p>'

    # Scored items table
    items_rows = ""
    for item in scored_items[:40]:
        score = item.get("llm_score", "?")
        title = _esc(item.get("title", "")[:90])
        cat = item.get("category", "?")
        source = _esc(item.get("source", ""))
        assessment = _esc(item.get("assessment", "")[:150])
        url = item.get("url", "")
        adjusted = " *" if item.get("adjusted_by_reviewer") else ""
        vap = ' <span class="vaporware">VAPORWARE</span>' if item.get("vaporware") else ""
        cat_color = CATEGORY_COLORS.get(cat, "#95a5a6")
        sc = int(score) if str(score).isdigit() else 0
        title_link = f'<a href="{_esc(url)}" target="_blank">{title}</a>' if url else title
        items_rows += f"""
            <tr>
                <td><span class="score-pill" style="background:{_score_color(sc)}">{score}{adjusted}</span></td>
                <td><span class="cat-badge" style="background:{cat_color}">{_esc(cat)}</span></td>
                <td>{title_link}{vap}</td>
                <td class="assessment-cell">{assessment}</td>
                <td class="source-cell">{source}</td>
            </tr>"""

    # Near-miss / watchlist items (scored 3-4, potential false negatives)
    near_miss_items = [x for x in scored_items if x.get("llm_score", 0) in (3, 4)]
    near_miss_html = ""
    if near_miss_items:
        near_miss_rows = ""
        for item in near_miss_items:
            score = item.get("llm_score", "?")
            title = _esc(item.get("title", "")[:100])
            cat = item.get("category", "?")
            source = _esc(item.get("source", ""))
            assessment = _esc(item.get("assessment", "")[:200])
            url = item.get("url", "")
            cat_color = CATEGORY_COLORS.get(cat, "#95a5a6")
            rescued = ' <span class="badge" style="background:#27ae60">RESCUED</span>' if item.get("rescued") else ""
            title_link = f'<a href="{_esc(url)}" target="_blank">{title}</a>' if url else title
            near_miss_rows += f"""
                <tr>
                    <td><span class="score-pill" style="background:{_score_color(int(score))}">{score}</span></td>
                    <td><span class="cat-badge" style="background:{cat_color}">{_esc(cat)}</span></td>
                    <td>{title_link}{rescued}</td>
                    <td class="assessment-cell">{assessment}</td>
                    <td class="source-cell">{source}</td>
                </tr>"""
        near_miss_html = f"""
        <div class="items-section" style="border-left: 3px solid #f39c12; padding-left: 16px;">
            <h2 style="color: #f39c12;">Watchlist / Near-Miss ({len(near_miss_items)} items)</h2>
            <p class="muted" style="margin-bottom: 12px;">Items scored 3-4 — borderline scope. Review for potential false negatives: non-invasive BCI companies, competitive intelligence, or BCI-adjacent funding.</p>
            <table class="items-table">
                <thead><tr>
                    <th>Score</th><th>Category</th><th>Title</th><th>Assessment</th><th>Source</th>
                </tr></thead>
                <tbody>{near_miss_rows}</tbody>
            </table>
        </div>"""

    # Review section
    review_html = ""
    if review and review.get("assessment") not in (None, "SKIPPED", "ERROR"):
        r_assessment = _esc(review.get("assessment", ""))
        r_quality = review.get("quality_score", "?")
        r_notes = _esc(review.get("reviewer_notes", ""))
        top = review.get("top_picks", [])
        top_html = ", ".join(_esc(str(t))[:50] for t in top) if top else "None specified"
        review_html = f"""
        <div class="review-box">
            <div class="review-header">
                <span>Reviewer: {r_assessment}</span>
                <span class="review-quality">Quality: {r_quality}/10</span>
            </div>
            <p>{r_notes}</p>
            <p class="review-picks"><strong>Top picks:</strong> {top_html}</p>
        </div>"""

    # Source breakdown chips
    source_chips = ""
    for sid, count in sorted(source_breakdown.items(), key=lambda x: -x[1]):
        source_chips += f'<span class="source-chip">{_esc(sid)} <b>{count}</b></span>'

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{_esc(agent_name)} — {date}</title>
<style>
:root {{
    --bg: #0d1117;
    --surface: #161b22;
    --border: #30363d;
    --text: #e6edf3;
    --muted: #8b949e;
    --accent-gold: #f0c040;
    --accent-blue: #58a6ff;
    --accent-red: #f85149;
}}
* {{ margin: 0; padding: 0; box-sizing: border-box; }}
body {{
    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', sans-serif;
    background: var(--bg);
    color: var(--text);
    line-height: 1.6;
}}
.container {{ max-width: 1200px; margin: 0 auto; padding: 24px; }}

/* Header */
.header {{
    display: flex; justify-content: space-between; align-items: center;
    padding: 20px 0; border-bottom: 1px solid var(--border); margin-bottom: 24px;
}}
.header h1 {{
    font-size: 1.6rem; font-weight: 700;
    background: linear-gradient(135deg, var(--accent-gold), var(--accent-blue));
    -webkit-background-clip: text; -webkit-text-fill-color: transparent;
    background-clip: text;
}}
.header .date {{ color: var(--muted); font-size: 0.95rem; }}

/* Stat bar */
.stat-bar {{
    display: flex; gap: 24px; flex-wrap: wrap;
    padding: 16px 20px; background: var(--surface); border-radius: 8px;
    margin-bottom: 24px; border: 1px solid var(--border);
}}
.stat {{ text-align: center; }}
.stat .val {{ font-size: 1.4rem; font-weight: 700; color: var(--accent-gold); }}
.stat .label {{ font-size: 0.75rem; color: var(--muted); text-transform: uppercase; letter-spacing: 0.05em; }}

/* Executive brief */
.brief-box {{
    background: var(--surface); border-radius: 8px; padding: 20px;
    margin-bottom: 24px; border: 1px solid var(--border);
    border-left: 3px solid var(--accent-blue);
}}
.brief-box h2 {{ font-size: 1.1rem; color: var(--accent-blue); margin-bottom: 12px; }}
.brief-box p, .brief-box li {{ color: var(--text); font-size: 0.92rem; margin-bottom: 8px; }}

/* Themes */
.themes {{ display: grid; grid-template-columns: repeat(auto-fill, minmax(280px, 1fr)); gap: 16px; margin-bottom: 24px; }}
.theme-card {{
    background: var(--surface); border-radius: 8px; padding: 16px;
    border: 1px solid var(--border);
}}
.theme-header {{ display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px; }}
.theme-name {{ font-weight: 600; font-size: 0.95rem; }}
.badge {{
    font-size: 0.65rem; font-weight: 700; padding: 2px 8px; border-radius: 10px;
    color: #fff; text-transform: uppercase; letter-spacing: 0.05em;
}}
.theme-narrative {{ color: var(--muted); font-size: 0.85rem; margin-bottom: 8px; }}
.theme-items {{ font-size: 0.75rem; color: var(--muted); }}

/* Alerts */
.alerts-section {{ margin-bottom: 24px; }}
.alerts-section h2 {{ font-size: 1.1rem; color: var(--accent-red); margin-bottom: 12px; }}
.alert-card {{
    display: flex; gap: 16px; background: var(--surface); border-radius: 8px;
    padding: 16px; margin-bottom: 12px; border: 1px solid var(--border);
    border-left: 3px solid var(--accent-red);
}}
.alert-score {{
    min-width: 44px; height: 44px; border-radius: 50%;
    display: flex; align-items: center; justify-content: center;
    font-weight: 700; font-size: 1.1rem; color: #fff; flex-shrink: 0;
}}
.alert-title {{ font-weight: 600; font-size: 0.95rem; margin-bottom: 4px; }}
.alert-assessment {{ color: var(--muted); font-size: 0.85rem; margin: 6px 0; }}
.alert-link {{ color: var(--accent-blue); text-decoration: none; font-size: 0.85rem; }}
.alert-link:hover {{ text-decoration: underline; }}

/* Category badges */
.cat-badge {{
    font-size: 0.65rem; font-weight: 600; padding: 2px 6px; border-radius: 6px;
    color: #fff; text-transform: uppercase; letter-spacing: 0.03em; white-space: nowrap;
}}

/* Items table */
.items-section {{ margin-bottom: 24px; }}
.items-section h2 {{ font-size: 1.1rem; color: var(--text); margin-bottom: 12px; }}
.items-table {{ width: 100%; border-collapse: collapse; font-size: 0.85rem; }}
.items-table th {{
    text-align: left; padding: 8px 10px; border-bottom: 2px solid var(--border);
    color: var(--muted); font-size: 0.75rem; text-transform: uppercase; letter-spacing: 0.05em;
}}
.items-table td {{ padding: 8px 10px; border-bottom: 1px solid var(--border); vertical-align: top; }}
.items-table tr:hover {{ background: rgba(88, 166, 255, 0.05); }}
.items-table a {{ color: var(--accent-blue); text-decoration: none; }}
.items-table a:hover {{ text-decoration: underline; }}
.score-pill {{
    display: inline-block; min-width: 28px; padding: 2px 8px; border-radius: 12px;
    text-align: center; color: #fff; font-weight: 700; font-size: 0.8rem;
}}
.assessment-cell {{ color: var(--muted); max-width: 300px; }}
.source-cell {{ color: var(--muted); white-space: nowrap; }}
.vaporware {{
    background: var(--accent-red); color: #fff; font-size: 0.6rem;
    padding: 1px 5px; border-radius: 4px; font-weight: 700; vertical-align: middle;
}}
.muted {{ color: var(--muted); font-style: italic; }}

/* Review */
.review-box {{
    background: var(--surface); border-radius: 8px; padding: 16px;
    margin-bottom: 24px; border: 1px solid var(--border);
    border-left: 3px solid var(--accent-gold);
}}
.review-header {{
    display: flex; justify-content: space-between; margin-bottom: 8px;
    font-weight: 600; color: var(--accent-gold);
}}
.review-quality {{ font-size: 0.85rem; }}
.review-box p {{ color: var(--muted); font-size: 0.88rem; margin-bottom: 6px; }}
.review-picks {{ font-size: 0.85rem; }}

/* Sources */
.sources-bar {{ margin-bottom: 24px; }}
.sources-bar h3 {{ font-size: 0.85rem; color: var(--muted); margin-bottom: 8px; }}
.source-chip {{
    display: inline-block; background: var(--surface); border: 1px solid var(--border);
    border-radius: 12px; padding: 3px 10px; margin: 3px 4px 3px 0; font-size: 0.75rem;
    color: var(--muted);
}}
.source-chip b {{ color: var(--text); }}

/* Footer */
.footer {{
    text-align: center; padding: 16px 0; margin-top: 24px;
    border-top: 1px solid var(--border); color: var(--muted); font-size: 0.75rem;
}}
.footer a {{ color: var(--accent-blue); text-decoration: none; }}
</style>
</head>
<body>
<div class="container">

<div class="header">
    <h1>{_esc(agent_name)}</h1>
    <div class="date">Intelligence Briefing — {date}</div>
</div>

<div class="stat-bar">
    <div class="stat"><div class="val">{raw_count}</div><div class="label">Fetched</div></div>
    <div class="stat"><div class="val">{prefiltered_count}</div><div class="label">In-Scope</div></div>
    <div class="stat"><div class="val">{scored_count}</div><div class="label">Scored</div></div>
    <div class="stat"><div class="val" style="color:var(--accent-red)">{alert_count}</div><div class="label">Alerts</div></div>
    <div class="stat"><div class="val">{len(themes)}</div><div class="label">Themes</div></div>
    <div class="stat"><div class="val">{tokens:,}</div><div class="label">Tokens</div></div>
    <div class="stat"><div class="val">${cost:.4f}</div><div class="label">Cost</div></div>
    <div class="stat"><div class="val">{duration:.0f}s</div><div class="label">Duration</div></div>
</div>

<div class="brief-box">
    <h2>Executive Brief</h2>
    {_md_to_html(executive_brief)}
</div>

<h2 style="font-size:1.1rem; margin-bottom:12px;">Themes</h2>
<div class="themes">{theme_html}</div>

<div class="alerts-section">
    <h2>Priority Alerts</h2>
    {alert_html}
</div>

{review_html}

<div class="sources-bar">
    <h3>Sources ({len(source_breakdown)} active)</h3>
    {source_chips}
</div>

<div class="items-section">
    <h2>All Scored Items ({scored_count})</h2>
    <table class="items-table">
        <thead><tr>
            <th>Score</th><th>Category</th><th>Title</th><th>Assessment</th><th>Source</th>
        </tr></thead>
        <tbody>{items_rows}</tbody>
    </table>
</div>

{near_miss_html}

<div class="footer">
    Generated by <a href="https://github.com/kgrajski/neurotech_newshound">{_esc(agent_name)}</a>
    &middot; Model: {_esc(model)} &middot; {date}
</div>

</div>
</body>
</html>"""
