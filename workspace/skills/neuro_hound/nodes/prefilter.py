"""Pre-filter node — regex-based triage to cut items before LLM scoring."""
from state import HoundState
from tools.scoring import is_in_scope, regex_score


def prefilter(state: HoundState) -> HoundState:
    """
    Fast regex pre-filter: keep only in-scope items.

    This is the cost-control gate. ~70 raw items → ~25-30 in-scope candidates
    that will be individually scored by the LLM. Everything else is discarded
    before any API calls are made.
    """
    print("  Pre-filtering with regex...")
    kept = []
    for item in state["raw_items"]:
        title = item.get("title", "")
        summary = item.get("summary", "")
        source = item.get("source", "")

        if is_in_scope(title, summary, source):
            item["regex_score"] = regex_score(title, summary, source)
            kept.append(item)

    # Sort by regex score descending (best candidates first for LLM)
    kept.sort(key=lambda x: x.get("regex_score", 0), reverse=True)
    state["prefiltered_items"] = kept

    print(f"  Pre-filter: {len(state['raw_items'])} → {len(kept)} in-scope")
    return state
