"""
Discovery memory — persistent structured memory across runs.

Implements the Retain/Recall/Reflect pattern inspired by Hindsight
(arXiv:2512.12818). Tracks entities discovered via Tavily wideband
search so they are never "forgotten" due to retrieval stochasticity.

Memory structure (discovery_memory.json):
    entities:
        entity_key → {name, entity_type, first_seen, last_seen,
                       times_seen, consecutive_misses, best_score,
                       best_category, status, search_terms, evidence}
    meta:
        {created, last_updated, total_runs, version}

Lifecycle:
    1. RETAIN — after scoring, extract entities from high-scoring Tavily
       items and update memory (times_seen++, last_seen, evidence)
    2. RECALL — before Tavily fetch, generate targeted queries for
       "cold" entities (active but not seen recently)
    3. REFLECT — meta-agent reviews memory health, promotes consistent
       entities to config.yaml watchlist, archives stale ones
"""
import datetime as dt
import json
import os
import re
from typing import Any, Dict, List, Optional, Tuple

MEMORY_FILE = os.path.join(os.path.dirname(__file__), "..", "discovery_memory.json")

COLD_THRESHOLD_DAYS = 14
COLD_THRESHOLD_MISSES = 3
PROMOTION_THRESHOLD_TIMES_SEEN = 4
ARCHIVE_THRESHOLD_MISSES = 8


def _entity_key(name: str) -> str:
    """Normalize an entity name into a stable key."""
    return re.sub(r"[^a-z0-9]+", "_", name.strip().lower()).strip("_")


def load_memory(path: str = None) -> Dict[str, Any]:
    """Load discovery memory from JSON. Returns empty structure if absent or empty."""
    path = path or MEMORY_FILE
    if os.path.exists(path) and os.path.getsize(path) > 0:
        with open(path) as f:
            data = json.load(f)
            if "entities" not in data:
                data["entities"] = {}
            if "meta" not in data:
                data["meta"] = _default_meta()
            return data
    return {"entities": {}, "meta": _default_meta()}


def save_memory(memory: Dict[str, Any], path: str = None):
    """Persist discovery memory to JSON."""
    path = path or MEMORY_FILE
    memory["meta"]["last_updated"] = dt.date.today().isoformat()
    with open(path, "w") as f:
        json.dump(memory, f, indent=2, default=str)


def _default_meta() -> Dict[str, Any]:
    return {
        "created": dt.date.today().isoformat(),
        "last_updated": dt.date.today().isoformat(),
        "total_runs": 0,
        "version": 1,
    }


# ── RETAIN ────────────────────────────────────────────────────────────


def retain_entities(
    memory: Dict[str, Any],
    scored_items: List[Dict[str, Any]],
    min_score: int = 6,
) -> Tuple[int, int]:
    """
    Extract entities from high-scoring Tavily items and update memory.

    Returns (new_count, updated_count).
    """
    today = dt.date.today().isoformat()
    entities = memory["entities"]
    new_count = 0
    updated_count = 0

    tavily_items = [
        it for it in scored_items
        if it.get("source_id") == "tavily_wideband"
        and it.get("llm_score", it.get("score", 0)) >= min_score
    ]

    for item in tavily_items:
        names = _extract_entity_names(item)
        score = item.get("llm_score", item.get("score", 0))
        category = item.get("category", "unknown")
        title = item.get("title", "")[:120]
        url = item.get("url", "")

        for name in names:
            key = _entity_key(name)
            if not key or len(key) < 3:
                continue

            if key in entities:
                ent = entities[key]
                ent["last_seen"] = today
                ent["times_seen"] = ent.get("times_seen", 1) + 1
                ent["consecutive_misses"] = 0
                if score > ent.get("best_score", 0):
                    ent["best_score"] = score
                    ent["best_category"] = category
                evidence = ent.get("evidence", [])
                if title and title not in evidence:
                    evidence.append(title)
                    ent["evidence"] = evidence[-5:]
                if url and url not in ent.get("source_urls", []):
                    ent.setdefault("source_urls", []).append(url)
                    ent["source_urls"] = ent["source_urls"][-10:]
                if ent.get("status") == "archived":
                    ent["status"] = "active"
                updated_count += 1
            else:
                entities[key] = {
                    "name": name,
                    "entity_type": "company",
                    "first_seen": today,
                    "last_seen": today,
                    "times_seen": 1,
                    "consecutive_misses": 0,
                    "best_score": score,
                    "best_category": category,
                    "status": "active",
                    "search_terms": [name.lower()],
                    "evidence": [title] if title else [],
                    "source_urls": [url] if url else [],
                }
                new_count += 1

    memory["meta"]["total_runs"] = memory["meta"].get("total_runs", 0) + 1

    return new_count, updated_count


def increment_misses(memory: Dict[str, Any], seen_keys: set):
    """Increment consecutive_misses for active entities not seen this run."""
    for key, ent in memory["entities"].items():
        if ent.get("status") not in ("active", "cold"):
            continue
        if key not in seen_keys:
            ent["consecutive_misses"] = ent.get("consecutive_misses", 0) + 1
            if ent["consecutive_misses"] >= COLD_THRESHOLD_MISSES and ent["status"] == "active":
                ent["status"] = "cold"
            if ent["consecutive_misses"] >= ARCHIVE_THRESHOLD_MISSES:
                ent["status"] = "archived"


def _extract_entity_names(item: Dict[str, Any]) -> List[str]:
    """Extract potential entity (company/org) names from a scored item.

    Uses heuristics: capitalized multi-word sequences, known patterns.
    Not perfect, but cheap (no LLM cost). The meta-agent can refine later.
    """
    names = []
    domain = item.get("discovered_domain", "")
    title = item.get("title", "")

    if domain:
        clean = domain.replace("www.", "").split(".")[0]
        if len(clean) >= 3 and clean not in _SKIP_DOMAINS:
            names.append(clean.capitalize())

    cap_pattern = re.compile(
        r'\b([A-Z][a-z]+(?:\s+[A-Z][a-z]+)+)\b'
    )
    for match in cap_pattern.finditer(title):
        candidate = match.group(1)
        if len(candidate) > 5 and candidate.lower() not in _SKIP_PHRASES:
            names.append(candidate)

    return names[:3]


_SKIP_DOMAINS = {
    "twitter", "x", "linkedin", "reddit", "youtube", "wikipedia",
    "google", "nih", "gov", "nature", "sciencedirect", "wiley",
    "springer", "ieee", "cell", "biorxiv", "medrxiv", "arxiv",
    "nytimes", "ft", "statnews", "fda",
}

_SKIP_PHRASES = {
    "the new", "new york", "united states", "los angeles",
    "clinical trial", "press release", "brain computer",
    "neural interface", "first human", "science news",
}


# ── RECALL ────────────────────────────────────────────────────────────


def get_recall_queries(
    memory: Dict[str, Any],
    max_queries: int = 5,
) -> List[str]:
    """Generate targeted Tavily queries for cold/active entities not seen recently.

    These queries are injected into the Tavily fetch step to actively
    re-search for entities that may have been missed due to retrieval
    stochasticity.
    """
    today = dt.date.today()
    entities = memory.get("entities", {})
    candidates = []

    for key, ent in entities.items():
        if ent.get("status") not in ("active", "cold"):
            continue
        if ent.get("consecutive_misses", 0) < 1:
            continue
        if ent.get("times_seen", 0) < 1:
            continue

        last_seen = ent.get("last_seen", "")
        if last_seen:
            try:
                days_since = (today - dt.date.fromisoformat(last_seen)).days
            except ValueError:
                days_since = 999
        else:
            days_since = 999

        priority = ent.get("best_score", 5) + min(ent.get("times_seen", 1), 5)
        if ent.get("status") == "cold":
            priority += 2

        candidates.append((priority, days_since, key, ent))

    candidates.sort(key=lambda x: (-x[0], -x[1]))

    queries = []
    for _, _, key, ent in candidates[:max_queries]:
        search_terms = ent.get("search_terms", [ent.get("name", key)])
        name = search_terms[0] if search_terms else ent.get("name", key)
        query = f'"{name}" BCI OR "neural interface" OR neurotechnology'
        queries.append(query)

    return queries


def get_seen_entity_keys(scored_items: List[Dict[str, Any]], min_score: int = 6) -> set:
    """Get the set of entity keys seen in this run's scored items."""
    keys = set()
    tavily_items = [
        it for it in scored_items
        if it.get("source_id") == "tavily_wideband"
        and it.get("llm_score", it.get("score", 0)) >= min_score
    ]
    for item in tavily_items:
        names = _extract_entity_names(item)
        for name in names:
            key = _entity_key(name)
            if key and len(key) >= 3:
                keys.add(key)
    return keys


# ── REFLECT ───────────────────────────────────────────────────────────


def get_memory_summary(memory: Dict[str, Any]) -> str:
    """Human-readable summary of discovery memory state."""
    entities = memory.get("entities", {})
    meta = memory.get("meta", {})

    if not entities:
        return "Discovery memory: empty (no entities tracked yet)"

    by_status = {}
    for ent in entities.values():
        status = ent.get("status", "unknown")
        by_status[status] = by_status.get(status, 0) + 1

    total = len(entities)
    active = by_status.get("active", 0)
    cold = by_status.get("cold", 0)
    promoted = by_status.get("promoted", 0)
    archived = by_status.get("archived", 0)

    lines = [
        f"Discovery memory: {total} entities tracked across {meta.get('total_runs', '?')} runs",
        f"  Active: {active} | Cold: {cold} | Promoted: {promoted} | Archived: {archived}",
    ]

    cold_entities = [
        ent for ent in entities.values()
        if ent.get("status") == "cold"
    ]
    if cold_entities:
        cold_names = [e.get("name", "?") for e in cold_entities[:5]]
        lines.append(f"  Cold entities: {', '.join(cold_names)}")

    promotable = [
        ent for ent in entities.values()
        if ent.get("status") == "active"
        and ent.get("times_seen", 0) >= PROMOTION_THRESHOLD_TIMES_SEEN
    ]
    if promotable:
        promo_names = [f"{e.get('name', '?')} (seen {e.get('times_seen', 0)}x)" for e in promotable[:5]]
        lines.append(f"  Promotion candidates: {', '.join(promo_names)}")

    return "\n".join(lines)


def get_promotion_candidates(memory: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Entities eligible for auto-promotion to the company watchlist."""
    entities = memory.get("entities", {})
    candidates = []
    for key, ent in entities.items():
        if (ent.get("status") == "active"
                and ent.get("times_seen", 0) >= PROMOTION_THRESHOLD_TIMES_SEEN
                and ent.get("best_score", 0) >= 7):
            candidates.append({
                "key": key,
                "name": ent.get("name", key),
                "times_seen": ent.get("times_seen", 0),
                "best_score": ent.get("best_score", 0),
                "best_category": ent.get("best_category", ""),
                "first_seen": ent.get("first_seen", ""),
                "evidence": ent.get("evidence", [])[:3],
            })
    return sorted(candidates, key=lambda x: -x["times_seen"])


def mark_promoted(memory: Dict[str, Any], entity_key: str):
    """Mark an entity as promoted (now tracked in config.yaml watchlist)."""
    ent = memory.get("entities", {}).get(entity_key)
    if ent:
        ent["status"] = "promoted"
        ent["promoted_on"] = dt.date.today().isoformat()


# ── BOOTSTRAP ─────────────────────────────────────────────────────────


def bootstrap_from_seen_items(
    seen_items: Dict[str, Dict[str, Any]],
    memory: Dict[str, Any],
    min_score: int = 7,
) -> int:
    """Seed memory from existing seen_items.json (dedup history).

    Looks for high-scoring items and creates memory entries. This allows
    bootstrapping the memory from a cold start without discarding the
    existing baseline.
    """
    today = dt.date.today().isoformat()
    entities = memory["entities"]
    count = 0

    for h, item in seen_items.items():
        score = item.get("score", 0)
        if score < min_score:
            continue
        title = item.get("title", "")
        if not title:
            continue

        cap_pattern = re.compile(r'\b([A-Z][a-z]+(?:\s+[A-Z][a-z]+)+)\b')
        for match in cap_pattern.finditer(title):
            candidate = match.group(1)
            if len(candidate) <= 5 or candidate.lower() in _SKIP_PHRASES:
                continue
            key = _entity_key(candidate)
            if not key or len(key) < 3 or key in entities:
                continue
            entities[key] = {
                "name": candidate,
                "entity_type": "company",
                "first_seen": item.get("first_seen", today),
                "last_seen": item.get("last_seen", today),
                "times_seen": item.get("run_count", 1),
                "consecutive_misses": 0,
                "best_score": score,
                "best_category": item.get("category", "unknown"),
                "status": "active",
                "search_terms": [candidate.lower()],
                "evidence": [title[:120]],
                "source_urls": [],
            }
            count += 1

    return count


def bootstrap_from_discoveries(
    discoveries: List[Dict[str, Any]],
    memory: Dict[str, Any],
) -> int:
    """Seed memory from existing discoveries.yaml entries."""
    today = dt.date.today().isoformat()
    entities = memory["entities"]
    count = 0

    for d in discoveries:
        name = d.get("name", "")
        if not name:
            continue
        key = _entity_key(name)
        if key in entities:
            continue
        entities[key] = {
            "name": name,
            "entity_type": "company",
            "first_seen": d.get("discovered_on", today),
            "last_seen": d.get("discovered_on", today),
            "times_seen": 1,
            "consecutive_misses": 0,
            "best_score": 7,
            "best_category": "unknown",
            "status": "active",
            "search_terms": [name.lower()],
            "evidence": [d.get("evidence", "")[:120]] if d.get("evidence") else [],
            "source_urls": [],
        }
        count += 1

    return count
