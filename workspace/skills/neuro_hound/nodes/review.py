"""Review node — Reflection Pattern (LLM critiques the brief)."""
from state import HoundState
from tools.llm import create_llm, invoke_llm, parse_json


def review(state: HoundState) -> HoundState:
    """
    REFLECTION NODE: A reviewer critiques the executive brief.

    Implements the Reflection Pattern from the trading analyst:
    - Check if significance assessments are calibrated
    - Flag any miscategorized items
    - Identify missed signals or themes
    - Call out vaporware or marketing that slipped through
    - Suggest score adjustments

    Uses HOUND_REVIEWER_MODEL if configured (different from analyst model),
    enabling diverse perspectives or premium review.
    """
    brief = state.get("executive_brief", "")
    themes = state.get("themes", [])
    scored = state.get("scored_items", [])

    if not brief or brief.startswith("_"):
        state["review"] = {"assessment": "SKIPPED", "notes": "No brief to review."}
        return state

    reviewer_model = state.get("reviewer_model") or state["model"]
    print(f"  Reviewing brief (Reflection Pattern) with {reviewer_model}...")
    llm = create_llm(reviewer_model)

    # Build scored items summary for reviewer context
    items_text = ""
    for x in scored[:20]:
        items_text += (
            f"- [{x.get('llm_score', '?')}] {x.get('category', '?')}: "
            f"{x.get('title', '')[:70]} — {x.get('assessment', '')[:100]}\n"
        )

    # Themes summary
    themes_text = ""
    for t in themes:
        themes_text += f"- {t.get('name', '?')} ({t.get('significance', '?')}): {t.get('narrative', '')[:100]}\n"

    prompt = f"""You are a Principal Investigator reviewing a weekly NeuroTech intelligence briefing prepared by a research associate.

Your domain: implantable BCIs, ECoG/sEEG, microstimulation, neural interface materials, FDA regulatory pathway.

=== EXECUTIVE BRIEF TO REVIEW ===
{brief}

=== THEMES ===
{themes_text or "No themes."}

=== UNDERLYING SCORED ITEMS ===
{items_text or "No items."}

=== YOUR REVIEW TASK ===
1. Are the significance assessments calibrated? (Is anything overhyped or underappreciated?)
2. Are items correctly categorized? Any obvious miscategorizations?
3. Did the analyst miss any themes or connections between items?
4. Any items that look like vaporware, marketing, or press-release science?
5. Which 1-3 items are the most genuinely important this week?

Respond in JSON:
{{"assessment": "APPROVE/NEEDS_REVISION",
 "quality_score": 1-10,
 "score_adjustments": [
     {{"title_snippet": "...", "original_score": N, "adjusted_score": M, "reason": "..."}}
 ],
 "missed_signals": ["anything the analyst should have caught"],
 "top_picks": ["1-3 most important items this week"],
 "vaporware_flags": ["items that seem like marketing/hype"],
 "reviewer_notes": "2-3 sentence summary of review"}}"""

    try:
        content = invoke_llm(llm, prompt, node="review", model_name=reviewer_model)
        result = parse_json(content)
        state["review"] = result

        # Apply score adjustments
        adjustments = result.get("score_adjustments", [])
        if adjustments:
            for adj in adjustments:
                snippet = adj.get("title_snippet", "")
                new_score = adj.get("adjusted_score")
                if snippet and new_score is not None:
                    for item in state["scored_items"]:
                        if snippet.lower() in item.get("title", "").lower():
                            old = item.get("llm_score", "?")
                            item["llm_score_original"] = old
                            item["llm_score"] = new_score
                            item["adjusted_by_reviewer"] = True
                            item["adjustment_reason"] = adj.get("reason", "")
                            print(f"    Adjusted: {snippet[:40]}... {old} → {new_score}")
                            break

        # Re-sort and re-generate alerts after adjustments
        state["scored_items"].sort(key=lambda x: x.get("llm_score", 0), reverse=True)
        state["alerts"] = [x for x in state["scored_items"] if x.get("llm_score", 0) >= 9]

        assessment = result.get("assessment", "N/A")
        quality = result.get("quality_score", "?")
        print(f"  Review: {assessment} (quality: {quality}/10)")
        top = result.get("top_picks", [])
        if top:
            print(f"  Top picks: {', '.join(str(t)[:40] for t in top)}")
    except Exception as e:
        state["errors"].append(f"Review: {e}")
        state["review"] = {"assessment": "ERROR", "reviewer_notes": str(e)}

    return state
