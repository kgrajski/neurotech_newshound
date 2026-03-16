"""
Editorial memory — tracks stories reported to the user across runs.

Extends the HindSight pattern from entity-level (discovery_memory.json)
to story-level tracking. While discovery memory asks "what entities have
I found?", editorial memory asks "what stories have I told the user about?"

This enables story classification:
    BREAKING  — new story, not previously reported
    DISCOVERY — old item (>90 days), but never reported before
    FOLLOW_UP — previously reported story with new sources/developments
    REHASH    — previously reported, no new information — suppress

Matching uses OpenAI embeddings (text-embedding-3-small) for deterministic
semantic similarity. Unlike chat completions, embedding models produce the
same vector for the same input every time — no sampling, no temperature.

editorial_memory.json structure:
    stories:
        story_key → {headline, entity, embedding, first_reported,
                     last_reported, times_reported, source_count, urls}
    meta:
        {created, last_updated, total_reports, version}
"""
import datetime as dt
import json
import os
import re
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

MEMORY_FILE = os.path.join(os.path.dirname(__file__), "..", "editorial_memory.json")
EMBEDDING_MODEL = "text-embedding-3-small"

SIMILARITY_THRESHOLD = 0.82
DISCOVERY_AGE_DAYS = 90


def load_editorial_memory(path: str = None) -> Dict[str, Any]:
    """Load editorial memory from JSON."""
    path = path or MEMORY_FILE
    if os.path.exists(path) and os.path.getsize(path) > 0:
        with open(path) as f:
            data = json.load(f)
            data.setdefault("stories", {})
            data.setdefault("meta", _default_meta())
            return data
    return {"stories": {}, "meta": _default_meta()}


def save_editorial_memory(memory: Dict[str, Any], path: str = None):
    """Persist editorial memory to JSON."""
    path = path or MEMORY_FILE
    memory["meta"]["last_updated"] = dt.date.today().isoformat()
    with open(path, "w") as f:
        json.dump(memory, f, indent=2, default=str)


def _default_meta() -> Dict[str, Any]:
    return {
        "created": dt.date.today().isoformat(),
        "last_updated": dt.date.today().isoformat(),
        "total_reports": 0,
        "version": 1,
    }


# ── EMBEDDINGS ──────────────────────────────────────────────────────────

def _get_embedding_client():
    """Lazy-load the OpenAI client for embeddings."""
    from openai import OpenAI
    return OpenAI()


def compute_embedding(text: str) -> List[float]:
    """Compute a deterministic embedding vector for text."""
    client = _get_embedding_client()
    response = client.embeddings.create(
        model=EMBEDDING_MODEL,
        input=text[:8000],
    )
    return response.data[0].embedding


def compute_embeddings_batch(texts: List[str]) -> List[List[float]]:
    """Compute embeddings for multiple texts in one API call."""
    if not texts:
        return []
    client = _get_embedding_client()
    truncated = [t[:8000] for t in texts]
    response = client.embeddings.create(
        model=EMBEDDING_MODEL,
        input=truncated,
    )
    return [item.embedding for item in response.data]


def cosine_similarity(a: List[float], b: List[float]) -> float:
    """Cosine similarity between two embedding vectors."""
    va = np.array(a)
    vb = np.array(b)
    dot = np.dot(va, vb)
    norm = np.linalg.norm(va) * np.linalg.norm(vb)
    if norm == 0:
        return 0.0
    return float(dot / norm)


# ── STORY TEXT ──────────────────────────────────────────────────────────

def _story_text(item: Dict[str, Any]) -> str:
    """Build the text to embed for a story: title + LLM assessment."""
    title = item.get("title", "")[:200]
    assessment = item.get("assessment", "")[:500]
    return f"{title}\n{assessment}"


def _story_key(headline: str) -> str:
    """Normalize a headline into a stable key."""
    return re.sub(r"[^a-z0-9]+", "_", headline.strip().lower()).strip("_")[:80]


# ── CLASSIFY ────────────────────────────────────────────────────────────

def classify_stories(
    scored_items: List[Dict[str, Any]],
    memory: Dict[str, Any],
    lookback_days: int = 7,
) -> List[Dict[str, Any]]:
    """Classify each scored item against editorial memory.

    Computes embeddings for all items that need classification (score >= 6,
    not cluster secondaries), then compares against stored story embeddings.

    Adds '_editorial_class' field to each classified item:
        BREAKING, DISCOVERY, FOLLOW_UP, REHASH

    Returns the list of items that were classified (for memory update).
    """
    candidates = [
        item for item in scored_items
        if item.get("llm_score", 0) >= 6
        and not item.get("_cluster_secondary")
    ]

    if not candidates:
        return []

    stories = memory.get("stories", {})
    stored_embeddings = []
    stored_keys = []
    for key, story in stories.items():
        emb = story.get("embedding")
        if emb:
            stored_embeddings.append(emb)
            stored_keys.append(key)

    texts = [_story_text(item) for item in candidates]
    try:
        new_embeddings = compute_embeddings_batch(texts)
    except Exception as e:
        print(f"  [warn] Embedding computation failed: {e}")
        for item in candidates:
            item["_editorial_class"] = "BREAKING"
            item["_embedding"] = None
        return candidates

    today = dt.date.today()
    classified = []

    for item, embedding in zip(candidates, new_embeddings):
        item["_embedding"] = embedding

        best_sim = 0.0
        best_key = None
        for stored_emb, key in zip(stored_embeddings, stored_keys):
            sim = cosine_similarity(embedding, stored_emb)
            if sim > best_sim:
                best_sim = sim
                best_key = key

        if best_sim >= SIMILARITY_THRESHOLD and best_key:
            stored_story = stories[best_key]
            item["_editorial_match"] = best_key
            item["_editorial_similarity"] = round(best_sim, 3)

            old_urls = set(stored_story.get("urls", []))
            new_url = item.get("url", "")
            has_new_source = new_url and new_url not in old_urls

            if has_new_source:
                item["_editorial_class"] = "FOLLOW_UP"
            else:
                item["_editorial_class"] = "REHASH"
        else:
            item_date = _get_item_age(item)
            if item_date and (today - item_date).days > DISCOVERY_AGE_DAYS:
                item["_editorial_class"] = "DISCOVERY"
            else:
                item["_editorial_class"] = "BREAKING"

        classified.append(item)

    return classified


def _get_item_age(item: Dict[str, Any]) -> Optional[dt.date]:
    """Extract item publication date, including from URL patterns."""
    from tools.date_utils import extract_item_date, parse_date

    d = extract_item_date(item)
    if d:
        return d

    url = item.get("url", "")
    url_date = _extract_date_from_url(url)
    if url_date:
        return url_date

    return None


def _extract_date_from_url(url: str) -> Optional[dt.date]:
    """Extract publication date from URL path patterns like /2021/10/."""
    if not url:
        return None
    m = re.search(r"/(\d{4})/(\d{1,2})/", url)
    if m:
        try:
            year = int(m.group(1))
            month = int(m.group(2))
            if 2000 <= year <= 2030 and 1 <= month <= 12:
                return dt.date(year, month, 1)
        except ValueError:
            pass
    m = re.search(r"/(\d{4})/", url)
    if m:
        try:
            year = int(m.group(1))
            if 2000 <= year <= 2030:
                return dt.date(year, 1, 1)
        except ValueError:
            pass
    return None


# ── RETAIN (update memory after reporting) ──────────────────────────────

def retain_reported_stories(
    memory: Dict[str, Any],
    classified_items: List[Dict[str, Any]],
):
    """Record reported stories into editorial memory.

    Called after report generation. Only retains BREAKING and DISCOVERY
    items (new stories being reported for the first time) and updates
    FOLLOW_UP stories with new source URLs.
    """
    today = dt.date.today().isoformat()
    stories = memory["stories"]

    for item in classified_items:
        cls = item.get("_editorial_class", "")
        if cls in ("BREAKING", "DISCOVERY"):
            headline = item.get("title", "")[:120]
            key = _story_key(headline)
            if not key:
                continue

            embedding = item.get("_embedding")
            stories[key] = {
                "headline": headline,
                "entity": _extract_primary_entity(item),
                "category": item.get("category", ""),
                "embedding": embedding,
                "first_reported": today,
                "last_reported": today,
                "times_reported": 1,
                "source_count": item.get("_cluster_size", 1),
                "urls": _collect_urls(item),
                "score": item.get("llm_score", 0),
                "editorial_class": cls,
            }

        elif cls == "FOLLOW_UP":
            match_key = item.get("_editorial_match", "")
            if match_key and match_key in stories:
                story = stories[match_key]
                story["last_reported"] = today
                story["times_reported"] = story.get("times_reported", 1) + 1
                new_url = item.get("url", "")
                if new_url and new_url not in story.get("urls", []):
                    story["urls"].append(new_url)
                story["source_count"] = len(story.get("urls", []))

    memory["meta"]["total_reports"] = memory["meta"].get("total_reports", 0) + 1


def _extract_primary_entity(item: Dict[str, Any]) -> str:
    """Best-effort entity extraction from a scored item."""
    source = item.get("source", "")
    title = item.get("title", "")

    for known in _KNOWN_ENTITIES:
        if known.lower() in title.lower() or known.lower() in source.lower():
            return known
    return ""


_KNOWN_ENTITIES = [
    "Paradromics", "Neuralink", "Synchron", "Precision Neuroscience",
    "Blackrock Neurotech", "Axoft", "INBRAIN", "Cortera", "Science Corp",
    "Motif Neurotech", "Tether", "BrainGate", "Stentrode",
]


def _collect_urls(item: Dict[str, Any]) -> List[str]:
    """Collect all URLs associated with an item (primary + also-reported-by)."""
    urls = []
    if item.get("url"):
        urls.append(item["url"])
    for r in item.get("_also_reported_by", []):
        if r.get("url"):
            urls.append(r["url"])
    return urls


# ── REPORTING HELPERS ───────────────────────────────────────────────────

def get_editorial_summary(memory: Dict[str, Any]) -> str:
    """Human-readable summary of editorial memory state."""
    stories = memory.get("stories", {})
    meta = memory.get("meta", {})

    if not stories:
        return "Editorial memory: empty (first run)"

    total = len(stories)
    by_class = {}
    for s in stories.values():
        cls = s.get("editorial_class", "unknown")
        by_class[cls] = by_class.get(cls, 0) + 1

    lines = [
        f"Editorial memory: {total} stories tracked across {meta.get('total_reports', '?')} reports",
        f"  BREAKING: {by_class.get('BREAKING', 0)} | "
        f"DISCOVERY: {by_class.get('DISCOVERY', 0)}",
    ]

    recent = sorted(
        stories.values(),
        key=lambda s: s.get("last_reported", ""),
        reverse=True,
    )[:5]
    if recent:
        lines.append("  Recent stories:")
        for s in recent:
            lines.append(f"    - {s.get('headline', '?')[:60]} ({s.get('first_reported', '?')})")

    return "\n".join(lines)


def get_classification_counts(classified_items: List[Dict[str, Any]]) -> Dict[str, int]:
    """Count items by editorial classification."""
    counts = {"BREAKING": 0, "DISCOVERY": 0, "FOLLOW_UP": 0, "REHASH": 0}
    for item in classified_items:
        cls = item.get("_editorial_class", "BREAKING")
        counts[cls] = counts.get(cls, 0) + 1
    return counts
