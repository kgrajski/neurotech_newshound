"""PubMed E-utilities fetch (no API key required).

The search query is constructed dynamically from vocabulary.yaml via
tools/vocabulary.py. This replaces the previous hardcoded query and
allows the vocabulary to grow as new papers are processed.
"""
import datetime as dt
import urllib.parse
import xml.etree.ElementTree as ET
from typing import Any, Dict, List

from tools.http import http_get, http_post, safe_text
from tools.vocabulary import build_pubmed_query


ESEARCH_URL = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi"


def _esearch_post(params: dict) -> ET.Element:
    """POST to esearch — avoids 414 URI Too Long for large vocabulary queries."""
    data = http_post(ESEARCH_URL, params)
    return ET.fromstring(data)


def esearch(query: str, days: int, max_items: int) -> List[str]:
    """Search PubMed and return list of PMIDs."""
    mindate = (dt.date.today() - dt.timedelta(days=days)).strftime("%Y/%m/%d")
    maxdate = dt.date.today().strftime("%Y/%m/%d")
    params = {
        "db": "pubmed", "term": query, "retmode": "xml",
        "retmax": str(max_items), "mindate": mindate, "maxdate": maxdate,
        "datetype": "pdat", "sort": "pub+date",
    }
    root = _esearch_post(params)
    return [el.text for el in root.findall(".//IdList/Id") if el.text]


EFETCH_URL = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi"
EFETCH_BATCH = 200  # PMIDs per efetch call to avoid URL length issues


def _efetch_batch(pmids: List[str]) -> List[Dict[str, Any]]:
    """Fetch full records for a batch of PMIDs via POST."""
    if not pmids:
        return []
    params = {"db": "pubmed", "id": ",".join(pmids), "retmode": "xml"}
    data = http_post(EFETCH_URL, params)
    root = ET.fromstring(data)

    items = []
    for art in root.findall(".//PubmedArticle"):
        pmid = art.findtext(".//PMID") or ""
        title = safe_text(art.findtext(".//ArticleTitle") or "")
        abstract_parts = [safe_text(x.text or "") for x in art.findall(".//Abstract/AbstractText")]
        abstract = safe_text(" ".join(p for p in abstract_parts if p))
        journal = safe_text(art.findtext(".//Journal/Title") or "")
        year = art.findtext(".//PubDate/Year") or art.findtext(".//PubDate/MedlineDate") or ""
        items.append({
            "source": "PubMed",
            "title": title,
            "summary": abstract,
            "meta": safe_text(f"{journal} {year} PMID:{pmid}"),
            "url": f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/" if pmid else "",
        })
    return items


def efetch(pmids: List[str]) -> List[Dict[str, Any]]:
    """Fetch full records for a list of PMIDs, batching to avoid URL limits."""
    if not pmids:
        return []
    items = []
    for i in range(0, len(pmids), EFETCH_BATCH):
        batch = pmids[i:i + EFETCH_BATCH]
        items.extend(_efetch_batch(batch))
    return items


def esearch_date_range(
    query: str, start_date: str, end_date: str, max_items: int, retstart: int = 0
) -> tuple:
    """Search PubMed with explicit date range. Returns (pmids, total_count).

    Uses POST to avoid 414 URI Too Long with our expanded vocabulary query.
    """
    params = {
        "db": "pubmed", "term": query, "retmode": "xml",
        "retmax": str(max_items), "retstart": str(retstart),
        "mindate": start_date, "maxdate": end_date,
        "datetype": "pdat", "sort": "pub+date",
    }
    root = _esearch_post(params)
    count = int(root.findtext(".//Count") or "0")
    pmids = [el.text for el in root.findall(".//IdList/Id") if el.text]
    return pmids, count


def fetch_pubmed_backfill(
    start_year: int,
    end_year: int,
    chunk_months: int = 6,
    max_per_chunk: int = 500,
) -> List[Dict[str, Any]]:
    """Backfill PubMed in date-range chunks for multi-year historical data.

    Chunks the date range into windows of `chunk_months` months. Within each
    chunk, paginates if results exceed `max_per_chunk`. Respects NCBI rate
    limits (no API key = 3 req/sec).
    """
    import time

    query = build_pubmed_query()
    if not query:
        print("    [warn] No vocabulary — skipping PubMed backfill")
        return []

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

        s_str = chunk_start.strftime("%Y/%m/%d")
        e_str = chunk_end.strftime("%Y/%m/%d")

        try:
            pmids, total = esearch_date_range(query, s_str, e_str, max_per_chunk)
            print(
                f"    [pubmed] {chunk_start.strftime('%Y-%m')} → "
                f"{chunk_end.strftime('%Y-%m')}: {total} results, "
                f"fetching {min(len(pmids), max_per_chunk)}"
            )

            if pmids:
                items = efetch(pmids[:max_per_chunk])
                for it in items:
                    it["source_id"] = "pubmed"
                    it["source_category"] = "database"
                all_items.extend(items)

            time.sleep(0.5)

            # Paginate if more results exist
            retstart = max_per_chunk
            while retstart < total and retstart < max_per_chunk * 3:
                pmids2, _ = esearch_date_range(query, s_str, e_str, max_per_chunk, retstart)
                if not pmids2:
                    break
                items2 = efetch(pmids2)
                for it in items2:
                    it["source_id"] = "pubmed"
                    it["source_category"] = "database"
                all_items.extend(items2)
                retstart += max_per_chunk
                time.sleep(0.5)

        except Exception as e:
            print(f"    [warn] PubMed chunk {s_str}-{e_str}: {e}")

        chunk_start = chunk_end + dt.timedelta(days=1)

    return all_items


def fetch_pubmed_items(days: int, max_items: int) -> List[Dict[str, Any]]:
    """High-level: search + fetch PubMed items.

    Query is constructed dynamically from vocabulary.yaml. Falls back to
    a minimal hardcoded query if vocabulary.yaml is missing or empty.
    """
    query = build_pubmed_query()
    if not query:
        query = (
            '("brain-computer interface"[Title/Abstract] OR BCI[Title/Abstract] '
            'OR ECoG[Title/Abstract] OR "neural implant"[Title/Abstract]) '
            'AND (human[Title/Abstract] OR implant*[Title/Abstract])'
        )
    pmids = esearch(query, days, max_items)
    return efetch(pmids[:max_items])
