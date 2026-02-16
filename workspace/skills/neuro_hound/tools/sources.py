"""
Source registry — tracks all data sources (curated + discovered).

Persists to sources.json alongside this file. Tracks per-source yield
statistics so we can prioritize high-value sources and prune cold ones.

Design:
    - Curated sources are locked (cannot be auto-pruned)
    - Discovered sources (from Tavily) can be pruned after 30 days of silence
    - Total sources capped at MAX_SOURCES (default 40)
    - Stats updated after each run
"""
import datetime as dt
import json
import os
from typing import Any, Dict, List, Optional

SOURCES_FILE = os.path.join(os.path.dirname(__file__), "..", "sources.json")
MAX_SOURCES = 40


# ── Default curated sources ────────────────────────────────────────────

DEFAULT_SOURCES: List[Dict[str, Any]] = [
    # --- Core databases (API-based) ---
    {
        "id": "pubmed",
        "name": "PubMed",
        "category": "database",
        "type": "api",
        "enabled": True,
        "curated": True,
    },

    # --- Preprint servers (RSS) ---
    {
        "id": "biorxiv_neuro",
        "name": "bioRxiv (neuroscience)",
        "category": "preprint",
        "type": "rss",
        "url": "https://connect.biorxiv.org/biorxiv_xml.php?subject=neuroscience",
        "enabled": True,
        "curated": True,
    },
    {
        "id": "medrxiv",
        "name": "medRxiv",
        "category": "preprint",
        "type": "rss",
        "url": "https://connect.medrxiv.org/medrxiv_xml.php",
        "enabled": True,
        "curated": True,
    },
    {
        "id": "arxiv_qbio_nc",
        "name": "arXiv q-bio.NC",
        "category": "preprint",
        "type": "rss",
        "url": "https://rss.arxiv.org/rss/q-bio.NC",
        "enabled": True,
        "curated": True,
    },

    # --- Peer-reviewed journals (RSS/Atom) ---
    {
        "id": "nature_neuro",
        "name": "Nature Neuroscience",
        "category": "journal",
        "type": "rss",
        "url": "https://www.nature.com/neuro.rss",
        "enabled": True,
        "curated": True,
    },
    {
        "id": "nature_bme",
        "name": "Nature Biomedical Engineering",
        "category": "journal",
        "type": "rss",
        "url": "https://www.nature.com/natbiomedeng.rss",
        "enabled": True,
        "curated": True,
    },
    {
        "id": "jne",
        "name": "Journal of Neural Engineering",
        "category": "journal",
        "type": "rss",
        "url": "https://iopscience.iop.org/journal/rss/1741-2552",
        "enabled": True,
        "curated": True,
    },
    {
        "id": "neuron",
        "name": "Neuron",
        "category": "journal",
        "type": "rss",
        "url": "https://www.cell.com/neuron/inpress.rss",
        "enabled": True,
        "curated": True,
    },
    {
        "id": "sci_robotics",
        "name": "Science Robotics",
        "category": "journal",
        "type": "rss",
        "url": "https://www.science.org/action/showFeed?type=etoc&feed=rss&jc=scirobotics",
        "enabled": True,
        "curated": True,
    },

    # --- Regulatory (RSS) ---
    {
        "id": "fda_medwatch",
        "name": "FDA MedWatch Safety",
        "category": "regulatory",
        "type": "rss",
        "url": "http://www.fda.gov/AboutFDA/ContactFDA/StayInformed/RSSFeeds/MedWatch/rss.xml",
        "enabled": True,
        "curated": True,
    },

    # --- General press (RSS — headlines + summaries, paywalled body) ---
    {
        "id": "nyt_science",
        "name": "NYT Science",
        "category": "press",
        "type": "rss",
        "url": "https://rss.nytimes.com/services/xml/rss/nyt/Science.xml",
        "enabled": True,
        "curated": True,
    },
    {
        "id": "nyt_health",
        "name": "NYT Health",
        "category": "press",
        "type": "rss",
        "url": "https://rss.nytimes.com/services/xml/rss/nyt/Health.xml",
        "enabled": True,
        "curated": True,
    },
    {
        "id": "ft_tech",
        "name": "FT Technology",
        "category": "press",
        "type": "rss",
        "url": "https://www.ft.com/technology?format=rss",
        "enabled": True,
        "curated": True,
    },
    {
        "id": "stat_news",
        "name": "STAT News",
        "category": "press",
        "type": "rss",
        "url": "https://www.statnews.com/feed/",
        "enabled": True,
        "curated": True,
    },

    # --- Tavily wideband search ---
    {
        "id": "tavily_wideband",
        "name": "Tavily Wideband Search",
        "category": "search",
        "type": "tavily",
        "enabled": True,
        "curated": True,
    },
]


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
    """Load source registry from JSON, or create default."""
    path = path or SOURCES_FILE
    if os.path.exists(path):
        with open(path) as f:
            registry = json.load(f)
        # Ensure all defaults are present (new curated sources added in code)
        existing_ids = {s["id"] for s in registry.get("sources", [])}
        for default in DEFAULT_SOURCES:
            if default["id"] not in existing_ids:
                default["stats"] = _empty_stats()
                registry["sources"].append(default)
        return registry

    # First run — initialize from defaults
    sources = []
    for s in DEFAULT_SOURCES:
        entry = {**s, "stats": _empty_stats()}
        sources.append(entry)

    registry = {
        "max_sources": MAX_SOURCES,
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
    """
    Add a Tavily-discovered source to the registry.
    Returns True if added, False if at cap or already exists.
    """
    existing_ids = {s["id"] for s in registry["sources"]}
    if source_id in existing_ids:
        return False

    enabled_count = len([s for s in registry["sources"] if s.get("enabled", True)])
    if enabled_count >= registry.get("max_sources", MAX_SOURCES):
        # Try pruning first
        pruned = prune_cold_sources(registry)
        enabled_count -= pruned
        if enabled_count >= registry.get("max_sources", MAX_SOURCES):
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
    """
    Disable discovered sources that haven't yielded in-scope items
    for cold_days. Curated sources are never pruned.
    Returns count of pruned sources.
    """
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
