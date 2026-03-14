"""
Tavily wideband search — discover neurotech items beyond curated sources.

Runs broad queries to catch items from VC announcements, press releases,
FDA notices, company blogs, and academic sources not in the RSS feeds.

Query sources (merged automatically):
  1. Static queries from config.yaml tavily_queries
  2. Auto-generated queries from company_watchlist entries
  3. Site-scoped queries from curated_industry_sources (e.g. Neurofounders)

Ensemble retrieval: each query is expanded into multiple variants
(synonym-swapped, restructured) and run independently. The union of
results is returned, reducing the impact of Tavily's non-deterministic
result ordering. See: "Generative Query Reformulation Using Ensemble
Prompting" (arXiv:2405.17658) — ensemble strategies improve recall by
up to 18%.

Also tracks new domains and companies: if a domain yields high-scoring
items consistently, propose it as a new source for the registry.
"""
import os
import random
import re
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse

from tools.config import get_all_tavily_queries, get_tavily_queries

DEFAULT_QUERIES = [
    '"brain-computer interface" OR "neural implant" clinical trial',
    '"intracranial EEG" OR ECoG OR sEEG neural recording human',
    'FDA "neural device" OR "brain implant" approval OR clearance',
    'BCI funding OR investment "neural interface"',
]

# ── Ensemble query variant templates ─────────────────────────────────
# Each base query is expanded by substituting domain-specific synonyms
# and restructuring. This is template-based (no LLM cost) and covers
# the most common terminology variation in the neurotech space.

_SYNONYM_MAP = {
    '"brain-computer interface"': [
        '"brain-computer interface"',
        '"brain-machine interface"',
        '"neural interface"',
    ],
    '"neural implant"': [
        '"neural implant"',
        '"brain implant"',
        '"neural prosthesis"',
        '"neuroprosthetic"',
    ],
    'BCI': ['BCI', '"brain-computer interface"'],
    '"neural interface"': ['"neural interface"', '"brain-machine interface"'],
    '"neural device"': ['"neural device"', '"neural implant"', '"neurostimulation device"'],
    'clinical trial': ['clinical trial', 'first-in-human', 'FDA trial'],
    'funding OR investment': ['funding OR investment', 'venture capital OR Series', 'raised OR financing'],
    'approval OR clearance': ['approval OR clearance', 'breakthrough device OR 510k', 'De Novo OR IDE'],
}


def _generate_variants(query: str, max_variants: int = 2) -> List[str]:
    """Generate query variants via synonym substitution.

    Returns the original query plus up to max_variants rewrites.
    Substitution is deterministic per query (seeded by query hash)
    but covers different terminology each run when combined with
    the shuffled synonym lists.
    """
    variants = [query]

    applicable = [
        (phrase, syns)
        for phrase, syns in _SYNONYM_MAP.items()
        if phrase.lower() in query.lower()
    ]

    if not applicable:
        return variants

    rng = random.Random(hash(query) & 0xFFFFFFFF)

    for _ in range(max_variants):
        rewritten = query
        for phrase, syns in applicable:
            alternatives = [s for s in syns if s.lower() != phrase.lower()]
            if alternatives:
                replacement = rng.choice(alternatives)
                rewritten = re.sub(re.escape(phrase), replacement, rewritten, count=1, flags=re.IGNORECASE)
        if rewritten != query and rewritten not in variants:
            variants.append(rewritten)

    return variants


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


def _run_single_query(
    client, query: str, max_results: int, days: int,
    seen_urls: set, all_items: list,
) -> int:
    """Execute one Tavily query, append new items, return count of new items."""
    try:
        response = client.search(
            query=query,
            max_results=max_results,
            search_depth="basic",
            include_answer=False,
            days=days,
        )
        results = response.get("results", [])
        new_count = 0
        for r in results:
            url = r.get("url", "")
            if url in seen_urls:
                continue
            seen_urls.add(url)
            new_count += 1

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
        return new_count
    except Exception as e:
        print(f"      [warn] query failed: {e}")
        return 0


def tavily_search(
    queries: Optional[List[str]] = None,
    max_results_per_query: int = 5,
    days: int = 7,
    ensemble_variants: int = 2,
    recall_queries: Optional[List[str]] = None,
) -> List[Dict[str, Any]]:
    """
    Run Tavily searches with ensemble retrieval and return deduplicated results.

    Each base query is expanded into 1 + ensemble_variants queries via
    synonym substitution. All variants are searched independently and
    results are unioned, reducing the impact of non-deterministic ordering.

    Args:
        queries: Base queries (defaults to config-driven merged set)
        max_results_per_query: Max results per individual API call
        days: Lookback window in days
        ensemble_variants: Number of synonym-swapped variants per base query
            (0 = no ensemble, just run originals; 2 = original + 2 variants)
        recall_queries: Memory-informed queries for cold/active entities
            (from discovery_memory.json). These are run without ensemble
            expansion since they are already targeted.
    """
    queries = queries or get_all_tavily_queries() or DEFAULT_QUERIES
    client = _get_client()

    seen_urls: set = set()
    all_items: list = []

    if ensemble_variants > 0:
        total_base = len(queries)
        expanded = []
        for q in queries:
            expanded.extend(_generate_variants(q, max_variants=ensemble_variants))
        expanded = list(dict.fromkeys(expanded))
        print(f"    Ensemble retrieval: {total_base} base queries → {len(expanded)} total (variants={ensemble_variants})")
        queries = expanded
    else:
        print(f"    Running {len(queries)} Tavily queries (no ensemble)...")

    # Append recall queries (no ensemble expansion — already targeted)
    if recall_queries:
        queries = list(queries) + recall_queries
        print(f"    + {len(recall_queries)} memory recall queries appended")

    for i, query in enumerate(queries):
        new_count = _run_single_query(client, query, max_results_per_query, days, seen_urls, all_items)
        if new_count > 0:
            print(f"    [{i+1}/{len(queries)}] +{new_count} items: {query[:60]}...")

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


def discover_companies(
    scored_items: List[Dict[str, Any]],
    existing_companies: List[str],
    llm_func=None,
    min_score: int = 6,
) -> List[Dict[str, Any]]:
    """
    Use LLM to extract new company names from high-scoring Tavily results.

    This is the adaptive/self-updating element of the watchlist: each run
    surfaces companies that appear in the news but aren't yet tracked.

    Args:
        scored_items: All scored items from the pipeline
        existing_companies: Names already in the watchlist
        llm_func: Callable(prompt) -> str for LLM invocation
        min_score: Minimum score to consider for discovery

    Returns:
        List of discovered company dicts with name, domain, evidence, confidence
    """
    tavily_items = [
        item for item in scored_items
        if item.get("source_id") == "tavily_wideband"
        and item.get("llm_score", item.get("score", 0)) >= min_score
    ]

    if not tavily_items or not llm_func:
        return []

    items_text = "\n".join(
        f"- [{it.get('llm_score', '?')}] {it.get('title', '')[:100]} "
        f"({it.get('discovered_domain', '')}): {it.get('assessment', '')[:150]}"
        for it in tavily_items[:20]
    )

    from tools.config import get_prompt
    prompt_template = get_prompt("discover_companies", "")
    if not prompt_template:
        return []

    prompt = prompt_template.format(
        items_text=items_text,
        existing_companies=", ".join(existing_companies),
        domain="implantable BCIs, ECoG/sEEG, microstimulation, enabling materials",
    )

    try:
        from tools.llm import parse_json
        content = llm_func(prompt)
        result = parse_json(content)
        return result.get("discovered", [])
    except Exception as e:
        print(f"    [warn] Company discovery failed: {e}")
        return []
