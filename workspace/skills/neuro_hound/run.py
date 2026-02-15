#!/usr/bin/env python3
"""
NeuroTech Hound — MVP discovery + triage skill.

Fetches recent items from PubMed and RSS feeds (bioRxiv, medRxiv),
scores them for relevance to implantable BCI / ECoG / sEEG research,
and produces a ranked markdown report with alerts.

Phase 1: Pure Python, no LLM, no API keys required.
Phase 2 (planned): LangGraph workflow with LLM summarization + reflection.
Phase 3 (planned): MLflow tracking for run metrics and artifacts.
"""
import argparse
import datetime as dt
import json
import os
import re
import ssl
import sys
import textwrap
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET

UA = "openclaw-neuro-hound/0.3 (MVP; no-api-keys)"

# SSL context — handles macOS certificate issues gracefully
try:
    import certifi
    _SSL_CTX = ssl.create_default_context(cafile=certifi.where())
except ImportError:
    _SSL_CTX = ssl.create_default_context()
    # macOS fallback: if default certs aren't found, disable verification
    # (fine for public PubMed/bioRxiv; the droplet won't need this)
    try:
        _SSL_CTX.load_default_certs()
    except Exception:
        _SSL_CTX.check_hostname = False
        _SSL_CTX.verify_mode = ssl.CERT_NONE

PUBMED_QUERY = (
    "("
    '"brain-computer interface"[Title/Abstract] OR BCI[Title/Abstract] OR neuroprosthe*[Title/Abstract] OR '
    'intracortical[Title/Abstract] OR "microelectrode array"[Title/Abstract] OR "Utah array"[Title/Abstract] OR '
    '"motor cortex"[Title/Abstract] OR "speech decoding"[Title/Abstract] OR '
    'ECoG[Title/Abstract] OR sEEG[Title/Abstract] OR "stereo-EEG"[Title/Abstract] OR '
    '"intracranial EEG"[Title/Abstract] OR iEEG[Title/Abstract]'
    ") "
    "AND ("
    'implant*[Title/Abstract] OR human[Title/Abstract] OR participant*[Title/Abstract] OR patient*[Title/Abstract] OR '
    'microstimulation[Title/Abstract] OR stimulation[Title/Abstract] OR "closed-loop"[Title/Abstract] OR '
    'chronic[Title/Abstract] OR long-term[Title/Abstract] OR biocompatib*[Title/Abstract] OR hermetic[Title/Abstract] OR '
    'encapsulation[Title/Abstract] OR coating[Title/Abstract]'
    ")"
)

RSS_FEEDS = [
    ("bioRxiv (neuroscience)", "https://connect.biorxiv.org/biorxiv_xml.php?subject=neuroscience"),
    ("medRxiv (all)", "https://connect.medrxiv.org/medrxiv_xml.php"),
]

# Broad scope (used for ranking/reporting)
IN_SCOPE_BROAD = re.compile(
    r"\b("
    r"brain[- ]computer interface|bci|neuroprosthe|intracortical|"
    r"ecog|seeg|stereo-?eeg|ieeg|intracranial eeg|"
    r"microstimulation|cortical stimulation|neural implant|implantable|"
    r"speech decoding|handwriting decoding|neural decoder|spike(s|d)?|single[- ]unit"
    r")\b",
    flags=re.IGNORECASE,
)

# Strict scope (required for score >=9)
IN_SCOPE_STRICT = re.compile(
    r"\b("
    r"brain[- ]computer interface|bci|neuroprosthe|"
    r"ecog|seeg|stereo-?eeg|ieeg|intracranial eeg|"
    r"microelectrode|microelectrode array|utah array|"
    r"implanted|implantable|neural implant|"
    r"single[- ]unit|spike(s|d)?|intracortical (recording|array|electrode)"
    r")\b",
    flags=re.IGNORECASE,
)

# Out-of-scope modalities (common false positives)
OUT_OF_SCOPE_HIGH = re.compile(
    r"\b("
    r"transcranial magnetic stimulation|tms|"
    r"transcranial direct current|tdcs|"
    r"transcranial alternating current|tacs"
    r")\b",
    flags=re.IGNORECASE,
)

HIGH_SIGNAL_PATTERNS = [
    (10, r"\bfirst[- ]in[- ]human\b|\bFIH\b"),
    (10, r"\bpivotal\b|\bPMA\b|\bDe\s?Novo\b|\b510\(k\)\b"),
    (10, r"\bFDA\b.*\bIDE\b|\bIDE\b.*\bFDA\b|\bIDE\b (granted|approved|accepted)"),
    (9,  r"\bhuman(s)?\b.*\bimplant\b|\bimplanted\b.*\bhuman\b|\bclinical trial\b|\btrial registration\b"),
    (8,  r"\bECoG\b|\bsEEG\b|\bstereo-?EEG\b|\bintracranial EEG\b|\biEEG\b"),
    (8,  r"\bsingle[- ]unit\b|\bspike(s|d)?\b"),
    (7,  r"\bmicrostimulation\b|\bclosed[- ]loop\b"),
    (6,  r"\bhermetic\b|\bencapsulation\b|\bcoating\b|\bmaterials?\b|\bbiocompatib"),
]

NEGATIVE_PATTERNS = [
    (2, r"\bwearable\b|\bEEG headset\b|\bheadband\b"),
    (2, r"\bmarketing\b|\bpress release\b|\bannounces\b"),
]


# =============================================================================
# HTTP & Parsing Utilities
# =============================================================================

def http_get(url: str, timeout=30) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=timeout, context=_SSL_CTX) as resp:
        return resp.read()


def safe_text(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "").strip())


# =============================================================================
# Scope & Scoring
# =============================================================================

def is_in_scope_broad(title: str, summary: str, source: str) -> bool:
    return bool(IN_SCOPE_BROAD.search(f"{title}\n{summary}\n{source}"))


def is_in_scope_strict(title: str, summary: str, source: str) -> bool:
    return bool(IN_SCOPE_STRICT.search(f"{title}\n{summary}\n{source}"))


def is_out_of_scope_high(title: str, summary: str) -> bool:
    return bool(OUT_OF_SCOPE_HIGH.search(f"{title}\n{summary}"))


def score_item(title: str, abstract_or_summary: str, source: str) -> int:
    """Score an item 1-10 based on relevance patterns."""
    text = f"{title}\n{abstract_or_summary}\n{source}"
    score = 4

    for val, pat in HIGH_SIGNAL_PATTERNS:
        if re.search(pat, text, flags=re.IGNORECASE):
            score = max(score, val)

    for val, pat in NEGATIVE_PATTERNS:
        if re.search(pat, text, flags=re.IGNORECASE):
            score = min(score, val)

    # Hard demotion for common out-of-scope modalities
    if is_out_of_scope_high(title, abstract_or_summary) and score >= 7:
        score = min(score, 6)

    # Gate: nothing can be 9-10 unless strictly in-scope
    if score >= 9 and not is_in_scope_strict(title, abstract_or_summary, source):
        score = 6

    return max(1, min(10, score))


# =============================================================================
# PubMed Fetch
# =============================================================================

def pubmed_esearch(query: str, days: int, max_items: int):
    mindate = (dt.date.today() - dt.timedelta(days=days)).strftime("%Y/%m/%d")
    maxdate = dt.date.today().strftime("%Y/%m/%d")
    params = {
        "db": "pubmed",
        "term": query,
        "retmode": "xml",
        "retmax": str(max_items),
        "mindate": mindate,
        "maxdate": maxdate,
        "datetype": "pdat",
        "sort": "pub+date",
    }
    url = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi?" + urllib.parse.urlencode(params)
    xml = http_get(url)
    root = ET.fromstring(xml)
    return [el.text for el in root.findall(".//IdList/Id") if el.text]


def pubmed_efetch(pmids):
    if not pmids:
        return []
    params = {"db": "pubmed", "id": ",".join(pmids), "retmode": "xml"}
    url = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi?" + urllib.parse.urlencode(params)
    xml = http_get(url)
    root = ET.fromstring(xml)

    items = []
    for art in root.findall(".//PubmedArticle"):
        pmid = art.findtext(".//PMID") or ""
        title = safe_text(art.findtext(".//ArticleTitle") or "")
        abstract_parts = [safe_text(x.text or "") for x in art.findall(".//Abstract/AbstractText")]
        abstract = safe_text(" ".join([p for p in abstract_parts if p]))
        journal = safe_text(art.findtext(".//Journal/Title") or "")
        year = art.findtext(".//PubDate/Year") or art.findtext(".//PubDate/MedlineDate") or ""
        url = f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/" if pmid else ""
        items.append({
            "source": "PubMed",
            "title": title,
            "summary": abstract,
            "meta": safe_text(f"{journal} {year} PMID:{pmid}"),
            "url": url,
        })
    return items


# =============================================================================
# RSS Fetch
# =============================================================================

def parse_rss(xml_bytes: bytes):
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
        summary = safe_text(entry.findtext(f"{{{ATOM_NS}}}summary") or entry.findtext(f"{{{ATOM_NS}}}content") or "")
        link = ""
        link_el = entry.find(f"{{{ATOM_NS}}}link")
        if link_el is not None and "href" in link_el.attrib:
            link = safe_text(link_el.attrib["href"])
        updated = safe_text(entry.findtext(f"{{{ATOM_NS}}}updated") or "")
        items.append({"title": title, "url": link, "summary": summary, "meta": updated})

    return items


# =============================================================================
# Report Generation
# =============================================================================

def md_escape(s: str) -> str:
    return (s or "").replace("\n", " ").strip()


def generate_report(scored: list, alerts: list, today: str, args) -> str:
    """Generate the markdown report."""
    lines = []
    lines.append(f"# Neuro Hound Report — {today}")
    lines.append("")
    lines.append(f"- Lookback: {args.days} day(s)")
    lines.append(f"- Total items: {len(scored)}")
    lines.append(f"- Alerts (9–10): {len(alerts)}")
    lines.append("")
    lines.append("## Alerts (9–10)")
    lines.append("")
    if alerts:
        for x in alerts[:20]:
            lines.append(f"- [{x['score']}] {md_escape(x.get('title', '(no title)'))} ({md_escape(x.get('source', ''))})")
            if x.get("url"):
                lines.append(f"  - {x['url']}")
    else:
        lines.append("_None detected in this run._")
    lines.append("")
    lines.append("## Top ranked (max 50)")
    lines.append("")
    for x in scored[:50]:
        tags = []
        if x.get("in_scope_strict"):
            tags.append("strict")
        elif x.get("in_scope_broad"):
            tags.append("broad")
        else:
            tags.append("out")
        if x.get("out_of_scope_high"):
            tags.append("TMS/transcranial")
        tag_str = ", ".join(tags)

        lines.append(f"### [{x['score']}] {md_escape(x.get('title', '(no title)'))} ({tag_str})")
        lines.append(f"- Source: {md_escape(x.get('source', ''))}")
        if x.get("meta"):
            lines.append(f"- Meta: {md_escape(x.get('meta', ''))}")
        if x.get("url"):
            lines.append(f"- Link: {x['url']}")
        if x.get("summary"):
            snippet = textwrap.shorten(md_escape(x["summary"]), width=500, placeholder="…")
            lines.append(f"- Summary: {snippet}")
        lines.append("")

    return "\n".join(lines).strip() + "\n"


# =============================================================================
# Main
# =============================================================================

def main():
    ap = argparse.ArgumentParser(description="NeuroTech Hound — discovery + triage")
    ap.add_argument("--days", type=int, default=7, help="Lookback window in days")
    ap.add_argument("--max", type=int, default=40, help="Max items per source")
    ap.add_argument("--output-dir", type=str, default=None,
                    help="Output directory (default: archives/neurotech/ relative to cwd)")
    args = ap.parse_args()

    today = dt.date.today().isoformat()
    out_dir = args.output_dir or os.path.join(os.getcwd(), "archives", "neurotech")
    os.makedirs(out_dir, exist_ok=True)
    out_md = os.path.join(out_dir, f"{today}.md")
    out_alerts = os.path.join(out_dir, f"{today}.alerts.json")

    all_items = []

    # --- PubMed ---
    try:
        pmids = pubmed_esearch(PUBMED_QUERY, args.days, args.max)
        pub_items = pubmed_efetch(pmids[:args.max])
        all_items.extend(pub_items)
        print(f"[ok] PubMed: {len(pub_items)} items")
    except Exception as e:
        print(f"[warn] PubMed fetch failed: {e}", file=sys.stderr)

    # --- RSS feeds ---
    for name, url in RSS_FEEDS:
        try:
            xml = http_get(url)
            items = parse_rss(xml)[:args.max]
            for it in items:
                it["source"] = name
            all_items.extend(items)
            print(f"[ok] RSS {name}: {len(items)} items")
        except Exception as e:
            print(f"[warn] RSS fetch failed ({name}): {e}", file=sys.stderr)

    # --- Score & sort ---
    scored = []
    for it in all_items:
        title = it.get("title", "")
        summary = it.get("summary", "")
        source = it.get("source", "")
        scored.append({
            **it,
            "score": score_item(title, summary, source),
            "in_scope_broad": is_in_scope_broad(title, summary, source),
            "in_scope_strict": is_in_scope_strict(title, summary, source),
            "out_of_scope_high": is_out_of_scope_high(title, summary),
        })

    scored.sort(key=lambda x: (
        x["score"],
        x.get("in_scope_strict", False),
        x.get("source", ""),
        x.get("title", ""),
    ), reverse=True)
    alerts = [x for x in scored if x["score"] >= 9]

    # --- Write outputs ---
    report = generate_report(scored, alerts, today, args)
    with open(out_md, "w", encoding="utf-8") as f:
        f.write(report)

    with open(out_alerts, "w", encoding="utf-8") as f:
        json.dump(alerts, f, ensure_ascii=False, indent=2)

    # --- Summary ---
    print(f"[done] Report:  {out_md}")
    print(f"[done] Alerts:  {out_alerts}")
    print(f"[done] Total: {len(scored)} items | In-scope: {sum(1 for x in scored if x['in_scope_broad'])} | Alerts: {len(alerts)}")


if __name__ == "__main__":
    main()
