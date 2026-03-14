#!/usr/bin/env python3
"""
Bootstrap discovery memory from existing data.

Seeds discovery_memory.json from:
  1. seen_items.json (dedup history) — high-scoring items become entities
  2. discoveries.yaml — previously discovered companies
  3. vocabulary.yaml — known terms (marks them as already-known context)

Run once when transitioning from Phase 9 to Phase 10b. Safe to re-run
(skips entities already in memory).

Usage:
    cd workspace/skills/neuro_hound
    python3 bootstrap_memory.py
    python3 bootstrap_memory.py --dry-run     # preview without writing
    python3 bootstrap_memory.py --seen-items path/to/seen_items.json
"""
import argparse
import json
import os
import sys
import yaml

skill_dir = os.path.dirname(os.path.abspath(__file__))
if skill_dir not in sys.path:
    sys.path.insert(0, skill_dir)

from tools.memory import (
    load_memory, save_memory,
    bootstrap_from_seen_items, bootstrap_from_discoveries,
    get_memory_summary,
)


def main():
    ap = argparse.ArgumentParser(description="Bootstrap discovery memory from existing data")
    ap.add_argument("--seen-items", type=str, default=None,
                    help="Path to seen_items.json (dedup history)")
    ap.add_argument("--discoveries", type=str, default=None,
                    help="Path to discoveries.yaml")
    ap.add_argument("--dry-run", action="store_true",
                    help="Preview changes without writing")
    args = ap.parse_args()

    seen_items_path = args.seen_items or os.path.join(skill_dir, "seen_items.json")
    discoveries_path = args.discoveries or os.path.join(
        skill_dir, "..", "..", "archives", "neurotech", "discoveries.yaml"
    )

    memory = load_memory()
    total_before = len(memory["entities"])

    print(f"Bootstrapping discovery memory...")
    print(f"  Current state: {get_memory_summary(memory)}")
    print()

    # 1. Bootstrap from seen_items.json
    if os.path.exists(seen_items_path):
        with open(seen_items_path) as f:
            seen_items = json.load(f)
        count = bootstrap_from_seen_items(seen_items, memory, min_score=7)
        print(f"  [seen_items.json] {count} entities extracted from {len(seen_items)} items")
    else:
        print(f"  [seen_items.json] Not found at {seen_items_path} — skipping")

    # 2. Bootstrap from discoveries.yaml
    if os.path.exists(discoveries_path):
        with open(discoveries_path) as f:
            discoveries = yaml.safe_load(f) or []
        count = bootstrap_from_discoveries(discoveries, memory)
        print(f"  [discoveries.yaml] {count} entities from {len(discoveries)} discoveries")
    else:
        print(f"  [discoveries.yaml] Not found at {discoveries_path} — skipping")

    # 3. Mark watchlist companies as promoted
    try:
        from tools.config import get_watchlist_company_names
        from tools.memory import _entity_key, mark_promoted
        watchlist_names = get_watchlist_company_names()
        promoted = 0
        for name in watchlist_names:
            key = _entity_key(name)
            if key in memory["entities"]:
                if memory["entities"][key].get("status") != "promoted":
                    mark_promoted(memory, key)
                    promoted += 1
        if promoted:
            print(f"  [watchlist] {promoted} entities marked as already-promoted")
    except Exception as e:
        print(f"  [watchlist] Skipped: {e}")

    total_after = len(memory["entities"])
    print(f"\n  Result: {total_before} → {total_after} entities (+{total_after - total_before})")
    print(f"  {get_memory_summary(memory)}")

    if args.dry_run:
        print("\n  [dry-run] No changes written.")
        print("  Entities that would be created:")
        for key, ent in memory["entities"].items():
            print(f"    {key}: {ent['name']} (score={ent['best_score']}, status={ent['status']})")
    else:
        save_memory(memory)
        print(f"\n  [ok] Saved to discovery_memory.json")


if __name__ == "__main__":
    main()
