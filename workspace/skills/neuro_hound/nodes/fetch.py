"""Fetch nodes — pull items from PubMed and RSS feeds (no LLM, no cost)."""
from state import HoundState
from tools.pubmed import fetch_pubmed_items
from tools.rss import fetch_rss_items


def fetch_pubmed(state: HoundState) -> HoundState:
    """Fetch recent items from PubMed."""
    print("  Fetching PubMed...")
    try:
        items = fetch_pubmed_items(state["days"], state["max_items"])
        state["raw_items"].extend(items)
        print(f"  [ok] PubMed: {len(items)} items")
    except Exception as e:
        state["errors"].append(f"PubMed: {e}")
        print(f"  [warn] PubMed: {e}")
    return state


def fetch_rss(state: HoundState) -> HoundState:
    """Fetch recent items from bioRxiv/medRxiv RSS feeds."""
    print("  Fetching RSS feeds...")
    items = fetch_rss_items(state["max_items"])
    state["raw_items"].extend(items)
    return state
