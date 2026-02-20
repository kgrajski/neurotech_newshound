"""PubMed E-utilities fetch (no API key required).

The search query is constructed dynamically from vocabulary.yaml via
tools/vocabulary.py. This replaces the previous hardcoded query and
allows the vocabulary to grow as new papers are processed.
"""
import datetime as dt
import urllib.parse
import xml.etree.ElementTree as ET
from typing import Any, Dict, List

from tools.http import http_get, safe_text
from tools.vocabulary import build_pubmed_query


def esearch(query: str, days: int, max_items: int) -> List[str]:
    """Search PubMed and return list of PMIDs."""
    mindate = (dt.date.today() - dt.timedelta(days=days)).strftime("%Y/%m/%d")
    maxdate = dt.date.today().strftime("%Y/%m/%d")
    params = {
        "db": "pubmed", "term": query, "retmode": "xml",
        "retmax": str(max_items), "mindate": mindate, "maxdate": maxdate,
        "datetype": "pdat", "sort": "pub+date",
    }
    url = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi?" + urllib.parse.urlencode(params)
    root = ET.fromstring(http_get(url))
    return [el.text for el in root.findall(".//IdList/Id") if el.text]


def efetch(pmids: List[str]) -> List[Dict[str, Any]]:
    """Fetch full records for a list of PMIDs."""
    if not pmids:
        return []
    params = {"db": "pubmed", "id": ",".join(pmids), "retmode": "xml"}
    url = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi?" + urllib.parse.urlencode(params)
    root = ET.fromstring(http_get(url))

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
