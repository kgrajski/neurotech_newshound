---
name: neuro_hound
description: MVP neurotech discovery + triage (PubMed + RSS) for implantable BCI, sEEG/ECoG, microstimulation, materials, and FDA/clinical signals.
---

## What it does
Generates a dated markdown report in `archives/neurotech/YYYY-MM-DD.md` by:
1) pulling recent PubMed items for a focused query
2) pulling RSS items (preprints + FDA safety comms if available)
3) scoring each item 1–10 (9–10 reserved for human clinical trial milestones or FDA milestones)
4) writing a concise ranked report + an alerts JSON file

## Run (manual)
From workspace root:
- `python3 skills/neuro_hound/run.py --days 7`
- Optional: `python3 skills/neuro_hound/run.py --days 1 --max 40`

## Outputs
- `archives/neurotech/YYYY-MM-DD.md`
- `archives/neurotech/YYYY-MM-DD.alerts.json` (only items scored 9–10)

## Configuration knobs (CLI)
- `--days N` : lookback window
- `--max N` : max items per source
