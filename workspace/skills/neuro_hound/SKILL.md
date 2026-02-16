---
name: neuro_hound
description: Agentic neurotech research intelligence — LangGraph pipeline with LLM scoring, thematic synthesis, and reflection for implantable BCI, sEEG/ECoG, microstimulation, materials, and FDA/clinical signals.
---

## What it does
Generates a dated intelligence briefing by:
1) Fetching recent PubMed items and bioRxiv/medRxiv RSS preprints
2) Pre-filtering with regex for in-scope neurotech items (fast, free)
3) LLM-scoring each candidate with domain-aware assessment (score 1-10, category, reasoning)
4) Clustering scored items into 2-5 themes with significance assessment
5) Writing an executive brief (TL;DR, themes, alerts, what-to-watch)
6) Reflection: reviewer LLM critiques the brief and adjusts scores

## Architecture
```
fetch_pubmed → fetch_rss → prefilter (regex)
    → [conditional: skip if empty]
    → score_items (LLM per-item)
    → summarize_themes (LLM)
    → write_brief (LLM)
    → review (LLM reflection)
```

## Run (manual)
From workspace root:
- Full pipeline: `python3 skills/neuro_hound/run.py --days 7`
- Custom model: `python3 skills/neuro_hound/run.py --days 7 --model gpt-4o-mini`
- Phase 1 only (no LLM): `python3 skills/neuro_hound/run.py --days 7 --phase1-only`

## Outputs
- `archives/neurotech/YYYY-MM-DD.md` — Full report with executive brief
- `archives/neurotech/YYYY-MM-DD.alerts.json` — Items scored 9-10
- `archives/neurotech/YYYY-MM-DD.full.json` — Machine-readable results + usage metrics

## Configuration knobs (CLI)
- `--days N` : lookback window (default: 7)
- `--max N` : max items per source (default: 40)
- `--model NAME` : LLM for scoring/synthesis (default: gpt-4o-mini)
- `--reviewer NAME` : LLM for reflection review (default: same as model)
- `--phase1-only` : regex scoring only, skip LLM pipeline
- `--output-dir PATH` : override output directory

## Environment Variables
- `HOUND_LLM_MODEL` : default model (overridden by --model)
- `HOUND_REVIEWER_MODEL` : default reviewer model
- `GOOGLE_API_KEY` : for Gemini models
- `OPENAI_API_KEY` : for GPT models
