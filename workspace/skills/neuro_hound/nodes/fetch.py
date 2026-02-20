"""
Fetch nodes — pull items from all sources (no LLM, no cost except Tavily).

Sources are driven by the registry (sources.json). Each fetch node handles
a category of sources and updates per-source stats after fetching.
"""
from state import HoundState
from tools.pubmed import fetch_pubmed_items
from tools.rss import fetch_rss_sources
from tools.sources import (
    load_sources, save_sources, get_enabled_sources,
    update_source_stats, get_source_summary,
)
from tools.scoring import is_in_scope


def fetch_pubmed(state: HoundState) -> HoundState:
    """Fetch recent items from PubMed (API, not RSS)."""
    print("  Fetching PubMed...")
    registry = state.get("_registry") or load_sources()
    try:
        items = fetch_pubmed_items(state["days"], state["max_items"])
        for it in items:
            it["source_id"] = "pubmed"
            it["source_category"] = "database"
        state["raw_items"].extend(items)
        in_scope = sum(1 for it in items if is_in_scope(it.get("title", ""), it.get("summary", "")))
        update_source_stats(registry, "pubmed", fetched=len(items), in_scope=in_scope)
        print(f"  [ok] PubMed: {len(items)} items ({in_scope} in-scope)")
    except Exception as e:
        state["errors"].append(f"PubMed: {e}")
        print(f"  [warn] PubMed: {e}")
    state["_registry"] = registry
    return state


def fetch_rss(state: HoundState) -> HoundState:
    """Fetch from all enabled RSS sources + watchlist Substack feeds."""
    print("  Fetching RSS sources...")
    registry = state.get("_registry") or load_sources()
    rss_sources = get_enabled_sources(registry, source_type="rss")

    from tools.config import get_watchlist_rss_feeds
    watchlist_feeds = get_watchlist_rss_feeds()
    if watchlist_feeds:
        existing_ids = {s.get("id") for s in rss_sources}
        new_feeds = [f for f in watchlist_feeds if f["id"] not in existing_ids]
        if new_feeds:
            rss_sources.extend(new_feeds)
            print(f"  +{len(new_feeds)} RSS feeds from company watchlist")

    if not rss_sources:
        print("  [warn] No RSS sources enabled")
        return state

    # Group by category for organized output
    by_cat = {}
    for s in rss_sources:
        cat = s.get("category", "other")
        by_cat.setdefault(cat, []).append(s)

    total_fetched = 0
    for cat, sources in sorted(by_cat.items()):
        print(f"  [{cat}]")
        results = fetch_rss_sources(sources, state["max_items"])
        for sid, items in results.items():
            if items:
                state["raw_items"].extend(items)
                total_fetched += len(items)
                in_scope = sum(
                    1 for it in items
                    if is_in_scope(it.get("title", ""), it.get("summary", ""))
                )
                update_source_stats(registry, sid, fetched=len(items), in_scope=in_scope)

    print(f"  [ok] RSS total: {total_fetched} items from {len(rss_sources)} feeds")
    state["_registry"] = registry
    return state


def fetch_tavily(state: HoundState) -> HoundState:
    """Wideband Tavily search for items not covered by RSS/API sources."""
    registry = state.get("_registry") or load_sources()
    tavily_sources = get_enabled_sources(registry, source_type="tavily")

    if not tavily_sources:
        print("  [skip] Tavily not enabled")
        return state

    print("  Fetching Tavily wideband search...")
    try:
        from tools.tavily import tavily_search
        items = tavily_search(days=state["days"])
        state["raw_items"].extend(items)
        in_scope = sum(
            1 for it in items
            if is_in_scope(it.get("title", ""), it.get("summary", ""))
        )
        update_source_stats(
            registry, "tavily_wideband",
            fetched=len(items), in_scope=in_scope,
        )
        print(f"  [ok] Tavily: {len(items)} items ({in_scope} in-scope)")
    except ImportError:
        print("  [skip] tavily-python not installed — skipping wideband search")
    except ValueError as e:
        print(f"  [skip] Tavily: {e}")
    except Exception as e:
        state["errors"].append(f"Tavily: {e}")
        print(f"  [warn] Tavily: {e}")

    state["_registry"] = registry
    return state


def save_registry(state: HoundState) -> HoundState:
    """Persist updated source registry after all fetches complete."""
    registry = state.get("_registry")
    if registry:
        save_sources(registry)
        print(f"  {get_source_summary(registry)}")
    return state
