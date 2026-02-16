"""
Tavily wideband search — discover neurotech items beyond curated sources.

Runs broad queries to catch items from VC announcements, press releases,
FDA notices, company blogs, and academic sources not in the RSS feeds.

Also tracks new domains: if a domain yields high-scoring items consistently,
propose it as a new source for the registry.
"""
import os
import re
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse

from tools.config import get_tavily_queries

DEFAULT_QUERIES = [
    '"brain-computer interface" OR "neural implant" clinical trial',
    'neuralink OR synchron OR paradromics OR "blackrock neurotech" OR "precision neuroscience"',
    '"intracranial EEG" OR ECoG OR sEEG neural recording human',
    'FDA "neural device" OR "brain implant" approval OR clearance',
    'BCI funding OR investment "neural interface"',
]


def _get_client():
    """Lazy-load Tavily client."""
    try:
        from tavily import TavilyClient
    except ImportError:
        raise ImportError(
            "tavily-python not installed. Run: pip install tavily-python"
        )
    api_key = os.getenv("TAVILY_API_KEY", "")
    if not api_key:
        raise ValueError("TAVILY_API_KEY not set in environment")
    return TavilyClient(api_key=api_key)


def tavily_search(
    queries: Optional[List[str]] = None,
    max_results_per_query: int = 5,
    days: int = 7,
) -> List[Dict[str, Any]]:
    """
    Run Tavily searches and return deduplicated results.

    Each result becomes an item dict compatible with the pipeline.
    """
    queries = queries or get_tavily_queries() or DEFAULT_QUERIES
    client = _get_client()

    seen_urls = set()
    all_items = []

    for query in queries:
        try:
            response = client.search(
                query=query,
                max_results=max_results_per_query,
                search_depth="basic",
                include_answer=False,
                days=days,
            )
            results = response.get("results", [])
            for r in results:
                url = r.get("url", "")
                if url in seen_urls:
                    continue
                seen_urls.add(url)

                domain = urlparse(url).netloc if url else ""
                all_items.append({
                    "title": r.get("title", ""),
                    "url": url,
                    "summary": r.get("content", "")[:500],
                    "meta": domain,
                    "source": f"Tavily ({domain})",
                    "source_id": "tavily_wideband",
                    "source_category": "search",
                    "discovered_domain": domain,
                })
        except Exception as e:
            print(f"    [warn] Tavily query failed: {e}")

    return all_items


def extract_discoverable_domains(
    scored_items: List[Dict[str, Any]],
    min_score: int = 7,
    min_hits: int = 2,
) -> List[Dict[str, str]]:
    """
    Analyze scored Tavily results to find domains worth adding as sources.

    Returns list of {domain, name, reason} for domains that yielded
    multiple high-scoring items.
    """
    domain_hits: Dict[str, List[Dict]] = {}

    for item in scored_items:
        if item.get("source_id") != "tavily_wideband":
            continue
        score = item.get("llm_score", item.get("score", 0))
        if score < min_score:
            continue
        domain = item.get("discovered_domain", "")
        if not domain:
            continue
        # Skip major sites (too broad to be useful as dedicated RSS sources)
        skip_domains = {"twitter.com", "x.com", "linkedin.com", "reddit.com",
                        "youtube.com", "wikipedia.org", "google.com"}
        if any(sd in domain for sd in skip_domains):
            continue
        domain_hits.setdefault(domain, []).append(item)

    discoveries = []
    for domain, items in domain_hits.items():
        if len(items) >= min_hits:
            titles = [it.get("title", "")[:50] for it in items[:3]]
            discoveries.append({
                "domain": domain,
                "name": domain.replace("www.", ""),
                "hit_count": len(items),
                "reason": f"Yielded {len(items)} high-scoring items: {'; '.join(titles)}",
            })

    return sorted(discoveries, key=lambda x: -x["hit_count"])
