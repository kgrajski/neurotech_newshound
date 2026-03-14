"""
Story-level deduplication — group items about the same underlying story.

URL-based dedup catches exact duplicates, but the same story reported by
different outlets (e.g., "China approves brain implant" from Reuters,
Euronews, Qazinform) gets through as 3 separate high-priority alerts.

This node uses a single LLM call to cluster scored items by story identity,
using titles, abstracts/summaries, URLs, and assessments to make semantic
distinctions — not just keyword overlap.

Each cluster gets one primary item (highest score) and the rest become
"also reported by" references.

Uses the reviewer model (configurable to gpt-4o) since this is a single
high-value call where clustering accuracy directly impacts report quality.

Inserted in the pipeline between review and retain_memory:
    review → cluster_stories → retain_memory → meta_reflect
"""
import json
import re
from typing import Any, Dict, List
from urllib.parse import urlparse

from state import HoundState
from tools.llm import create_llm, invoke_llm, parse_json
from tools.config import get_agent_domain


CLUSTER_PROMPT = """You are deduplicating a research intelligence feed about {domain}.

Below are {count} items. For each item you have: index, title, source, URL,
abstract/summary, and the analyst's one-line assessment. Use ALL of this
information — especially the abstract — to determine whether items describe
the same real-world story.

Group items that cover the SAME story into clusters. Items that are unique
should each get their own cluster.

RULES (read carefully):

1. SAME STORY = same real-world event reported by different outlets.
   "China approves brain implant" from Reuters and Euronews = same story.

2. Company pages from the same domain describing the same product/technology
   = same cluster ("About Synchron" and "Synchron Platform" and "Synchron
   Technology" are all Synchron's product page).

3. A company announcement and a news article covering that announcement
   = same story (Paradromics press release + Wired article about it).

4. DIFFERENT academic papers are ALWAYS different stories. Use the abstract
   to distinguish them. Papers with different patient populations, methods,
   modalities, or findings are separate stories even if titles share keywords.
   Examples of DIFFERENT stories (do NOT merge):
   - "EEG-SSVEP in ALS patients over 27 months" vs "intracortical BCI with
     brain-to-text speech decoders in pontine stroke" — different modality,
     different patients, different application
   - "Stability of chronic ECoG-BCI" vs "5-year follow-up of implanted BCI
     in spinal cord injury" — different devices, different studies
   Only merge papers if they are literally the same paper on different sites
   (same DOI, same abstract, same authors).

5. Different events from the same company = different stories (Paradromics
   FDA approval vs. Paradromics laser tool development).

=== ITEMS ===
{items_text}

Respond with ONLY a JSON array of clusters:
[
  {{"label": "short story description", "indices": [3, 7, 12]}},
  {{"label": "another story", "indices": [5]}},
  ...
]

Every item index must appear in exactly one cluster."""


def cluster_stories(state: HoundState) -> HoundState:
    """Cluster scored items by story identity to reduce redundant alerts."""
    scored = state.get("scored_items", [])
    if not scored or len(scored) < 3:
        return state

    candidates = [i for i, x in enumerate(scored) if x.get("llm_score", 0) >= 6]
    if len(candidates) < 3:
        return state

    print(f"  Clustering {len(candidates)} items by story identity...")

    items_text = _build_items_text(scored, candidates)

    domain = get_agent_domain()
    prompt = CLUSTER_PROMPT.format(
        domain=domain,
        count=len(candidates),
        items_text=items_text,
    )

    # Use reviewer model for clustering — single call, high-value decision
    model = state.get("reviewer_model") or state["model"]

    try:
        llm = create_llm(model)
        content = invoke_llm(llm, prompt, node="cluster_stories", model_name=model)
        clusters = parse_json(content)

        if not isinstance(clusters, list):
            print("  [warn] Clustering returned non-list, skipping")
            return state

        splits = _split_mismerged_papers(scored, clusters)
        if splits > 0:
            print(f"  [fix] Post-validation split {splits} mismerged academic papers")

        _apply_clusters(scored, clusters)

        multi_clusters = [c for c in clusters if len(c.get("indices", [])) > 1]
        total_deduped = sum(len(c["indices"]) - 1 for c in multi_clusters)
        print(f"  [ok] {len(multi_clusters)} story clusters found, {total_deduped} redundant items demoted")

        for c in multi_clusters:
            primary_idx = c["indices"][0]
            primary_title = scored[primary_idx].get("title", "")[:50]
            print(f"    \"{c.get('label', '?')}\": {len(c['indices'])} items (primary: {primary_title}...)")

        scored.sort(key=lambda x: x.get("llm_score", 0), reverse=True)
        state["scored_items"] = scored
        state["alerts"] = [x for x in scored if x.get("llm_score", 0) >= 9 and not x.get("_cluster_secondary")]

    except Exception as e:
        state["errors"].append(f"Story clustering: {e}")
        print(f"  [warn] Story clustering failed: {e}")

    return state


def _build_items_text(scored: list, candidates: list) -> str:
    """Format items for the clustering prompt, including abstracts."""
    lines = []
    for idx in candidates:
        item = scored[idx]
        title = item.get("title", "")[:120]
        source = item.get("source", "")[:40]
        url = item.get("url", "")[:100]
        summary = item.get("summary", "")[:300]
        assessment = item.get("assessment", "")[:150]

        lines.append(f"[{idx}] TITLE: {title}")
        lines.append(f"    SOURCE: {source} | URL: {url}")
        if summary:
            lines.append(f"    ABSTRACT: {summary}")
        lines.append(f"    ASSESSMENT: {assessment}")
        lines.append("")
    return "\n".join(lines)


_ACADEMIC_DOMAINS = {
    "medrxiv.org", "biorxiv.org", "arxiv.org", "pmc.ncbi.nlm.nih.gov",
    "pubmed.ncbi.nlm.nih.gov", "nature.com", "science.org", "cell.com",
    "thelancet.com", "nejm.org", "ieee.org", "iopscience.iop.org",
    "doi.org",
}

_DOI_RE = re.compile(r"10\.\d{4,}/[^\s]+")


def _is_academic(item: dict) -> bool:
    """Check if an item is an academic paper based on source/URL."""
    url = item.get("url", "")
    source = item.get("source", "").lower()
    source_id = item.get("source_id", "").lower()
    if any(d in url for d in _ACADEMIC_DOMAINS):
        return True
    if any(kw in source_id for kw in ("pubmed", "biorxiv", "medrxiv", "arxiv", "jne")):
        return True
    if "preprint" in item.get("source_category", ""):
        return True
    return False


def _extract_doi(item: dict) -> str:
    """Extract DOI from URL or meta fields."""
    url = item.get("url", "")
    meta = item.get("meta", "")
    for text in (url, meta):
        m = _DOI_RE.search(text)
        if m:
            return m.group(0).rstrip(".,;)")
    return ""


def _paper_identity(item: dict) -> str:
    """Fingerprint for an academic paper — DOI if available, else normalized URL."""
    doi = _extract_doi(item)
    if doi:
        return f"doi:{doi}"
    url = item.get("url", "").rstrip("/").split("?")[0]
    if url.endswith(".pdf"):
        url = url[:-4]
    return url


def _split_mismerged_papers(scored: list, clusters: list) -> int:
    """Post-LLM validation: split clusters that incorrectly merge different papers.

    If a cluster contains multiple academic papers with different DOIs/URLs,
    each distinct paper becomes its own single-item cluster. News articles
    and company pages are left in the original cluster.
    """
    total_splits = 0

    new_clusters = []
    for cluster in clusters:
        indices = cluster.get("indices", [])
        label = cluster.get("label", "")
        if len(indices) < 2:
            new_clusters.append(cluster)
            continue

        valid = [i for i in indices if 0 <= i < len(scored)]
        academic = [(i, _paper_identity(scored[i])) for i in valid if _is_academic(scored[i])]
        non_academic = [i for i in valid if not _is_academic(scored[i])]

        if len(academic) < 2:
            new_clusters.append(cluster)
            continue

        # Group academic items by identity
        by_identity: Dict[str, List[int]] = {}
        for idx, identity in academic:
            by_identity.setdefault(identity, []).append(idx)

        if len(by_identity) <= 1:
            new_clusters.append(cluster)
            continue

        # Multiple distinct papers incorrectly merged — split them
        for identity, group_indices in by_identity.items():
            combined = group_indices + non_academic
            non_academic = []  # non-academic items go with the first paper only
            paper_title = scored[group_indices[0]].get("title", "")[:60]
            new_clusters.append({
                "label": paper_title,
                "indices": combined,
            })

        total_splits += len(by_identity) - 1

    clusters.clear()
    clusters.extend(new_clusters)
    return total_splits


def _apply_clusters(scored: List[Dict[str, Any]], clusters: list):
    """Mark secondary items in each cluster and attach 'also reported by' to primary."""
    for cluster in clusters:
        indices = cluster.get("indices", [])
        label = cluster.get("label", "")
        if len(indices) < 2:
            continue

        valid = [i for i in indices if 0 <= i < len(scored)]
        if len(valid) < 2:
            continue

        # Primary = highest scored item in the cluster
        valid.sort(key=lambda i: scored[i].get("llm_score", 0), reverse=True)
        primary_idx = valid[0]
        secondary_indices = valid[1:]

        also_reported = []
        for sec_idx in secondary_indices:
            sec = scored[sec_idx]
            also_reported.append({
                "title": sec.get("title", "")[:100],
                "source": sec.get("source", ""),
                "url": sec.get("url", ""),
            })
            sec["_cluster_secondary"] = True
            sec["_cluster_label"] = label
            sec["_cluster_primary_title"] = scored[primary_idx].get("title", "")[:100]

        scored[primary_idx]["_also_reported_by"] = also_reported
        scored[primary_idx]["_cluster_label"] = label
        scored[primary_idx]["_cluster_size"] = len(valid)
