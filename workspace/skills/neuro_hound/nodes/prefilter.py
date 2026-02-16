"""Pre-filter node — regex-based triage + deduplication before LLM scoring."""
from state import HoundState
from tools.scoring import is_in_scope, regex_score
from tools.dedup import load_history, filter_seen, get_history_summary


def prefilter(state: HoundState) -> HoundState:
    """
    Fast regex pre-filter + dedup: keep only in-scope, unseen items.

    Two-stage cost-control gate:
    1. Regex: ~300 raw items → ~50 in-scope candidates
    2. Dedup: skip items previously scored < 7 (confirmed low-value)

    Items scored >= 7 in a prior run are re-evaluated (things evolve).
    """
    # Stage 1: Regex pre-filter
    print("  Pre-filtering with regex...")
    kept = []
    for item in state["raw_items"]:
        title = item.get("title", "")
        summary = item.get("summary", "")
        source = item.get("source", "")

        if is_in_scope(title, summary, source):
            item["regex_score"] = regex_score(title, summary, source)
            kept.append(item)

    regex_count = len(kept)

    # Stage 2: Dedup against history
    history = load_history()
    print(f"  {get_history_summary(history)}")
    to_score, skipped = filter_seen(kept, history)

    # Sort by regex score descending (best candidates first for LLM)
    to_score.sort(key=lambda x: x.get("regex_score", 0), reverse=True)
    state["prefiltered_items"] = to_score

    # Store history ref for post-scoring update
    state["_dedup_history"] = history

    dedup_saved = regex_count - len(to_score)
    print(f"  Pre-filter: {len(state['raw_items'])} → {regex_count} in-scope → {len(to_score)} to score ({dedup_saved} deduped)")
    return state
