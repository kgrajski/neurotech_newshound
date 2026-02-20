"""arXiv API fetcher for historical backfill.

Uses the arXiv API (Atom feed):
    http://export.arxiv.org/api/query?search_query=...&start=0&max_results=100

Rate limiting: arXiv asks for ≤1 request per 3 seconds for bulk queries.
"""
import time
import urllib.parse
import xml.etree.ElementTree as ET
from typing import Any, Dict, List

from tools.http import http_get, safe_text

BASE_URL = "http://export.arxiv.org/api/query"
ATOM_NS = "http://www.w3.org/2005/Atom"
ARXIV_NS = "http://arxiv.org/schemas/atom"
PAGE_SIZE = 100
RATE_LIMIT_SLEEP = 3.5  # arXiv is stricter than bioRxiv

ARXIV_CATEGORIES = [
    "q-bio.NC",   # Neurons and Cognition
    "cs.HC",      # Human-Computer Interaction
    "eess.SP",    # Signal Processing
    "cs.NE",      # Neural and Evolutionary Computing
    "cs.AI",      # Artificial Intelligence (for BCI + ML papers)
]

SEARCH_TERMS = [
    '"brain-computer interface"',
    '"neural interface"',
    '"neural implant"',
    '"electrocorticography"',
    '"intracortical"',
    '"neuroprosthesis"',
    '"speech decoding" AND brain',
    '"motor decoding" AND brain',
    '"brain-machine interface"',
]


def _build_arxiv_query() -> str:
    """Build an arXiv search query combining categories and terms."""
    cat_clause = " OR ".join(f"cat:{c}" for c in ARXIV_CATEGORIES)
    term_clause = " OR ".join(f"all:{t}" for t in SEARCH_TERMS)
    return f"({cat_clause}) AND ({term_clause})"


def _parse_arxiv_response(xml_bytes: bytes) -> List[Dict[str, Any]]:
    """Parse arXiv Atom API response into item dicts."""
    root = ET.fromstring(xml_bytes)
    items = []

    for entry in root.findall(f"{{{ATOM_NS}}}entry"):
        title = safe_text(entry.findtext(f"{{{ATOM_NS}}}title") or "")
        summary = safe_text(entry.findtext(f"{{{ATOM_NS}}}summary") or "")

        link = ""
        for link_el in entry.findall(f"{{{ATOM_NS}}}link"):
            if link_el.attrib.get("type") == "text/html":
                link = link_el.attrib.get("href", "")
                break
        if not link:
            link_el = entry.find(f"{{{ATOM_NS}}}link")
            if link_el is not None:
                link = link_el.attrib.get("href", "")

        published = safe_text(entry.findtext(f"{{{ATOM_NS}}}published") or "")
        arxiv_id = safe_text(entry.findtext(f"{{{ATOM_NS}}}id") or "")

        categories = []
        for cat_el in entry.findall(f"{{{ARXIV_NS}}}primary_category"):
            categories.append(cat_el.attrib.get("term", ""))
        for cat_el in entry.findall(f"{{{ATOM_NS}}}category"):
            categories.append(cat_el.attrib.get("term", ""))

        if title and title != "Error":
            items.append({
                "source": "arXiv",
                "source_id": "arxiv",
                "source_category": "preprint",
                "title": title,
                "summary": summary[:1000],
                "url": link or arxiv_id,
                "meta": safe_text(f"{' '.join(set(categories))} {published}"),
            })

    return items


def fetch_arxiv_page(query: str, start: int = 0) -> List[Dict[str, Any]]:
    """Fetch a single page from arXiv API."""
    params = {
        "search_query": query,
        "start": str(start),
        "max_results": str(PAGE_SIZE),
        "sortBy": "submittedDate",
        "sortOrder": "descending",
    }
    url = f"{BASE_URL}?{urllib.parse.urlencode(params)}"
    try:
        data = http_get(url, timeout=60)
        return _parse_arxiv_response(data)
    except Exception as e:
        print(f"      [warn] arXiv API error at start={start}: {e}")
        return []


def fetch_arxiv_backfill(max_results: int = 2000) -> List[Dict[str, Any]]:
    """Fetch BCI-related papers from arXiv, paginating through results.

    arXiv API doesn't support date-range filtering directly, but results
    are sorted by submission date (newest first). We paginate until we
    hit max_results or run out of papers.
    """
    query = _build_arxiv_query()
    all_items = []
    start = 0
    page = 0

    print(f"    [arxiv] Query: {query[:100]}...")

    while start < max_results:
        items = fetch_arxiv_page(query, start)
        if not items:
            break

        all_items.extend(items)
        page += 1
        print(f"      page {page}: fetched {len(items)}, total {len(all_items)}")

        if len(items) < PAGE_SIZE:
            break

        start += PAGE_SIZE
        time.sleep(RATE_LIMIT_SLEEP)

    return all_items
