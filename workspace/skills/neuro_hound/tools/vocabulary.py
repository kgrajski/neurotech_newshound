"""
Domain vocabulary manager — builds search queries from vocabulary.yaml.

The vocabulary store replaces hardcoded PubMed queries with a data-driven
approach. Terms are organized into primary (domain-defining) and qualifier
(relevance-filtering) categories. The PubMed query is constructed dynamically
at runtime by OR-ing primary terms in clause 1 and qualifier terms in clause 2.

In agentic mode, the LLM can propose new terms via add_terms(), which appends
them to vocabulary.yaml with provenance metadata. A configurable per-category
limit prevents unbounded growth, though in practice domain vocabulary
self-stabilizes as new papers mostly reuse existing terms.
"""
import os
import datetime as dt
from typing import Any, Dict, List, Optional, Tuple

import yaml

VOCAB_PATH = os.path.join(os.path.dirname(__file__), "..", "vocabulary.yaml")

_vocab: Optional[Dict[str, Any]] = None


def load_vocabulary(path: str = None) -> Dict[str, Any]:
    """Load and cache vocabulary from YAML."""
    global _vocab
    if _vocab is not None and path is None:
        return _vocab

    path = path or VOCAB_PATH
    if not os.path.exists(path):
        _vocab = {"settings": {}, "primary_terms": {}, "qualifier_terms": {}, "provenance": {}}
        return _vocab

    with open(path) as f:
        _vocab = yaml.safe_load(f) or {}
    return _vocab


def reload_vocabulary():
    """Force reload (for testing / after writes)."""
    global _vocab
    _vocab = None


def _get_settings() -> Dict[str, Any]:
    vocab = load_vocabulary()
    return vocab.get("settings", {})


def get_max_terms_per_category() -> int:
    return _get_settings().get("max_terms_per_category", 0)


def _flatten_term_group(group: Dict[str, List[str]]) -> List[str]:
    """Flatten a categorized term group into a deduplicated list."""
    seen = set()
    terms = []
    for category_terms in group.values():
        if not isinstance(category_terms, list):
            continue
        for term in category_terms:
            key = term.strip().lower()
            if key not in seen:
                seen.add(key)
                terms.append(term.strip())
    return terms


def get_primary_terms() -> List[str]:
    """Get all primary (domain-defining) terms, flattened and deduplicated."""
    vocab = load_vocabulary()
    return _flatten_term_group(vocab.get("primary_terms", {}))


def get_qualifier_terms() -> List[str]:
    """Get all qualifier (relevance-filtering) terms, flattened and deduplicated."""
    vocab = load_vocabulary()
    return _flatten_term_group(vocab.get("qualifier_terms", {}))


def _format_pubmed_term(term: str, field: str) -> str:
    """Format a single term for PubMed query syntax.

    Handles wildcards (no quotes needed) and multi-word phrases (need quotes).
    """
    if term.endswith("*"):
        return f"{term}[{field}]"
    if " " in term or "-" in term:
        return f'"{term}"[{field}]'
    return f"{term}[{field}]"


def build_pubmed_query() -> str:
    """Construct a PubMed query dynamically from vocabulary.yaml.

    Returns a query of the form:
        (primary_term1 OR primary_term2 OR ...) AND (qualifier1 OR qualifier2 OR ...)
    """
    field = _get_settings().get("pubmed_field", "Title/Abstract")
    primary = get_primary_terms()
    qualifiers = get_qualifier_terms()

    if not primary:
        return ""

    primary_clause = " OR ".join(_format_pubmed_term(t, field) for t in primary)

    if qualifiers:
        qualifier_clause = " OR ".join(_format_pubmed_term(t, field) for t in qualifiers)
        return f"({primary_clause}) AND ({qualifier_clause})"
    else:
        return f"({primary_clause})"


def get_vocabulary_stats() -> Dict[str, Any]:
    """Return term counts per category for monitoring convergence."""
    vocab = load_vocabulary()
    stats = {"primary": {}, "qualifier": {}, "totals": {"primary": 0, "qualifier": 0}}

    for category, terms in vocab.get("primary_terms", {}).items():
        if isinstance(terms, list):
            count = len(terms)
            stats["primary"][category] = count
            stats["totals"]["primary"] += count

    for category, terms in vocab.get("qualifier_terms", {}).items():
        if isinstance(terms, list):
            count = len(terms)
            stats["qualifier"][category] = count
            stats["totals"]["qualifier"] += count

    stats["totals"]["grand_total"] = stats["totals"]["primary"] + stats["totals"]["qualifier"]

    limit = get_max_terms_per_category()
    stats["max_terms_per_category"] = limit if limit > 0 else "unlimited"

    return stats


def add_terms(
    new_terms: List[Dict[str, str]],
    source_label: str = "auto-extracted",
    dry_run: bool = False,
) -> Tuple[List[str], List[str]]:
    """Add new terms to the vocabulary, respecting category limits.

    Args:
        new_terms: List of dicts with keys: term, group (primary/qualifier), category
        source_label: Provenance label (e.g. "Willett et al. 2023")
        dry_run: If True, report what would be added without writing

    Returns:
        (added, skipped) — lists of term strings
    """
    vocab = load_vocabulary()
    limit = get_max_terms_per_category()
    added = []
    skipped = []

    for entry in new_terms:
        term = entry.get("term", "").strip()
        group = entry.get("group", "primary")
        category = entry.get("category", "uncategorized")

        if not term:
            continue

        group_key = f"{group}_terms"
        if group_key not in vocab:
            vocab[group_key] = {}
        if category not in vocab[group_key]:
            vocab[group_key][category] = []

        existing = vocab[group_key][category]
        existing_lower = {t.strip().lower() for t in existing}

        if term.strip().lower() in existing_lower:
            skipped.append(f"{term} (duplicate)")
            continue

        if limit > 0 and len(existing) >= limit:
            skipped.append(f"{term} (category '{category}' at limit {limit})")
            continue

        existing.append(term)
        added.append(term)

    if added and not dry_run:
        today = dt.date.today().isoformat()
        provenance = vocab.setdefault("provenance", {})
        auto_key = f"auto_{today}"
        if auto_key not in provenance:
            provenance[auto_key] = {"date": today, "source": source_label, "terms_added": []}
        provenance[auto_key]["terms_added"].extend(added)

        with open(VOCAB_PATH, "w") as f:
            yaml.dump(vocab, f, default_flow_style=False, sort_keys=False, allow_unicode=True)

        reload_vocabulary()

    return added, skipped


def get_regex_terms() -> List[str]:
    """Get a flat list of all vocabulary terms for use in regex pre-filtering.

    Returns simplified terms (no PubMed wildcards or field tags) suitable for
    case-insensitive regex matching against article titles and abstracts.
    """
    all_terms = get_primary_terms() + get_qualifier_terms()
    regex_terms = []
    for term in all_terms:
        clean = term.rstrip("*").strip('"').strip()
        if len(clean) >= 3:
            regex_terms.append(clean)
    return regex_terms
