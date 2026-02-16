"""
Deduplication — avoid re-scoring items seen in previous runs.

Stores a hash of (title, url) for every scored item. On subsequent runs,
items with known hashes are filtered:
    - Score < 7 in prior run → skip entirely (confirmed low-value)
    - Score >= 7 in prior run → re-evaluate (things evolve)

The history file is a simple JSON mapping:
    hash → {score, category, first_seen, last_seen, run_count}
"""
import datetime as dt
import hashlib
import json
import os
from typing import Any, Dict, List, Tuple

HISTORY_FILE = os.path.join(os.path.dirname(__file__), "..", "seen_items.json")
RE_EVALUATE_THRESHOLD = 7  # Items scored >= this are re-evaluated each run


def _item_hash(title: str, url: str) -> str:
    """Stable hash from title + url."""
    key = f"{title.strip().lower()}|{url.strip().lower()}"
    return hashlib.sha256(key.encode()).hexdigest()[:16]


def load_history(path: str = None) -> Dict[str, Dict[str, Any]]:
    """Load seen items history from JSON."""
    path = path or HISTORY_FILE
    if os.path.exists(path):
        with open(path) as f:
            return json.load(f)
    return {}


def save_history(history: Dict[str, Dict[str, Any]], path: str = None):
    """Persist seen items history to JSON."""
    path = path or HISTORY_FILE
    with open(path, "w") as f:
        json.dump(history, f, indent=2, default=str)


def filter_seen(
    items: List[Dict[str, Any]],
    history: Dict[str, Dict[str, Any]],
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """
    Partition items into (to_score, skipped).

    - Items never seen before → to_score
    - Items seen with score < RE_EVALUATE_THRESHOLD → skipped
    - Items seen with score >= RE_EVALUATE_THRESHOLD → to_score (re-evaluate)
    """
    to_score = []
    skipped = []

    for item in items:
        h = _item_hash(item.get("title", ""), item.get("url", ""))
        item["_hash"] = h
        prior = history.get(h)

        if prior is None:
            to_score.append(item)
        elif prior.get("score", 0) >= RE_EVALUATE_THRESHOLD:
            item["_prior_score"] = prior.get("score")
            item["_prior_category"] = prior.get("category")
            to_score.append(item)
        else:
            item["_skipped_reason"] = f"Previously scored {prior.get('score', '?')} on {prior.get('last_seen', '?')}"
            skipped.append(item)

    return to_score, skipped


def update_history(
    history: Dict[str, Dict[str, Any]],
    scored_items: List[Dict[str, Any]],
):
    """Update history with newly scored items."""
    today = dt.date.today().isoformat()
    for item in scored_items:
        h = item.get("_hash") or _item_hash(item.get("title", ""), item.get("url", ""))
        score = item.get("llm_score", item.get("score", 0))
        category = item.get("category", "unknown")

        existing = history.get(h)
        if existing:
            existing["score"] = score
            existing["category"] = category
            existing["last_seen"] = today
            existing["run_count"] = existing.get("run_count", 1) + 1
        else:
            history[h] = {
                "title": item.get("title", "")[:100],
                "score": score,
                "category": category,
                "first_seen": today,
                "last_seen": today,
                "run_count": 1,
            }


def get_history_summary(history: Dict[str, Dict[str, Any]]) -> str:
    """Human-readable summary of dedup history."""
    total = len(history)
    if total == 0:
        return "Dedup history: empty (first run)"
    scores = [v.get("score", 0) for v in history.values()]
    high = sum(1 for s in scores if s >= 7)
    low = sum(1 for s in scores if s < 7)
    return f"Dedup history: {total} items tracked ({high} high-value, {low} low-value)"
