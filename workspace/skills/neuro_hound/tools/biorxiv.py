"""bioRxiv / medRxiv API fetcher for historical backfill.

Uses the official content-detail API:
    https://api.biorxiv.org/details/{server}/{start}/{end}/{cursor}/json

Returns 100 papers per page (all subjects). We filter client-side using
the vocabulary regex because the API has no search/subject parameter.

Rate limiting: bioRxiv asks for ≤1 request/sec. We sleep 1.5s between pages.
"""
import datetime as dt
import json
import time
import urllib.parse
from typing import Any, Dict, List, Optional

from tools.http import http_get, safe_text
from tools.scoring import is_in_scope

BASE_URL = "https://api.biorxiv.org/details"
PAGE_SIZE = 100
RATE_LIMIT_SLEEP = 1.5  # seconds between API calls


def fetch_biorxiv_page(
    server: str,
    start_date: str,
    end_date: str,
    cursor: int = 0,
    timeout: int = 60,
) -> Optional[Dict[str, Any]]:
    """Fetch a single page from bioRxiv/medRxiv API.

    Args:
        server: "biorxiv" or "medrxiv"
        start_date: "YYYY-MM-DD"
        end_date: "YYYY-MM-DD"
        cursor: page offset (0-indexed, increments by 100)
    """
    url = f"{BASE_URL}/{server}/{start_date}/{end_date}/{cursor}/json"
    try:
        data = http_get(url, timeout=timeout)
        return json.loads(data)
    except Exception as e:
        print(f"      [warn] {server} API error at cursor {cursor}: {e}")
        return None


def fetch_biorxiv_window(
    server: str,
    start_date: str,
    end_date: str,
    max_pages: int = 50,
    verbose: bool = True,
) -> List[Dict[str, Any]]:
    """Fetch all papers from a date window, filtering for BCI relevance.

    Iterates through pages until no more results or max_pages reached.
    Applies vocabulary-based regex filter client-side.
    """
    all_items = []
    cursor = 0
    total_scanned = 0
    page = 0

    while page < max_pages:
        result = fetch_biorxiv_page(server, start_date, end_date, cursor)

        if result is None:
            break

        messages = result.get("messages", [{}])
        msg = messages[0] if messages else {}
        total_in_range = int(msg.get("total", 0))
        count_on_page = int(msg.get("count", 0))

        if count_on_page == 0:
            break

        papers = result.get("collection", [])
        if not papers:
            break

        for paper in papers:
            title = safe_text(paper.get("title", ""))
            abstract = safe_text(paper.get("abstract", ""))
            total_scanned += 1

            if is_in_scope(title, abstract):
                doi = paper.get("doi", "")
                all_items.append({
                    "source": f"{server.capitalize()}",
                    "source_id": server,
                    "source_category": "preprint",
                    "title": title,
                    "summary": abstract[:1000],
                    "url": f"https://doi.org/{doi}" if doi else "",
                    "meta": safe_text(
                        f"{paper.get('category', '')} "
                        f"{paper.get('date', '')} "
                        f"doi:{doi}"
                    ),
                })

        if verbose:
            print(
                f"      page {page + 1}: scanned {total_scanned}/{total_in_range}, "
                f"matched {len(all_items)} in-scope"
            )

        cursor += PAGE_SIZE
        page += 1

        if total_scanned >= total_in_range:
            break

        time.sleep(RATE_LIMIT_SLEEP)

    return all_items


def fetch_biorxiv_backfill(
    server: str,
    start_year: int,
    end_year: int,
    chunk_months: int = 3,
    max_pages_per_chunk: int = 100,
) -> List[Dict[str, Any]]:
    """Backfill from bioRxiv/medRxiv in monthly chunks over multiple years.

    Chunks the date range into windows of `chunk_months` months to avoid
    API timeouts and provide granular progress reporting.
    """
    all_items = []
    start = dt.date(start_year, 1, 1)
    end = dt.date(end_year, 12, 31)
    today = dt.date.today()
    if end > today:
        end = today

    chunk_start = start
    while chunk_start < end:
        chunk_end = chunk_start + dt.timedelta(days=chunk_months * 30)
        if chunk_end > end:
            chunk_end = end

        s_str = chunk_start.strftime("%Y-%m-%d")
        e_str = chunk_end.strftime("%Y-%m-%d")
        print(f"    [{server}] {s_str} → {e_str}")

        items = fetch_biorxiv_window(
            server=server,
            start_date=s_str,
            end_date=e_str,
            max_pages=max_pages_per_chunk,
        )
        all_items.extend(items)
        print(f"    [{server}] {s_str} → {e_str}: {len(items)} in-scope papers")

        chunk_start = chunk_end + dt.timedelta(days=1)

    return all_items
