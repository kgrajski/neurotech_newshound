"""
Config loader — reads config.yaml + prompts.yaml and provides typed access.

The config file is the single place users edit to customize the agent.
All other modules read from this instead of hardcoding values.
"""
import os
from typing import Any, Dict, List, Optional

import yaml

CONFIG_PATH = os.path.join(os.path.dirname(__file__), "..", "config.yaml")

_config: Optional[Dict[str, Any]] = None
_prompts: Optional[Dict[str, str]] = None


def load_config(path: str = None) -> Dict[str, Any]:
    """Load and cache config from YAML."""
    global _config
    if _config is not None and path is None:
        return _config

    path = path or CONFIG_PATH
    if not os.path.exists(path):
        raise FileNotFoundError(
            f"Config file not found: {path}\n"
            "Copy config.yaml.example to config.yaml and edit it."
        )
    with open(path) as f:
        _config = yaml.safe_load(f)
    return _config


# ── Agent identity ───────────────────────────────────────────────────

def get_agent_name() -> str:
    cfg = load_config()
    return cfg.get("agent", {}).get("name", "NeuroTech NewsHound")


def get_agent_tagline() -> str:
    cfg = load_config()
    return cfg.get("agent", {}).get("tagline", "")


def get_agent_domain() -> str:
    cfg = load_config()
    return cfg.get("agent", {}).get("domain", "")


# ── Defaults ─────────────────────────────────────────────────────────

def get_defaults() -> Dict[str, Any]:
    cfg = load_config()
    return cfg.get("defaults", {})


def get_default_model() -> str:
    return get_defaults().get("model", "gpt-4o-mini")


def get_default_reviewer() -> str:
    return get_defaults().get("reviewer_model", "")


def get_default_days() -> int:
    return get_defaults().get("days", 7)


def get_max_items() -> int:
    return get_defaults().get("max_items_per_source", 40)


def get_max_sources() -> int:
    return get_defaults().get("max_sources", 40)


# ── Sources ──────────────────────────────────────────────────────────

def get_sources() -> List[Dict[str, Any]]:
    """Get all source definitions from config."""
    cfg = load_config()
    return cfg.get("sources", [])


def get_enabled_sources_from_config(source_type: str = None) -> List[Dict[str, Any]]:
    """Get enabled sources, optionally filtered by type."""
    sources = [s for s in get_sources() if s.get("enabled", True)]
    if source_type:
        sources = [s for s in sources if s.get("type") == source_type]
    return sources


# ── Company Watchlist ────────────────────────────────────────────────

def get_company_watchlist() -> List[Dict[str, Any]]:
    """Get the company watchlist from config."""
    cfg = load_config()
    return [c for c in cfg.get("company_watchlist", []) if c.get("enabled", True)]


def get_watchlist_company_names() -> List[str]:
    """Get just the names of tracked companies (for dedup against discoveries)."""
    return [c["name"] for c in get_company_watchlist()]


def get_watchlist_tavily_queries() -> List[str]:
    """Auto-generate Tavily queries from the company watchlist.

    Groups companies into batches of 4-5 per query to stay within
    reasonable query lengths while covering all tracked entities.
    """
    companies = get_company_watchlist()
    if not companies:
        return []

    all_aliases = []
    for company in companies:
        aliases = company.get("aliases", [company["name"].lower()])
        all_aliases.extend(aliases)

    queries = []
    batch_size = 5
    for i in range(0, len(all_aliases), batch_size):
        batch = all_aliases[i:i + batch_size]
        terms = " OR ".join(f'"{a}"' for a in batch)
        queries.append(f'{terms} BCI OR "neural interface" OR "brain implant"')

    return queries


def get_watchlist_rss_feeds() -> List[Dict[str, Any]]:
    """Extract RSS feeds (Substack URLs) from watchlist entries.

    Returns source dicts compatible with the RSS fetcher, so watchlist
    Substacks are automatically included without duplicating them in
    the sources list.
    """
    companies = get_company_watchlist()
    existing_urls = {s.get("url", "") for s in get_sources()}
    feeds = []
    for company in companies:
        substack = company.get("substack", "")
        if substack and substack not in existing_urls:
            feeds.append({
                "id": f"watchlist_{company['name'].lower().replace(' ', '_')}_substack",
                "name": f"{company['name']} (Substack, via watchlist)",
                "category": "press",
                "type": "rss",
                "url": substack,
                "enabled": True,
            })
    return feeds


# ── Curated Industry Sources ────────────────────────────────────────

def get_curated_industry_queries() -> List[str]:
    """Get Tavily queries from curated industry sources (e.g. Neurofounders)."""
    cfg = load_config()
    sources = cfg.get("curated_industry_sources", [])
    return [
        s["tavily_query"]
        for s in sources
        if s.get("enabled", True) and s.get("tavily_query")
    ]


# ── Combined Tavily Queries ─────────────────────────────────────────

def get_all_tavily_queries() -> List[str]:
    """Merge static queries + watchlist-generated + curated industry queries."""
    static = get_tavily_queries()
    watchlist = get_watchlist_tavily_queries()
    curated = get_curated_industry_queries()
    return static + watchlist + curated


def get_tavily_queries() -> List[str]:
    """Get the static Tavily queries from config."""
    cfg = load_config()
    return cfg.get("tavily_queries", [])


# ── Prompts ──────────────────────────────────────────────────────────

def load_prompts() -> Dict[str, str]:
    """Load prompts from prompts.yaml (same directory as config.yaml)."""
    global _prompts
    if _prompts is not None:
        return _prompts

    cfg = load_config()
    prompts_file = cfg.get("prompts_file", "prompts.yaml")

    config_dir = os.path.dirname(os.path.abspath(CONFIG_PATH))
    prompts_path = os.path.join(config_dir, prompts_file)

    if os.path.exists(prompts_path):
        with open(prompts_path) as f:
            _prompts = yaml.safe_load(f) or {}
    else:
        _prompts = {}
    return _prompts


def get_prompt(name: str, fallback: str = "") -> str:
    """Get a named prompt template. Returns fallback if not found.

    This allows nodes to define a hardcoded default but prefer the
    external prompts.yaml version when available.
    """
    prompts = load_prompts()
    return prompts.get(name, fallback)


def reload_config():
    """Force reload of config and prompts (for testing / hot-reload)."""
    global _config, _prompts
    _config = None
    _prompts = None


# ── MLflow ───────────────────────────────────────────────────────────

def get_mlflow_config() -> Dict[str, Any]:
    cfg = load_config()
    return cfg.get("mlflow", {"enabled": True, "experiment_name": "neurotech-newshound"})
