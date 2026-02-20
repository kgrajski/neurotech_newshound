"""LLM-based scoring node — per-item qualitative assessment."""
import textwrap

from state import HoundState
from tools.llm import create_llm, invoke_llm, parse_json
from tools.config import get_prompt, get_agent_domain

FALLBACK_SCORE_PROMPT = """You are a senior neurotechnology research analyst specializing in {domain}.

Score this research item for relevance to the NeuroTech field.

TITLE: {title}
SOURCE: {source}
META: {meta}
ABSTRACT/SUMMARY: {summary}

SCORING CRITERIA (from most to least significant):
- 9-10: Human implant/first-in-human, FDA milestone (IDE/PMA/De Novo), pivotal clinical trial
- 7-8: ECoG/sEEG/iEEG recording, single-unit/spiking data, microstimulation, closed-loop BCI
- 5-6: Materials/biocompatibility, animal BCI studies, neural decoding methods
- 3-4: Tangentially related neuroscience (not BCI/implant focused)
- 1-2: Out of scope (scalp EEG wearables, marketing, unrelated clinical)

IMPORTANT:
- If this is NOT about implantable neural interfaces, intracranial recording, or BCI, score it LOW (1-3) regardless of regex matches
- Prefer peer-reviewed work over press releases
- If it smells like vaporware or marketing, say so

Respond in JSON:
{{"score": <1-10>,
 "category": "<implantable_bci|ecog_seeg|stimulation|materials|regulatory|funding|animal_study|methods|out_of_scope>",
 "assessment": "<1-2 sentences: what this is and why it matters or doesn't>",
 "vaporware": <true/false>}}"""


def score_items(state: HoundState) -> HoundState:
    """
    Score each pre-filtered item using LLM with domain understanding.

    Prompt is loaded from prompts.yaml with fallback to hardcoded default.
    """
    items = state["prefiltered_items"]
    if not items:
        state["scored_items"] = []
        state["alerts"] = []
        return state

    print(f"  LLM-scoring {len(items)} items with {state['model']}...")
    llm = create_llm(state["model"])
    scored = []

    prompt_template = get_prompt("score_item", FALLBACK_SCORE_PROMPT)
    domain = get_agent_domain()

    for i, item in enumerate(items):
        title = item.get("title", "")
        summary = textwrap.shorten(item.get("summary", ""), width=600, placeholder="...")
        source = item.get("source", "")
        meta = item.get("meta", "")

        prompt = prompt_template.format(
            title=title, source=source, meta=meta,
            summary=summary, domain=domain,
        )

        try:
            content = invoke_llm(llm, prompt, node=f"score_{i}", model_name=state["model"])
            result = parse_json(content)
            scored.append({
                **item,
                "llm_score": result.get("score", 4),
                "category": result.get("category", "unknown"),
                "assessment": result.get("assessment", ""),
                "vaporware": result.get("vaporware", False),
            })
            score = result.get("score", "?")
            cat = result.get("category", "?")
            print(f"    [{score}] {cat}: {title[:60]}")
        except Exception as e:
            state["errors"].append(f"Score item {i}: {e}")
            scored.append({
                **item,
                "llm_score": item.get("regex_score", 4),
                "category": "error",
                "assessment": f"Scoring failed: {e}",
                "vaporware": False,
            })

    # Sort by LLM score descending
    scored.sort(key=lambda x: x.get("llm_score", 0), reverse=True)
    state["scored_items"] = scored
    state["alerts"] = [x for x in scored if x.get("llm_score", 0) >= 9]

    print(f"  Scored: {len(scored)} items | Alerts: {len(state['alerts'])}")
    return state
