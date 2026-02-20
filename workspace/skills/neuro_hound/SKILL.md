---
name: neuro_hound
description: Generate this week's NeuroTech intelligence briefing
command-dispatch: tool
command-tool: exec
command-arg-mode: raw
user-invocable: true
---

# NeuroTech NewsHound — Skill Specification

> This file is the complete operational specification for the NewsHound skill.
> It describes what the agent does, how it reasons, what tools it has, and what
> constraints it operates under. A developer should be able to read this file
> alone and understand the agent's complete behavior.
>
> For agent identity and values, see `../../SOUL.md`.
> For runtime configuration, see `config.yaml` and `prompts.yaml`.

---

## Purpose

Produce a weekly intelligence briefing on the implantable BCI ecosystem by
fetching from 20+ sources, scoring items with domain-aware LLM judgment,
clustering into themes, and synthesizing an executive brief — then critically
reviewing its own output.

The briefing replaces manual scanning of dozens of journals, preprint servers,
press outlets, and regulatory feeds. A senior researcher should be able to read
the output in 5 minutes and know what mattered this week.

## Goals

### Primary: Produce the weekly briefing

1. Fetch from all configured sources (PubMed, RSS feeds, Tavily wideband)
2. Pre-filter with domain-specific regex (fast, free, deterministic)
3. Deduplicate against scored history
4. Score each candidate with LLM (1–10, category, assessment, vaporware flag)
5. Cluster scored items into 2–5 themes with significance ratings
6. Write an executive brief (TL;DR, themes, alerts, what-to-watch)
7. Review the brief via Reflection Pattern (reviewer LLM critiques and adjusts)
8. Produce HTML report, dashboard, markdown, alerts JSON, full results JSON
9. Log to MLflow (parameters, metrics, artifacts)

### Meta: Maintain and evolve source coverage

10. **Company discovery**: After scoring, extract new company names from
    high-scoring Tavily results. Write candidates to `discoveries.yaml` for
    human review and promotion to the watchlist.
11. **Domain discovery**: Track which web domains yield high-scoring items
    across runs. Propose new RSS sources when a domain is consistently valuable.
12. **Source health monitoring**: Track per-source yield (items fetched,
    in-scope count, last hit date). Flag cold sources that haven't produced
    in-scope items in 30+ days.

> **Honesty note**: Goals 10–12 are currently implemented as fixed code paths
> in the pipeline — they always run in the same way. The agent does not yet
> *reason* about whether or when to pursue these goals. This is a documented
> design gap; see `docs/ADR-001-agent-specification.md`.

## Tools Available

The skill has access to the following tools, implemented as Python modules:

| Tool | Module | Description |
|------|--------|-------------|
| PubMed fetch | `tools/pubmed.py` | NCBI E-utilities API for biomedical literature |
| RSS fetch | `tools/rss.py` | Registry-driven RSS/Atom parser for journals, preprints, press, regulatory |
| Tavily search | `tools/tavily.py` | Wideband web search with auto-generated queries from watchlist + curated sources |
| Regex scorer | `tools/scoring.py` | Domain-specific pattern matching for fast pre-filtering |
| Dedup history | `tools/dedup.py` | Hash-based history to skip confirmed low-value repeats |
| LLM | `tools/llm.py` | Multi-model LLM factory (GPT-4o-mini, GPT-4o, Gemini, Claude) with usage tracking |
| Config loader | `tools/config.py` | Reads config.yaml, prompts.yaml, watchlist, curated sources |
| Source registry | `tools/sources.py` | JSON-persisted source stats (yield, last hit, health) |
| HTML report | `tools/html_report.py` | Polished HTML intelligence briefing generator |
| Dashboard | `tools/html_dashboard.py` | Operational dashboard (source health, config, run metrics) |
| MLflow logger | `tools/mlflow_tracker.py` | Experiment tracking (params, metrics, artifacts per run) |

## Workflow

```
fetch_pubmed → fetch_rss → fetch_tavily → save_registry
    → prefilter (regex + dedup)
    → [conditional: skip LLM if nothing in-scope]
    → score_items (LLM × N items)
    → summarize_themes (cluster + significance)
    → write_brief (executive briefing)
    → review (Reflection Pattern + dedup update + company discovery)
    → outputs (HTML, dashboard, markdown, JSON, MLflow)
```

Implemented as a LangGraph `StateGraph` with a conditional edge after
pre-filtering: if nothing passes regex, the LLM pipeline is skipped entirely
(no API cost on quiet weeks).

## Scoring Criteria

Items are scored 1–10 by the LLM using criteria defined in `prompts.yaml`:

| Score | Meaning | Examples |
|-------|---------|----------|
| 9–10 | Priority alert | First-in-human implant, FDA IDE/PMA/De Novo, pivotal trial |
| 7–8 | High signal | ECoG/sEEG study, single-unit data, closed-loop BCI |
| 5–6 | Moderate | Materials/biocompatibility, animal BCI, neural decoding |
| 3–4 | Low | Tangentially related neuroscience |
| 1–2 | Out of scope | Scalp EEG wearables, oncology, marketing |

Categories: `implantable_bci` · `ecog_seeg` · `stimulation` · `materials` ·
`regulatory` · `funding` · `animal_study` · `methods` · `out_of_scope`

## Behavioral Constraints

These are inherited from SOUL.md and enforced in prompts and code:

- **No hallucination.** If a source isn't found, say so. Never fabricate links.
- **Peer-reviewed over press releases.** Prefer primary literature. Flag
  vaporware and marketing.
- **Verify before alerting.** Priority 9–10 alerts only for human clinical
  milestones or FDA regulatory milestones.
- **Evidence-based opinions.** Have opinions on scientific validity, but ground
  them in what the data actually says.
- **Concise over comprehensive.** The executive brief should be readable in
  5 minutes. Details go in the scored items list.

## Self-Assessment

After each run, the review node evaluates:

1. Are significance assessments calibrated? (Overhyped or underappreciated?)
2. Are items correctly categorized? Any miscategorizations?
3. Did the analyst miss themes or connections between items?
4. Any vaporware or marketing that slipped through?
5. Which 1–3 items are genuinely most important this week?

The reviewer can adjust scores, flag missed signals, and call out vaporware.
Quality score (1–10) is logged to MLflow for tracking over time.

## Configuration

All runtime parameters live in two YAML files (no code edits needed):

**`config.yaml`** — Sources, models, company watchlist, curated industry
sources, Tavily queries, MLflow settings. This is the single source of truth
for what the agent monitors and how.

**`prompts.yaml`** — All LLM prompts as templates with `{variable}`
placeholders. Edit here to iterate on analysis quality. Prompt text is logged
to MLflow for A/B tracking.

### Company Watchlist (config.yaml)

Tracked companies get automatic Tavily queries and RSS feeds (if Substack URL
provided). New companies can be added manually or promoted from
`discoveries.yaml` (auto-generated after each run).

### Curated Industry Sources (config.yaml)

Websites without RSS (e.g., Neurofounders, IEEE Spectrum) are searched via
Tavily `site:` queries.

## Invocation

```bash
# Full pipeline
python3 skills/neuro_hound/run.py --days 7

# Phase 1 only (regex scoring, no LLM cost)
python3 skills/neuro_hound/run.py --days 7 --phase1-only

# With specific models
python3 skills/neuro_hound/run.py --days 7 --model gpt-4o --reviewer gpt-4o

# From Telegram (via OpenClaw)
/neuro_hound --days 7
```

## Outputs

| File | Description |
|------|-------------|
| `YYYY-MM-DD.html` | Polished HTML intelligence briefing |
| `dashboard.html` | Operational dashboard (source health, config, metrics) |
| `YYYY-MM-DD.md` | Markdown report with executive brief |
| `YYYY-MM-DD.alerts.json` | Priority items (score 9–10) |
| `YYYY-MM-DD.full.json` | Full results + usage metrics |
| `discoveries.yaml` | Candidate companies for watchlist promotion |

## Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| `OPENAI_API_KEY` | Yes | For GPT models |
| `TAVILY_API_KEY` | Optional | For Tavily wideband search |
| `GOOGLE_API_KEY` | Optional | For Gemini models |
| `ANTHROPIC_API_KEY` | Optional | For Claude models |

## Evolution

| Level | Description | Status |
|-------|-------------|--------|
| Procedural pipeline | Fixed workflow, LLM calls at certain steps | **Current** |
| Workflow with agency | LLM decides within nodes (conditional paths, tool selection) | Partial (conditional edge) |
| Agentic meta-layer | Agent reasons about its own coverage, decides when to discover/prune | Design goal |
| Self-modifying | Agent reads SOUL.md/SKILL.md, reasons about goals, updates config | Future |

See `docs/ADR-001-agent-specification.md` for the full architecture rationale.
