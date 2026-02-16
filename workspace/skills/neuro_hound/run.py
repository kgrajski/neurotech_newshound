#!/usr/bin/env python3
"""
NeuroTech NewsHound — Agentic research intelligence skill.

Usage:
    python3 skills/neuro_hound/run.py --days 7
    python3 skills/neuro_hound/run.py --days 14 --max 60
    python3 skills/neuro_hound/run.py --days 7 --model gpt-4o-mini
    python3 skills/neuro_hound/run.py --days 7 --phase1-only    # Skip LLM, regex only

Phase 1 (regex): Fetch + pre-filter + regex score → markdown report
Phase 2 (LLM):   + LLM scoring + thematic synthesis + executive brief + reflection
"""
import argparse
import datetime as dt
import json
import os
import sys
import textwrap
import time

from dotenv import load_dotenv
load_dotenv()


def run_phase1(args, out_dir: str):
    """Phase 1 only: fetch + regex score + basic report (no LLM)."""
    from tools.pubmed import fetch_pubmed_items
    from tools.rss import fetch_rss_sources
    from tools.scoring import is_in_scope, regex_score
    from tools.sources import load_sources, get_enabled_sources

    today = dt.date.today().isoformat()
    all_items = []

    print("  Fetching PubMed...")
    try:
        items = fetch_pubmed_items(args.days, args.max)
        all_items.extend(items)
        print(f"  [ok] PubMed: {len(items)} items")
    except Exception as e:
        print(f"  [warn] PubMed: {e}")

    print("  Fetching RSS sources...")
    registry = load_sources()
    rss_sources = get_enabled_sources(registry, source_type="rss")
    results = fetch_rss_sources(rss_sources, args.max)
    for sid, items in results.items():
        all_items.extend(items)

    # Score with regex
    scored = []
    for it in all_items:
        title, summary, source = it.get("title", ""), it.get("summary", ""), it.get("source", "")
        if is_in_scope(title, summary, source):
            it["score"] = regex_score(title, summary, source)
            scored.append(it)

    scored.sort(key=lambda x: x.get("score", 0), reverse=True)
    alerts = [x for x in scored if x["score"] >= 9]

    # Write report
    lines = [f"# NeuroTech NewsHound Report — {today} (Phase 1 / Regex Only)", "",
             f"- Lookback: {args.days} day(s)", f"- Total fetched: {len(all_items)}",
             f"- In-scope: {len(scored)}", f"- Alerts (9-10): {len(alerts)}", ""]
    lines.append("## Alerts (9–10)\n")
    if alerts:
        for x in alerts[:20]:
            lines.append(f"- [{x['score']}] {x.get('title', '')[:100]} ({x.get('source', '')})")
    else:
        lines.append("_None detected._")
    lines.append("\n## Scored Items\n")
    for x in scored[:50]:
        lines.append(f"### [{x.get('score', '?')}] {x.get('title', '')[:100]}")
        lines.append(f"- Source: {x.get('source', '')}")
        if x.get("url"): lines.append(f"- Link: {x['url']}")
        if x.get("summary"):
            lines.append(f"- Summary: {textwrap.shorten(x['summary'], 400, placeholder='...')}")
        lines.append("")

    out_md = os.path.join(out_dir, f"{today}.md")
    out_alerts = os.path.join(out_dir, f"{today}.alerts.json")
    with open(out_md, "w") as f:
        f.write("\n".join(lines))
    with open(out_alerts, "w") as f:
        json.dump(alerts, f, indent=2, default=str)

    print(f"\n[done] Report: {out_md}")
    print(f"[done] Total: {len(scored)} in-scope | Alerts: {len(alerts)}")


def run_phase2(args, out_dir: str):
    """Phase 2: Full LangGraph workflow with LLM scoring + synthesis + reflection."""
    from graph import build_hound_graph
    from state import HoundState
    from tools.llm import get_tracker, reset_tracker

    reset_tracker()
    today = dt.date.today().isoformat()

    from tools.config import get_default_model, get_default_reviewer, get_agent_name
    model = args.model or os.getenv("HOUND_LLM_MODEL", "") or get_default_model()
    reviewer = args.reviewer or os.getenv("HOUND_REVIEWER_MODEL", "") or get_default_reviewer() or model
    agent_name = get_agent_name()

    print(f"\n{'='*60}")
    print(f"{agent_name.upper()} — Agentic Intelligence Briefing")
    print(f"{'='*60}")
    print(f"  Model: {model}")
    print(f"  Reviewer: {reviewer}")
    print(f"  Lookback: {args.days} days")
    print()

    # Initialize state
    initial_state: HoundState = {
        "days": args.days,
        "max_items": args.max,
        "model": model,
        "reviewer_model": reviewer,
        "raw_items": [],
        "prefiltered_items": [],
        "regex_scores": {},
        "scored_items": [],
        "alerts": [],
        "themes": None,
        "executive_brief": None,
        "review": None,
        "_registry": None,
        "source_discoveries": [],
        "_dedup_history": None,
        "errors": [],
        "usage": {},
    }

    # Build and run graph
    graph = build_hound_graph()
    start_time = time.time()
    final_state = graph.invoke(initial_state)
    duration = time.time() - start_time

    tracker = get_tracker()

    # --- Write full report ---
    lines = []
    lines.append(f"# {agent_name} Report — {today}")
    lines.append("")
    lines.append(f"- Model: {model} | Reviewer: {reviewer}")
    lines.append(f"- Lookback: {args.days} days | Fetched: {len(final_state['raw_items'])} | In-scope: {len(final_state['prefiltered_items'])}")
    lines.append(f"- LLM calls: {tracker.calls} | Tokens: {tracker.input_tokens + tracker.output_tokens:,} | Cost: ${tracker.estimate_cost(model):.4f}")
    lines.append(f"- Duration: {duration:.1f}s")
    lines.append("")

    # Executive brief
    brief = final_state.get("executive_brief", "")
    if brief and not brief.startswith("_"):
        lines.append("## Executive Brief")
        lines.append("")
        lines.append(brief)
        lines.append("")

    # Reviewer notes
    review_data = final_state.get("review", {})
    if review_data and review_data.get("assessment") not in ("SKIPPED", "ERROR", None):
        lines.append("## Reviewer Notes")
        lines.append("")
        lines.append(f"**Assessment:** {review_data.get('assessment', 'N/A')} (quality: {review_data.get('quality_score', '?')}/10)")
        lines.append("")
        top = review_data.get("top_picks", [])
        if top:
            lines.append(f"**Top picks:** {', '.join(str(t) for t in top)}")
            lines.append("")
        vaporware = review_data.get("vaporware_flags", [])
        if vaporware:
            lines.append(f"**Vaporware flags:** {', '.join(str(v) for v in vaporware)}")
            lines.append("")
        notes = review_data.get("reviewer_notes", "")
        if notes:
            lines.append(notes)
            lines.append("")

    # Alerts
    alerts = final_state.get("alerts", [])
    lines.append("## Alerts (9-10)")
    lines.append("")
    if alerts:
        for a in alerts:
            lines.append(f"- [{a.get('llm_score', '?')}] **{a.get('title', '')[:100]}** ({a.get('category', '?')})")
            lines.append(f"  {a.get('assessment', '')}")
            if a.get("url"):
                lines.append(f"  [{a.get('source', 'link')}]({a['url']})")
            lines.append("")
    else:
        lines.append("_None this week._")
        lines.append("")

    # Scored items
    scored = final_state.get("scored_items", [])
    lines.append("## All Scored Items")
    lines.append("")
    for x in scored[:50]:
        adjusted = " (reviewer-adjusted)" if x.get("adjusted_by_reviewer") else ""
        vap = " [VAPORWARE]" if x.get("vaporware") else ""
        lines.append(f"### [{x.get('llm_score', '?')}] {x.get('title', '')[:100]}{adjusted}{vap}")
        lines.append(f"- Category: {x.get('category', '?')} | Source: {x.get('source', '')}")
        lines.append(f"- Assessment: {x.get('assessment', '')}")
        if x.get("url"):
            lines.append(f"- Link: {x['url']}")
        lines.append("")

    # Errors
    errors = final_state.get("errors", [])
    if errors:
        lines.append("## Errors")
        lines.append("")
        for e in errors:
            lines.append(f"- {e}")
        lines.append("")

    # Source breakdown
    source_breakdown = {}
    for item in final_state["raw_items"]:
        sid = item.get("source_id", item.get("source", "unknown"))
        source_breakdown[sid] = source_breakdown.get(sid, 0) + 1

    # Write outputs
    report_text = "\n".join(lines)
    out_md = os.path.join(out_dir, f"{today}.md")
    out_html = os.path.join(out_dir, f"{today}.html")
    out_alerts = os.path.join(out_dir, f"{today}.alerts.json")
    out_json = os.path.join(out_dir, f"{today}.full.json")

    with open(out_md, "w") as f:
        f.write(report_text)
    with open(out_alerts, "w") as f:
        json.dump(alerts, f, indent=2, default=str)

    # Generate HTML report
    try:
        from tools.html_report import generate_html_report
        html_content = generate_html_report(
            scored_items=scored,
            themes=final_state.get("themes", []),
            executive_brief=brief,
            review=review_data,
            alerts=alerts,
            metadata={
                "agent_name": agent_name,
                "date": today,
                "model": model,
                "raw_count": len(final_state["raw_items"]),
                "prefiltered_count": len(final_state["prefiltered_items"]),
                "scored_count": len(scored),
                "alert_count": len(alerts),
                "duration_seconds": duration,
                "cost": tracker.estimate_cost(model),
                "tokens": tracker.input_tokens + tracker.output_tokens,
                "source_breakdown": source_breakdown,
            },
        )
        with open(out_html, "w") as f:
            f.write(html_content)
    except Exception as e:
        final_state.get("errors", []).append(f"HTML report: {e}")
        print(f"  [warn] HTML report generation failed: {e}")

    # Generate dashboard HTML
    try:
        from tools.html_dashboard import generate_dashboard
        from tools.config import load_config
        from tools.dedup import load_history
        config = load_config()
        registry = final_state.get("_registry") or {}
        dedup_history = final_state.get("_dedup_history") or load_history()
        high_val = sum(1 for v in dedup_history.values() if v.get("score", 0) >= 7)
        dashboard_html = generate_dashboard(
            registry=registry,
            config=config,
            run_metadata={
                "date": today,
                "raw_count": len(final_state["raw_items"]),
                "prefiltered_count": len(final_state["prefiltered_items"]),
                "scored_count": len(scored),
                "alert_count": len(alerts),
                "tokens": tracker.input_tokens + tracker.output_tokens,
                "cost": tracker.estimate_cost(model),
                "duration_seconds": duration,
            },
            history_summary={
                "total": len(dedup_history),
                "high_value": high_val,
                "low_value": len(dedup_history) - high_val,
            },
        )
        out_dashboard = os.path.join(out_dir, "dashboard.html")
        with open(out_dashboard, "w") as f:
            f.write(dashboard_html)
    except Exception as e:
        final_state.get("errors", []).append(f"Dashboard: {e}")
        print(f"  [warn] Dashboard generation failed: {e}")

    # Full results JSON (for MLflow artifacts in Phase 3)
    full_results = {
        "date": today,
        "model": model,
        "reviewer_model": reviewer,
        "days": args.days,
        "duration_seconds": duration,
        "raw_count": len(final_state["raw_items"]),
        "prefiltered_count": len(final_state["prefiltered_items"]),
        "scored_count": len(scored),
        "alert_count": len(alerts),
        "source_breakdown": source_breakdown,
        "executive_brief": brief,
        "scored_items": scored,
        "alerts": alerts,
        "themes": final_state.get("themes", []),
        "review": review_data,
        "tokens": tracker.input_tokens + tracker.output_tokens,
        "cost": tracker.estimate_cost(model),
        "usage": tracker.to_dict(),
        "errors": errors,
    }
    with open(out_json, "w") as f:
        json.dump(full_results, f, indent=2, default=str)

    # Summary
    flags = {cat: 0 for cat in set(x.get("category", "?") for x in scored)}
    for x in scored:
        flags[x.get("category", "?")] = flags.get(x.get("category", "?"), 0) + 1

    print(f"\n{'='*60}")
    print(f"COMPLETE — {len(scored)} items scored in {duration:.1f}s")
    print(f"Tokens: {tracker.input_tokens + tracker.output_tokens:,} | Cost: ${tracker.estimate_cost(model):.4f}")
    print(f"Alerts: {len(alerts)} | Themes: {len(final_state.get('themes', []))}")
    print(f"Categories: {', '.join(f'{k}={v}' for k, v in sorted(flags.items(), key=lambda x: -x[1]))}")
    if source_breakdown:
        print(f"Sources: {', '.join(f'{k}={v}' for k, v in sorted(source_breakdown.items(), key=lambda x: -x[1]))}")
    print(f"{'='*60}")
    # Log to MLflow
    try:
        from tools.config import get_mlflow_config
        from tools.mlflow_tracker import log_run
        mlflow_cfg = get_mlflow_config()
        if mlflow_cfg.get("enabled", True):
            log_run(
                final_state=final_state,
                tracker=tracker,
                duration=duration,
                out_dir=out_dir,
                model=model,
                reviewer_model=reviewer,
                days=args.days,
                experiment_name=mlflow_cfg.get("experiment_name", "neurotech-newshound"),
            )
    except Exception as e:
        print(f"  [warn] MLflow logging failed: {e}")

    print(f"\n[done] Report: {out_md}")
    print(f"[done] HTML:   {out_html}")
    print(f"[done] Alerts: {out_alerts}")
    print(f"[done] Full JSON: {out_json}")


def main():
    ap = argparse.ArgumentParser(description="NeuroTech NewsHound — agentic research intelligence")
    ap.add_argument("--days", type=int, default=7, help="Lookback window in days")
    ap.add_argument("--max", type=int, default=40, help="Max items per source")
    ap.add_argument("--output-dir", type=str, default=None, help="Output directory")
    ap.add_argument("--model", type=str, default=None, help="LLM model (default: HOUND_LLM_MODEL or gemini-2.0-flash)")
    ap.add_argument("--reviewer", type=str, default=None, help="Reviewer model (default: same as model)")
    ap.add_argument("--phase1-only", action="store_true", help="Phase 1 only: regex scoring, no LLM")
    args = ap.parse_args()

    out_dir = args.output_dir or os.path.join(os.getcwd(), "archives", "neurotech")
    os.makedirs(out_dir, exist_ok=True)

    if args.phase1_only:
        run_phase1(args, out_dir)
    else:
        run_phase2(args, out_dir)


if __name__ == "__main__":
    # Ensure the skill directory is on the path for relative imports
    skill_dir = os.path.dirname(os.path.abspath(__file__))
    if skill_dir not in sys.path:
        sys.path.insert(0, skill_dir)

    main()
