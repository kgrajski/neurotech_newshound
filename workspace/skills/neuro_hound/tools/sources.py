"""
Source registry — tracks runtime stats for all data sources.

Sources are defined in config.yaml (user-editable).
This module manages the runtime stats overlay (sources.json):
    - Per-source yield stats (fetched, in_scope, last_hit)
    - Discovered source tracking (from Tavily)
    - Cold-source pruning for discovered sources
"""
import datetime as dt
import json
import os
from typing import Any, Dict, List, Optional

from tools.config import get_sources, get_max_sources, get_enabled_sources_from_config

SOURCES_FILE = os.path.join(os.path.dirname(__file__), "..", "sources.json")


def _empty_stats() -> Dict[str, Any]:
    return {
        "runs": 0,
        "total_fetched": 0,
        "in_scope_count": 0,
        "high_score_count": 0,
        "last_hit_date": None,
        "last_run_date": None,
    }


def load_sources(path: Optional[str] = None) -> Dict[str, Any]:
    """
    Load source registry: config.yaml sources + runtime stats overlay.

    On first run, initializes stats for all configured sources.
    On subsequent runs, merges any new sources from config.yaml.
    """
    path = path or SOURCES_FILE
    config_sources = get_sources()

    if os.path.exists(path):
        with open(path) as f:
            registry = json.load(f)
        # Merge in any new sources from config
        existing_ids = {s["id"] for s in registry.get("sources", [])}
        for cs in config_sources:
            if cs["id"] not in existing_ids:
                registry["sources"].append({**cs, "curated": True, "stats": _empty_stats()})
        # Update source definitions from config (URL changes, etc.)
        config_by_id = {s["id"]: s for s in config_sources}
        for s in registry["sources"]:
            if s["id"] in config_by_id:
                cfg = config_by_id[s["id"]]
                s["name"] = cfg.get("name", s.get("name", ""))
                s["url"] = cfg.get("url", s.get("url", ""))
                s["enabled"] = cfg.get("enabled", s.get("enabled", True))
                s["category"] = cfg.get("category", s.get("category", ""))
                s["type"] = cfg.get("type", s.get("type", ""))
        return registry

    # First run — initialize from config
    sources = []
    for cs in config_sources:
        sources.append({**cs, "curated": True, "stats": _empty_stats()})

    registry = {
        "max_sources": get_max_sources(),
        "created": dt.date.today().isoformat(),
        "last_pruned": None,
        "sources": sources,
    }
    save_sources(registry, path)
    return registry


def save_sources(registry: Dict[str, Any], path: Optional[str] = None):
    """Persist registry to JSON."""
    path = path or SOURCES_FILE
    with open(path, "w") as f:
        json.dump(registry, f, indent=2, default=str)


def get_enabled_sources(registry: Dict[str, Any], source_type: Optional[str] = None) -> List[Dict[str, Any]]:
    """Get enabled sources, optionally filtered by type."""
    sources = [s for s in registry["sources"] if s.get("enabled", True)]
    if source_type:
        sources = [s for s in sources if s.get("type") == source_type]
    return sources


def update_source_stats(
    registry: Dict[str, Any],
    source_id: str,
    fetched: int = 0,
    in_scope: int = 0,
    high_score: int = 0,
):
    """Update stats for a source after a run."""
    today = dt.date.today().isoformat()
    for s in registry["sources"]:
        if s["id"] == source_id:
            stats = s.setdefault("stats", _empty_stats())
            stats["runs"] = stats.get("runs", 0) + 1
            stats["total_fetched"] = stats.get("total_fetched", 0) + fetched
            stats["in_scope_count"] = stats.get("in_scope_count", 0) + in_scope
            stats["high_score_count"] = stats.get("high_score_count", 0) + high_score
            stats["last_run_date"] = today
            if in_scope > 0:
                stats["last_hit_date"] = today
            break


def add_discovered_source(
    registry: Dict[str, Any],
    source_id: str,
    name: str,
    url: str,
    category: str = "discovered",
    source_type: str = "rss",
) -> bool:
    """Add a Tavily-discovered source. Returns True if added."""
    existing_ids = {s["id"] for s in registry["sources"]}
    if source_id in existing_ids:
        return False

    enabled_count = len([s for s in registry["sources"] if s.get("enabled", True)])
    if enabled_count >= registry.get("max_sources", get_max_sources()):
        pruned = prune_cold_sources(registry)
        enabled_count -= pruned
        if enabled_count >= registry.get("max_sources", get_max_sources()):
            return False

    registry["sources"].append({
        "id": source_id,
        "name": name,
        "category": category,
        "type": source_type,
        "url": url,
        "enabled": True,
        "curated": False,
        "discovered_date": dt.date.today().isoformat(),
        "stats": _empty_stats(),
    })
    return True


def prune_cold_sources(registry: Dict[str, Any], cold_days: int = 30) -> int:
    """Disable discovered sources with no in-scope hits for cold_days."""
    cutoff = (dt.date.today() - dt.timedelta(days=cold_days)).isoformat()
    pruned = 0
    for s in registry["sources"]:
        if s.get("curated", False):
            continue
        if not s.get("enabled", True):
            continue
        last_hit = s.get("stats", {}).get("last_hit_date")
        if last_hit is None or last_hit < cutoff:
            s["enabled"] = False
            pruned += 1
    if pruned:
        registry["last_pruned"] = dt.date.today().isoformat()
    return pruned


def get_source_summary(registry: Dict[str, Any]) -> str:
    """Human-readable summary of source registry."""
    enabled = [s for s in registry["sources"] if s.get("enabled", True)]
    by_cat = {}
    for s in enabled:
        cat = s.get("category", "other")
        by_cat.setdefault(cat, []).append(s["name"])
    lines = [f"Sources: {len(enabled)} enabled / {len(registry['sources'])} total"]
    for cat, names in sorted(by_cat.items()):
        lines.append(f"  {cat}: {', '.join(names)}")
    return "\n".join(lines)
