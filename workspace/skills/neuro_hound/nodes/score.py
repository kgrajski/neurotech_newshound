"""LLM-based scoring node — per-item qualitative assessment."""
import re
import textwrap
from datetime import datetime, timedelta

from state import HoundState
from tools.llm import create_llm, invoke_llm, parse_json
from tools.config import get_prompt, get_agent_domain

_EVERGREEN_TYPES = {"evergreen_page", "company_page"}
_REVIEW_TYPES = {"review_article"}
_STALE_MONTHS = 6
_EVERGREEN_CAP = 5
_REVIEW_CAP = 6
_STALE_PENALTY = 2

FALLBACK_SCORE_PROMPT = """You are a senior neurotechnology research analyst specializing in {domain}.

Score this research item for relevance AND freshness to the NeuroTech field.

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

FRESHNESS — CRITICAL:
- Estimate the content_type: "research_paper", "news_article", "press_release", "clinical_trial", "conference", "evergreen_page", or "company_page"
- Company "About" pages, product pages, and permanent institutional pages are "evergreen_page" or "company_page" — cap these at score 5 maximum
- If you can estimate when published, provide estimated_date as "YYYY-MM" or "YYYY"
- Items older than 6 months should lose 2-3 points

Respond in JSON:
{{"score": <1-10>,
 "category": "<implantable_bci|ecog_seeg|stimulation|materials|regulatory|funding|animal_study|methods|out_of_scope>",
 "content_type": "<research_paper|news_article|press_release|clinical_trial|conference|evergreen_page|company_page|review_article>",
 "estimated_date": "<YYYY-MM or YYYY or null if unknown>",
 "assessment": "<1-2 sentences: what this is and why it matters or doesn't>",
 "vaporware": <true/false>}}"""


def _parse_estimated_date(raw: str | None) -> datetime | None:
    """Best-effort parse of LLM-estimated date ('YYYY-MM', 'YYYY', or None)."""
    if not raw or raw == "null":
        return None
    raw = str(raw).strip()
    m = re.match(r'^(\d{4})-(\d{1,2})$', raw)
    if m:
        return datetime(int(m.group(1)), int(m.group(2)), 1)
    m = re.match(r'^(\d{4})$', raw)
    if m:
        return datetime(int(m.group(1)), 6, 1)  # mid-year estimate
    return None


def _extract_year_from_url(url: str) -> int | None:
    """Extract publication year from URL patterns (DOIs, journal paths, PIIs)."""
    if not url:
        return None
    # DOI with year: 10.xxxx/something.2021.xxxxx or /j.copbio.2021.10.001
    m = re.search(r'\.(\d{4})\.', url)
    if m:
        yr = int(m.group(1))
        if 2000 <= yr <= 2030:
            return yr
    # Path segment like /2021/ or /2022/
    m = re.search(r'/(\d{4})/', url)
    if m:
        yr = int(m.group(1))
        if 2000 <= yr <= 2030:
            return yr
    return None


def _enforce_freshness(item: dict, now: datetime | None = None) -> dict:
    """Apply deterministic score caps based on content_type and estimated_date.

    The LLM extracts metadata but doesn't reliably self-enforce penalties.
    This function applies them in code so they can't be skipped.

    Date-based penalties use a tiered trust model:
      1. _parsed_date (from source metadata) — highly reliable, full penalty
      2. URL-extracted year — moderately reliable, full penalty
      3. LLM estimate — unreliable (models default to training cutoff);
         only penalize if the estimate is >3 years old, where even a wrong
         guess strongly suggests the content is genuinely not recent
    """
    now = now or datetime.utcnow()
    score = item.get("llm_score", 0)
    content_type = item.get("content_type", "unknown")
    original_score = score
    reasons = []

    if content_type in _EVERGREEN_TYPES and score > _EVERGREEN_CAP:
        score = _EVERGREEN_CAP
        reasons.append(f"evergreen/company page capped at {_EVERGREEN_CAP}")

    if content_type in _REVIEW_TYPES and score > _REVIEW_CAP:
        score = _REVIEW_CAP
        reasons.append(f"review article capped at {_REVIEW_CAP}")

    # Tiered date signals: pick the most reliable available
    parsed_date = item.get("_parsed_date")
    url_year = _extract_year_from_url(item.get("url", ""))
    llm_est = _parse_estimated_date(item.get("estimated_date"))

    reliable_date = None
    date_source = None

    if parsed_date:
        try:
            reliable_date = datetime.fromisoformat(str(parsed_date))
            date_source = "source metadata"
        except (ValueError, TypeError):
            pass

    if not reliable_date and url_year:
        reliable_date = datetime(url_year, 6, 1)
        date_source = "url"

    # LLM estimates only trusted when they indicate old content (>30mo).
    # Models often default to their training cutoff (e.g. "2023-10") for
    # recent items they can't date. Bare-year estimates like "2023" parse
    # to mid-year (~34mo) and correctly trigger the penalty.
    _LLM_TRUST_THRESHOLD_MONTHS = 30
    if not reliable_date and llm_est:
        llm_age_months = (now.year - llm_est.year) * 12 + (now.month - llm_est.month)
        if llm_age_months > _LLM_TRUST_THRESHOLD_MONTHS:
            reliable_date = llm_est
            date_source = "llm estimate"

    if reliable_date and (now - reliable_date) > timedelta(days=_STALE_MONTHS * 30):
        age_months = (now.year - reliable_date.year) * 12 + (now.month - reliable_date.month)
        penalty = _STALE_PENALTY if age_months < 24 else _STALE_PENALTY + 1
        new_score = max(score - penalty, 1)
        if new_score < score:
            reasons.append(f"~{age_months}mo old ({date_source}), -{score - new_score}pts")
            score = new_score

    if score != original_score:
        item["_original_llm_score"] = original_score
        item["_freshness_adjustment"] = "; ".join(reasons)
        item["llm_score"] = score

    return item


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
            entry = {
                **item,
                "llm_score": result.get("score", 4),
                "category": result.get("category", "unknown"),
                "content_type": result.get("content_type", "unknown"),
                "estimated_date": result.get("estimated_date"),
                "assessment": result.get("assessment", ""),
                "vaporware": result.get("vaporware", False),
            }
            entry = _enforce_freshness(entry)
            scored.append(entry)
            score = entry.get("llm_score", "?")
            cat = entry.get("category", "?")
            adj = f" (was {entry['_original_llm_score']}: {entry['_freshness_adjustment']})" if "_freshness_adjustment" in entry else ""
            print(f"    [{score}] {cat}: {title[:60]}{adj}")
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
