"""
Meta-tools — callable functions for the ReAct meta-reflection agent.

Each tool takes structured input and returns a human-readable string
(the "observation" in the ReAct loop). The meta-agent decides which
tools to call and in what order based on its analysis of the pipeline's
output.

These tools bridge existing capabilities (vocabulary.py, sources.py,
tavily.py) with agentic reasoning. Most wrap existing functions —
the agency comes from the LLM deciding *when* to use them.
"""
import json
from typing import Any, Dict, List, Optional

TOOL_REGISTRY: Dict[str, Dict[str, Any]] = {}


def _register(name: str, description: str, parameters: Dict[str, str]):
    """Decorator to register a tool with its schema for the LLM prompt."""
    def decorator(func):
        TOOL_REGISTRY[name] = {
            "name": name,
            "description": description,
            "parameters": parameters,
            "function": func,
        }
        return func
    return decorator


def get_tool_descriptions() -> str:
    """Format all tool schemas for inclusion in the ReAct system prompt."""
    lines = []
    for name, info in TOOL_REGISTRY.items():
        params = ", ".join(f"{k}: {v}" for k, v in info["parameters"].items())
        lines.append(f"- {name}({params})")
        lines.append(f"  {info['description']}")
    return "\n".join(lines)


def call_tool(name: str, args: Dict[str, Any], state: Dict[str, Any]) -> str:
    """Dispatch a tool call by name. Returns the observation string."""
    if name not in TOOL_REGISTRY:
        return f"ERROR: Unknown tool '{name}'. Available: {', '.join(TOOL_REGISTRY.keys())}"
    try:
        return TOOL_REGISTRY[name]["function"](args=args, state=state)
    except Exception as e:
        return f"ERROR: {name} failed — {e}"


# ─── Tool Implementations ─────────────────────────────────────────────


@_register(
    name="get_vocabulary_stats",
    description="Return term counts per category and convergence indicators. No side effects.",
    parameters={},
)
def tool_get_vocabulary_stats(args: Dict, state: Dict) -> str:
    from tools.vocabulary import get_vocabulary_stats
    stats = get_vocabulary_stats()
    lines = [f"Vocabulary: {stats['totals']['grand_total']} terms total"]
    lines.append(f"  Primary ({stats['totals']['primary']}): " +
                 ", ".join(f"{k}={v}" for k, v in stats["primary"].items()))
    lines.append(f"  Qualifier ({stats['totals']['qualifier']}): " +
                 ", ".join(f"{k}={v}" for k, v in stats["qualifier"].items()))
    limit = stats["max_terms_per_category"]
    lines.append(f"  Per-category limit: {limit}")
    return "\n".join(lines)


@_register(
    name="check_vocabulary_gaps",
    description="Analyze high-scoring items for domain terms NOT already in vocabulary.yaml. Returns candidate terms.",
    parameters={},
)
def tool_check_vocabulary_gaps(args: Dict, state: Dict) -> str:
    from tools.vocabulary import get_primary_terms, get_qualifier_terms

    existing = set(t.lower() for t in get_primary_terms() + get_qualifier_terms())
    scored = state.get("scored_items", [])
    high_scoring = [it for it in scored if it.get("llm_score", 0) >= 7]

    if not high_scoring:
        return "No high-scoring items (>=7) to analyze for vocabulary gaps."

    titles_and_summaries = []
    for it in high_scoring:
        text = f"{it.get('title', '')} {it.get('summary', '')[:200]}"
        titles_and_summaries.append(text)

    combined = " ".join(titles_and_summaries).lower()

    candidate_phrases = _extract_candidate_terms(combined, existing)

    if not candidate_phrases:
        return (f"Analyzed {len(high_scoring)} high-scoring items. "
                "No obvious vocabulary gaps detected — existing terms appear adequate.")

    lines = [f"Analyzed {len(high_scoring)} high-scoring items. Potential gaps:"]
    for term, context in candidate_phrases[:10]:
        lines.append(f"  - \"{term}\" (found in: {context[:60]}...)")
    return "\n".join(lines)


def _extract_candidate_terms(text: str, existing: set) -> List[tuple]:
    """Simple heuristic extraction of potential domain terms not in vocabulary."""
    import re
    neuro_indicators = [
        r"(\w+\s+electrode[s]?)", r"(\w+\s+implant[s]?)",
        r"(\w+\s+recording[s]?)", r"(\w+\s+stimulat\w+)",
        r"(\w+\s+decod\w+)", r"(\w+\s+interface[s]?)",
        r"(\w+\s+array[s]?)", r"(\w+\s+probe[s]?)",
        r"(\w+\s+cortex\b)", r"(\w+\s+cortical\b)",
        r"(neural\s+\w+)", r"(brain\s+\w+)",
    ]
    candidates = []
    seen = set()
    for pattern in neuro_indicators:
        for match in re.finditer(pattern, text):
            phrase = match.group(1).strip()
            key = phrase.lower()
            if key not in existing and key not in seen and len(phrase) > 5:
                seen.add(key)
                start = max(0, match.start() - 20)
                context = text[start:match.end() + 30]
                candidates.append((phrase, context))
    return candidates


@_register(
    name="add_vocabulary_terms",
    description="Add new terms to vocabulary.yaml with provenance. Respects category limits.",
    parameters={"terms": "list of {term, group, category}"},
)
def tool_add_vocabulary_terms(args: Dict, state: Dict) -> str:
    from tools.vocabulary import add_terms

    terms = args.get("terms", [])
    if not terms:
        return "No terms provided."

    added, skipped = add_terms(terms, source_label="meta-agent auto-extraction")

    lines = []
    if added:
        lines.append(f"Added {len(added)} terms: {', '.join(added)}")
    if skipped:
        lines.append(f"Skipped {len(skipped)}: {', '.join(skipped)}")
    if not added and not skipped:
        lines.append("No terms processed.")
    return "\n".join(lines)


@_register(
    name="check_source_health",
    description="Analyze source registry for cold, broken, or underperforming sources.",
    parameters={},
)
def tool_check_source_health(args: Dict, state: Dict) -> str:
    import datetime as dt

    registry = state.get("_registry") or {}
    sources = registry.get("sources", [])
    if not sources:
        return "No source registry available for this run."

    cutoff_30 = (dt.date.today() - dt.timedelta(days=30)).isoformat()
    cutoff_14 = (dt.date.today() - dt.timedelta(days=14)).isoformat()

    cold = []
    no_data = []
    healthy = []
    high_yield = []

    for s in sources:
        if not s.get("enabled", True):
            continue
        stats = s.get("stats", {})
        fetched = stats.get("total_fetched", 0)
        in_scope = stats.get("in_scope_count", 0)
        last_hit = stats.get("last_hit_date")
        name = s.get("name", s.get("id", "?"))

        if fetched == 0 and stats.get("runs", 0) > 0:
            no_data.append(name)
        elif last_hit and last_hit < cutoff_30:
            cold.append(f"{name} (last hit: {last_hit})")
        elif in_scope > 0 and fetched > 0:
            ratio = in_scope / fetched
            if ratio > 0.3:
                high_yield.append(f"{name} ({ratio:.0%} yield)")
            else:
                healthy.append(name)
        else:
            healthy.append(name)

    lines = [f"Source health ({len(sources)} total, {len(cold)+len(no_data)+len(healthy)+len(high_yield)} enabled):"]
    if cold:
        lines.append(f"  COLD (no hits 30+ days): {', '.join(cold)}")
    if no_data:
        lines.append(f"  NO DATA (fetched 0): {', '.join(no_data)}")
    if high_yield:
        lines.append(f"  HIGH YIELD: {', '.join(high_yield)}")
    if not cold and not no_data:
        lines.append("  All sources producing. No action needed.")
    return "\n".join(lines)


@_register(
    name="flag_cold_source",
    description="Disable a source that hasn't produced in-scope items recently. Curated sources are flagged but not disabled.",
    parameters={"source_id": "ID of the source to flag"},
)
def tool_flag_cold_source(args: Dict, state: Dict) -> str:
    source_id = args.get("source_id", "")
    if not source_id:
        return "ERROR: source_id is required."

    registry = state.get("_registry") or {}
    for s in registry.get("sources", []):
        if s.get("id") == source_id:
            if s.get("curated", True):
                return (f"Source '{source_id}' is curated — flagged for human review "
                        "but NOT auto-disabled. Curated sources require manual action.")
            s["enabled"] = False
            return f"Source '{source_id}' disabled. It will be skipped on next run."

    return f"Source '{source_id}' not found in registry."


@_register(
    name="assess_coverage",
    description="Summarize this week's topic coverage and identify potential blind spots.",
    parameters={},
)
def tool_assess_coverage(args: Dict, state: Dict) -> str:
    themes = state.get("themes") or []
    scored = state.get("scored_items", [])
    alerts = state.get("alerts", [])

    categories = {}
    for it in scored:
        cat = it.get("category", "unknown")
        categories[cat] = categories.get(cat, 0) + 1

    lines = [f"Coverage: {len(scored)} items scored, {len(alerts)} alerts, {len(themes)} themes"]
    lines.append(f"  Categories: {', '.join(f'{k}={v}' for k, v in sorted(categories.items(), key=lambda x: -x[1]))}")

    if themes:
        lines.append("  Themes:")
        for t in themes:
            lines.append(f"    - {t.get('name', '?')} ({t.get('significance', '?')})")

    expected = {"implantable_bci", "materials", "regulatory", "methods"}
    covered = set(categories.keys())
    missing = expected - covered
    if missing:
        lines.append(f"  Potential blind spots (no items): {', '.join(missing)}")
    else:
        lines.append("  All expected categories represented.")

    return "\n".join(lines)


@_register(
    name="discover_companies",
    description="Extract new BCI companies from high-scoring Tavily items using LLM analysis.",
    parameters={},
)
def tool_discover_companies(args: Dict, state: Dict) -> str:
    scored = state.get("scored_items", [])
    tavily_scored = [
        it for it in scored
        if it.get("source_id") == "tavily_wideband"
        and it.get("llm_score", 0) >= 6
    ]
    if not tavily_scored:
        return "No qualifying Tavily items (score >= 6) for company discovery."

    from tools.config import get_watchlist_company_names
    from tools.tavily import discover_companies
    from tools.llm import create_llm, invoke_llm

    existing = get_watchlist_company_names()
    model_name = state.get("reviewer_model") or state.get("model", "gpt-4o-mini")
    llm = create_llm(model_name)

    def llm_call(prompt: str) -> str:
        return invoke_llm(llm, prompt, node="discover_companies", model_name=model_name)

    discoveries = discover_companies(scored, existing, llm_func=llm_call)
    state.setdefault("company_discoveries", []).extend(discoveries)

    if discoveries:
        names = [d.get("name", "?") for d in discoveries]
        return f"Discovered {len(discoveries)} new companies: {', '.join(names)}. Added to discoveries list for human review."
    return "No new companies discovered in this week's results."


@_register(
    name="propose_source",
    description="Suggest a new RSS feed or Tavily query for future runs. Logged for human review.",
    parameters={"source_type": "rss or tavily", "value": "URL or query string", "reason": "why"},
)
def tool_propose_source(args: Dict, state: Dict) -> str:
    source_type = args.get("source_type", "")
    value = args.get("value", "")
    reason = args.get("reason", "")

    if not value:
        return "ERROR: value (URL or query) is required."

    return (f"Proposed new {source_type} source: {value}\n"
            f"Reason: {reason}\n"
            "Logged for human review in meta_actions output.")
