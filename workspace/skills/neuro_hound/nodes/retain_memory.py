"""
Retain memory node — persist discovered entities across runs.

After scoring and review, this node extracts entities from high-scoring
Tavily items and updates discovery_memory.json. It also increments
consecutive_misses for entities not seen in the current run.

This is the "Retain" step of the Retain/Recall/Reflect pattern
(Hindsight, arXiv:2512.12818).
"""
from state import HoundState
from tools.memory import (
    load_memory, save_memory, retain_entities,
    increment_misses, get_seen_entity_keys, get_memory_summary,
)


def retain_memory(state: HoundState) -> HoundState:
    """Update discovery memory with entities found (or not found) this run."""
    scored = state.get("scored_items", [])
    if not scored:
        return state

    print("  Updating discovery memory...")
    memory = state.get("_discovery_memory") or load_memory()

    new_count, updated_count = retain_entities(memory, scored, min_score=6)

    seen_keys = get_seen_entity_keys(scored, min_score=6)
    increment_misses(memory, seen_keys)

    save_memory(memory)
    state["_discovery_memory"] = memory

    summary = get_memory_summary(memory)
    print(f"  [ok] Memory: +{new_count} new, {updated_count} updated")
    print(f"  {summary}")

    return state
