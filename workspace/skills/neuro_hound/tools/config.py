"""
Config loader — reads config.yaml and provides typed access.

The config file is the single place users edit to customize the agent.
All other modules read from this instead of hardcoding values.
"""
import os
from typing import Any, Dict, List, Optional

import yaml

CONFIG_PATH = os.path.join(os.path.dirname(__file__), "..", "config.yaml")

_config: Optional[Dict[str, Any]] = None


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


def get_agent_name() -> str:
    cfg = load_config()
    return cfg.get("agent", {}).get("name", "NeuroTech NewsHound")


def get_agent_tagline() -> str:
    cfg = load_config()
    return cfg.get("agent", {}).get("tagline", "")


def get_agent_domain() -> str:
    cfg = load_config()
    return cfg.get("agent", {}).get("domain", "")


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


def get_tavily_queries() -> List[str]:
    cfg = load_config()
    return cfg.get("tavily_queries", [])


def get_mlflow_config() -> Dict[str, Any]:
    cfg = load_config()
    return cfg.get("mlflow", {"enabled": True, "experiment_name": "neurotech-newshound"})
