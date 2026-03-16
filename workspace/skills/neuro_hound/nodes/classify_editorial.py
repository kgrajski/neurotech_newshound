"""
Editorial classification node — classifies stories against editorial memory.

Inserted after cluster_stories and before retain_memory:
    review → cluster_stories → classify_editorial → retain_memory → meta_reflect

Uses embedding-based semantic matching to determine if a story has been
previously reported to the user. Each item gets an _editorial_class:
    BREAKING  — genuinely new story
    DISCOVERY — old item, but never reported before (valuable find)
    FOLLOW_UP — previously reported, new sources added
    REHASH    — previously reported, no new info (suppress from alerts)
"""
from state import HoundState
from tools.editorial_memory import (
    load_editorial_memory,
    save_editorial_memory,
    classify_stories,
    retain_reported_stories,
    get_editorial_summary,
    get_classification_counts,
)


def classify_editorial(state: HoundState) -> HoundState:
    """Classify scored items against editorial memory and update alerts."""
    scored = state.get("scored_items", [])
    if not scored:
        return state

    memory = load_editorial_memory()
    print(f"  {get_editorial_summary(memory)}")

    print(f"  Classifying stories against editorial memory...")
    classified = classify_stories(scored, memory, lookback_days=state["days"])

    counts = get_classification_counts(classified)
    print(f"  [ok] Editorial classification: "
          f"{counts['BREAKING']} breaking, "
          f"{counts['DISCOVERY']} discoveries, "
          f"{counts['FOLLOW_UP']} follow-ups, "
          f"{counts['REHASH']} rehashes")

    rehash_count = counts["REHASH"]
    if rehash_count > 0:
        suppressed = [
            item for item in classified
            if item.get("_editorial_class") == "REHASH"
            and item.get("llm_score", 0) >= 9
        ]
        if suppressed:
            titles = [f"'{item.get('title', '')[:50]}'" for item in suppressed[:3]]
            print(f"    Suppressed from alerts: {', '.join(titles)}")

    alerts = [
        item for item in scored
        if item.get("llm_score", 0) >= 9
        and not item.get("_cluster_secondary")
        and item.get("_editorial_class") != "REHASH"
    ]
    state["alerts"] = alerts

    retain_reported_stories(memory, classified)
    save_editorial_memory(memory)

    story_count = len(memory.get("stories", {}))
    print(f"  Editorial memory updated: {story_count} stories tracked")

    return state
