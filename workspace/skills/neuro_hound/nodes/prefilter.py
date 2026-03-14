"""Pre-filter node — regex triage + date gate + deduplication before LLM scoring."""
from state import HoundState
from tools.scoring import is_in_scope, regex_score
from tools.dedup import load_history, filter_seen, get_history_summary
from tools.date_utils import date_gate


def prefilter(state: HoundState) -> HoundState:
    """
    Fast pre-filter pipeline: regex → date gate → dedup.

    Three-stage cost-control gate:
    1. Regex: ~300 raw items → ~50 in-scope candidates
    2. Date gate: discard items published outside lookback window
       (catches Tavily's unreliable date filtering)
    3. Dedup: skip items previously scored < 7 (confirmed low-value)

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

    # Stage 2: Date gate — discard items outside lookback window
    fresh, stale = date_gate(kept, state["days"], grace_days=2)
    if stale:
        stale_sources = {}
        for s in stale:
            src = s.get("source", "unknown")
            stale_sources[src] = stale_sources.get(src, 0) + 1
        stale_summary = ", ".join(f"{k}={v}" for k, v in sorted(stale_sources.items(), key=lambda x: -x[1]))
        print(f"  Date gate: {len(stale)} stale items removed ({stale_summary})")
        state["errors"].append(
            f"Date gate: {len(stale)} items outside {state['days']}+2d lookback "
            f"({stale_summary})"
        )

    # Stage 3: Dedup against history
    history = load_history()
    print(f"  {get_history_summary(history)}")
    to_score, skipped = filter_seen(fresh, history)

    # Sort by regex score descending (best candidates first for LLM)
    to_score.sort(key=lambda x: x.get("regex_score", 0), reverse=True)
    state["prefiltered_items"] = to_score

    # Store history ref for post-scoring update
    state["_dedup_history"] = history

    dedup_saved = len(fresh) - len(to_score)
    print(f"  Pre-filter: {len(state['raw_items'])} raw → {regex_count} in-scope → {len(fresh)} fresh → {len(to_score)} to score ({dedup_saved} deduped)")
    return state
