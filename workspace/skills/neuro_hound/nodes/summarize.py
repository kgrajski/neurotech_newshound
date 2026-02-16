"""Summarization nodes — thematic clustering and executive brief (LLM)."""
from state import HoundState
from tools.llm import create_llm, invoke_llm, parse_json


def summarize_themes(state: HoundState) -> HoundState:
    """
    Cluster scored items into 2-5 themes.

    Equivalent of analyze_themes in the trading analyst.
    """
    items = state["scored_items"]
    if not items:
        state["themes"] = []
        return state

    print("  Clustering themes...")
    llm = create_llm(state["model"])

    # Build item summaries for the prompt
    item_lines = []
    for x in items[:30]:  # Cap at 30 for prompt length
        score = x.get("llm_score", "?")
        cat = x.get("category", "?")
        title = x.get("title", "")[:100]
        assessment = x.get("assessment", "")[:150]
        item_lines.append(f"- [{score}] ({cat}) {title}\n  {assessment}")

    prompt = f"""You are a senior neurotechnology research analyst preparing a weekly intelligence briefing.

Here are {len(items)} scored research items from the past week:

{chr(10).join(item_lines)}

TASK: Group these into 2-5 coherent themes based on what they're actually about (not source or score).

For each theme:
1. Name it concisely (e.g., "Speech Decoding Advances", "Electrode Longevity")
2. List which items belong to it (by title snippet)
3. Assess significance: routine / notable / breakthrough
4. Write a 2-3 sentence narrative: what happened and why it matters

Respond in JSON:
{{"themes": [
    {{"name": "...",
     "items": ["title snippet 1", "title snippet 2"],
     "significance": "routine/notable/breakthrough",
     "narrative": "2-3 sentences"}}
 ],
 "overall_assessment": "quiet_week/active_week/major_developments",
 "summary": "1-2 sentence overall summary of the week in neurotech"}}"""

    try:
        content = invoke_llm(llm, prompt, node="summarize_themes", model_name=state["model"])
        result = parse_json(content)
        state["themes"] = result.get("themes", [])
        print(f"  Themes: {len(state['themes'])} identified")
        for t in state["themes"]:
            print(f"    - {t.get('name', '?')} ({t.get('significance', '?')})")
    except Exception as e:
        state["errors"].append(f"Themes: {e}")
        state["themes"] = []

    return state


def write_brief(state: HoundState) -> HoundState:
    """
    Write the executive briefing memo from themes and scored items.

    This produces the final human-readable output — the "decision artifact"
    that replaces manual scanning of dozens of papers.
    """
    themes = state.get("themes", [])
    items = state["scored_items"]
    alerts = state["alerts"]

    if not themes and not items:
        state["executive_brief"] = "_No items to report this week._"
        return state

    print("  Writing executive brief...")
    llm = create_llm(state["model"])

    # Format themes for prompt
    themes_text = ""
    for t in themes:
        themes_text += f"\nTheme: {t.get('name', '?')} ({t.get('significance', '?')})\n"
        themes_text += f"  Narrative: {t.get('narrative', '')}\n"
        themes_text += f"  Items: {', '.join(t.get('items', []))}\n"

    # Format alerts
    alerts_text = ""
    if alerts:
        for a in alerts:
            alerts_text += f"- [{a.get('llm_score')}] {a.get('title', '')[:80]}: {a.get('assessment', '')}\n"
    else:
        alerts_text = "None this week."

    # Top items by score
    top_items = ""
    for x in items[:10]:
        top_items += f"- [{x.get('llm_score', '?')}] {x.get('title', '')[:80]} ({x.get('category', '?')})\n"

    prompt = f"""You are writing a weekly NeuroTech intelligence briefing for a senior researcher specializing in implantable BCIs, ECoG/sEEG, and neural interfaces.

THEMES IDENTIFIED:
{themes_text or "No themes identified."}

PRIORITY ALERTS (score 9-10):
{alerts_text}

TOP ITEMS THIS WEEK:
{top_items}

Write a concise executive briefing in Markdown with these sections:

1. **TL;DR** — 2-3 sentences: What mattered this week?
2. **Themes** — For each theme: "What's new" (1-2 sentences) and "Why it matters" (1 sentence)
3. **Priority Alerts** — Detail any 9-10 scored items, or note "None"
4. **What to Watch** — 2-3 things to monitor next week based on this week's signals

Be analytical, not performative. Skip filler. Have opinions on scientific validity.
Write as a Senior Research Associate, not a corporate drone."""

    try:
        content = invoke_llm(llm, prompt, node="write_brief", model_name=state["model"])
        state["executive_brief"] = content
        print("  Executive brief written")
    except Exception as e:
        state["errors"].append(f"Brief: {e}")
        state["executive_brief"] = f"_Brief generation failed: {e}_"

    return state
