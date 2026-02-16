---
name: neuro_hound
description: Generate this week's NeuroTech intelligence briefing
command-dispatch: tool
command-tool: exec
command-arg-mode: raw
user-invocable: true
---

## What it does
NeuroTech NewsHound — agentic research intelligence for the NeuroTech ecosystem.

Generates a dated intelligence briefing by:
1) Fetching from 21 sources — PubMed, journal RSS (Nature, Science, Neuron, NEJM, ...), preprints (bioRxiv, medRxiv, arXiv), press (NYT, FT, STAT), FDA, and Tavily wideband search
2) Pre-filtering with regex for in-scope neurotech items (fast, free)
3) Deduplicating against previously-scored items
4) LLM-scoring each candidate (score 1-10, category, reasoning)
5) Clustering into themes with significance assessment
6) Writing an executive brief
7) Reflection: reviewer LLM critiques and adjusts scores
8) Producing HTML report, dashboard, markdown, alerts JSON, MLflow logs

## Use
From Telegram: `/neuro_hound --days 7`

Arguments (all optional):
- `--days N` — lookback window (default: 7)
- `--phase1-only` — regex scoring only, no LLM cost
- `--model NAME` — LLM model (default: gpt-4o-mini)

## Outputs
- `archives/neurotech/YYYY-MM-DD.html` — HTML intelligence briefing
- `archives/neurotech/dashboard.html` — Operational dashboard
- `archives/neurotech/YYYY-MM-DD.md` — Markdown report
- `archives/neurotech/YYYY-MM-DD.alerts.json` — Priority items (score 9-10)
- `archives/neurotech/YYYY-MM-DD.full.json` — Full results + usage metrics

## Configuration
All settings in `config.yaml` — sources, models, Tavily queries, MLflow.

## Environment Variables
- `OPENAI_API_KEY` — for GPT models (required)
- `TAVILY_API_KEY` — for Tavily wideband search (optional)
- `GOOGLE_API_KEY` — for Gemini models (optional)
