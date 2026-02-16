"""RSS feed parsing — handles RSS 2.0, RSS 1.0/RDF, and Atom feeds.

Now registry-driven: instead of a hardcoded feed list, accepts a list of
source dicts from the source registry. The parse_rss() function is unchanged
and handles all three feed formats.
"""
import xml.etree.ElementTree as ET
from typing import Any, Dict, List

from tools.http import http_get, safe_text


def parse_rss(xml_bytes: bytes) -> List[Dict[str, Any]]:
    """Parse RSS 2.0, RSS 1.0/RDF, or Atom feed. Returns list of item dicts."""
    if xml_bytes[:3] == b"\xef\xbb\xbf":
        xml_bytes = xml_bytes[3:]
    root = ET.fromstring(xml_bytes)
    items = []

    # RSS 2.0
    for item in root.findall(".//channel/item"):
        items.append({
            "title": safe_text(item.findtext("title") or ""),
            "url": safe_text(item.findtext("link") or ""),
            "summary": safe_text(item.findtext("description") or ""),
            "meta": safe_text(item.findtext("pubDate") or ""),
        })
    if items:
        return items

    # RSS 1.0 / RDF
    RSS1_NS = "http://purl.org/rss/1.0/"
    RDF_NS = "http://www.w3.org/1999/02/22-rdf-syntax-ns#"
    for item in root.findall(f".//{{{RSS1_NS}}}item"):
        title = safe_text(item.findtext(f"{{{RSS1_NS}}}title") or "")
        link = safe_text(item.findtext(f"{{{RSS1_NS}}}link") or "")
        desc = safe_text(item.findtext(f"{{{RSS1_NS}}}description") or "")
        about = item.attrib.get(f"{{{RDF_NS}}}about", "")
        items.append({"title": title, "url": link or about, "summary": desc, "meta": ""})
    if items:
        return items

    # Atom
    ATOM_NS = "http://www.w3.org/2005/Atom"
    for entry in root.findall(f".//{{{ATOM_NS}}}entry"):
        title = safe_text(entry.findtext(f"{{{ATOM_NS}}}title") or "")
        summary = safe_text(
            entry.findtext(f"{{{ATOM_NS}}}summary") or
            entry.findtext(f"{{{ATOM_NS}}}content") or ""
        )
        link = ""
        link_el = entry.find(f"{{{ATOM_NS}}}link")
        if link_el is not None and "href" in link_el.attrib:
            link = safe_text(link_el.attrib["href"])
        updated = safe_text(entry.findtext(f"{{{ATOM_NS}}}updated") or "")
        items.append({"title": title, "url": link, "summary": summary, "meta": updated})

    return items


def fetch_rss_source(source: Dict[str, Any], max_items: int) -> List[Dict[str, Any]]:
    """Fetch items from a single RSS source (source dict from registry)."""
    name = source.get("name", source.get("id", "unknown"))
    url = source.get("url", "")
    if not url:
        return []

    xml = http_get(url)
    items = parse_rss(xml)[:max_items]
    for it in items:
        it["source"] = name
        it["source_id"] = source.get("id", "")
        it["source_category"] = source.get("category", "")
    return items


def fetch_rss_sources(sources: List[Dict[str, Any]], max_items: int) -> Dict[str, List[Dict[str, Any]]]:
    """
    Fetch items from multiple RSS sources.

    Returns dict of {source_id: items_list} so the caller can update
    per-source stats in the registry.
    """
    results = {}
    for source in sources:
        sid = source.get("id", "unknown")
        name = source.get("name", sid)
        try:
            items = fetch_rss_source(source, max_items)
            results[sid] = items
            print(f"    [ok] {name}: {len(items)} items")
        except Exception as e:
            results[sid] = []
            print(f"    [warn] {name}: {e}")
    return results
