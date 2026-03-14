"""
Story-level deduplication — group items about the same underlying story.

URL-based dedup catches exact duplicates, but the same story reported by
different outlets (e.g., "China approves brain implant" from Reuters,
Euronews, Qazinform) gets through as 3 separate high-priority alerts.

This node uses a single GPT-4o-mini call to cluster scored items by
story identity. Each cluster gets one primary item (highest score) and
the rest become "also reported by" references.

Inserted in the pipeline between review and retain_memory:
    review → cluster_stories → retain_memory → meta_reflect
"""
import json
from typing import Any, Dict, List

from state import HoundState
from tools.llm import create_llm, invoke_llm, parse_json
from tools.config import get_agent_domain


CLUSTER_PROMPT = """You are deduplicating a research intelligence feed about {domain}.

Below are {count} items, each with an index, title, source, and one-line assessment.
Many items report the SAME underlying story from different news outlets or are
different pages from the same company website describing the same product/technology.

Group items that cover the same story, event, or entity page into clusters.
Items that are unique (no duplicates) should each get their own cluster.

IMPORTANT:
- "Same story" means the same real-world event, announcement, or milestone
  reported by different sources. E.g., "China approves brain implant" from
  Reuters and Euronews are the same story.
- Company "about" pages, "platform" pages, and "technology" pages from the
  same company domain are the same cluster (they describe the same product).
- A company's FDA approval announcement and a news article about that same
  approval are the same story.
- Different events from the same company are DIFFERENT stories (e.g.,
  Paradromics FDA approval vs. Paradromics laser tool development).

=== ITEMS ===
{items_text}

Respond with a JSON array of clusters. Each cluster has:
- "label": a short (5-10 word) description of the story
- "indices": array of item indices (0-based) in this cluster

Example:
[
  {{"label": "China approves first commercial brain implant", "indices": [3, 7, 12, 15]}},
  {{"label": "Synchron raises $200M funding round", "indices": [5, 9]}},
  {{"label": "Novel graphene BCI material", "indices": [22]}}
]

Return ONLY the JSON array. Every item index must appear in exactly one cluster."""


def cluster_stories(state: HoundState) -> HoundState:
    """Cluster scored items by story identity to reduce redundant alerts."""
    scored = state.get("scored_items", [])
    if not scored or len(scored) < 3:
        return state

    # Only cluster items scored >= 6 (lower-scored items rarely cause alert spam)
    candidates = [i for i, x in enumerate(scored) if x.get("llm_score", 0) >= 6]
    if len(candidates) < 3:
        return state

    print(f"  Clustering {len(candidates)} items by story identity...")

    items_text = ""
    for idx in candidates:
        item = scored[idx]
        title = item.get("title", "")[:100]
        source = item.get("source", "")[:40]
        assessment = item.get("assessment", "")[:80]
        items_text += f"[{idx}] {title} | {source} | {assessment}\n"

    domain = get_agent_domain()
    prompt = CLUSTER_PROMPT.format(
        domain=domain,
        count=len(candidates),
        items_text=items_text,
    )

    try:
        llm = create_llm(state["model"])
        content = invoke_llm(llm, prompt, node="cluster_stories", model_name=state["model"])
        clusters = parse_json(content)

        if not isinstance(clusters, list):
            print("  [warn] Clustering returned non-list, skipping")
            return state

        _apply_clusters(scored, clusters)

        multi_clusters = [c for c in clusters if len(c.get("indices", [])) > 1]
        total_deduped = sum(len(c["indices"]) - 1 for c in multi_clusters)
        print(f"  [ok] {len(multi_clusters)} story clusters found, {total_deduped} redundant items demoted")

        for c in multi_clusters:
            primary_idx = c["indices"][0]
            primary_title = scored[primary_idx].get("title", "")[:50]
            print(f"    \"{c.get('label', '?')}\": {len(c['indices'])} items (primary: {primary_title}...)")

        # Re-sort: primaries keep their score, secondaries are demoted
        scored.sort(key=lambda x: x.get("llm_score", 0), reverse=True)
        state["scored_items"] = scored
        state["alerts"] = [x for x in scored if x.get("llm_score", 0) >= 9 and not x.get("_cluster_secondary")]

    except Exception as e:
        state["errors"].append(f"Story clustering: {e}")
        print(f"  [warn] Story clustering failed: {e}")

    return state


def _apply_clusters(scored: List[Dict[str, Any]], clusters: list):
    """Mark secondary items in each cluster and attach 'also reported by' to primary."""
    for cluster in clusters:
        indices = cluster.get("indices", [])
        label = cluster.get("label", "")
        if len(indices) < 2:
            continue

        # Validate indices
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
