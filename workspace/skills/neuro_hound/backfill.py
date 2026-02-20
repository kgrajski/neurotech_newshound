#!/usr/bin/env python3
"""
NeuroTech NewsHound — Historical Backfill (Phase 8)

Fetches BCI literature going back 5 years from PubMed, bioRxiv, medRxiv,
and arXiv. Applies regex scoring (no LLM — too expensive for thousands of
items). Stores results in dedup history and a backfill archive JSON.

Usage:
    python3 backfill.py
    python3 backfill.py --start-year 2023 --end-year 2026
    python3 backfill.py --sources pubmed           # PubMed only
    python3 backfill.py --sources pubmed,arxiv      # PubMed + arXiv
    python3 backfill.py --dry-run                   # Fetch but don't update dedup

Progress is printed to stdout in real-time. The full run may take 30-60
minutes depending on API response times and rate limiting.
"""
import argparse
import datetime as dt
import json
import os
import sys
import time

# Ensure the skill directory is on the path
skill_dir = os.path.dirname(os.path.abspath(__file__))
if skill_dir not in sys.path:
    sys.path.insert(0, skill_dir)

from dotenv import load_dotenv
load_dotenv()


def run_backfill(args):
    from tools.scoring import regex_score, is_in_scope
    from tools.dedup import load_history, save_history, update_history, _item_hash
    from tools.vocabulary import get_vocabulary_stats

    start_time = time.time()
    today = dt.date.today().isoformat()
    sources = [s.strip() for s in args.sources.split(",")]

    # Output directory
    out_dir = args.output_dir or os.path.join(
        os.path.dirname(os.path.dirname(skill_dir)),
        "archives", "neurotech", "backfill"
    )
    os.makedirs(out_dir, exist_ok=True)

    print("=" * 70)
    print("NEUROTECH NEWSHOUND — HISTORICAL BACKFILL")
    print("=" * 70)
    print(f"  Date range:  {args.start_year} → {args.end_year}")
    print(f"  Sources:     {', '.join(sources)}")
    print(f"  Regex threshold: {args.regex_threshold} (items below this are discarded)")
    print(f"  Dry run:     {args.dry_run}")
    print(f"  Output:      {out_dir}")
    print()

    # Show vocabulary stats
    stats = get_vocabulary_stats()
    print(f"  Vocabulary:  {stats['totals']['grand_total']} terms "
          f"({stats['totals']['primary']} primary, {stats['totals']['qualifier']} qualifier)")
    print()

    all_items = []
    source_counts = {}

    # ── PubMed ──────────────────────────────────────────────────────
    if "pubmed" in sources:
        print("─" * 70)
        print("SOURCE: PubMed (NCBI E-utilities)")
        print("─" * 70)
        from tools.pubmed import fetch_pubmed_backfill
        try:
            items = fetch_pubmed_backfill(
                start_year=args.start_year,
                end_year=args.end_year,
                chunk_months=6,
                max_per_chunk=500,
            )
            source_counts["pubmed"] = len(items)
            all_items.extend(items)
            print(f"  ✓ PubMed total: {len(items)} items")
        except Exception as e:
            print(f"  ✗ PubMed failed: {e}")
            source_counts["pubmed"] = 0
        print()

    # ── bioRxiv ─────────────────────────────────────────────────────
    if "biorxiv" in sources:
        print("─" * 70)
        print("SOURCE: bioRxiv (content API, client-side filtering)")
        print("─" * 70)
        from tools.biorxiv import fetch_biorxiv_backfill
        try:
            items = fetch_biorxiv_backfill(
                server="biorxiv",
                start_year=args.start_year,
                end_year=args.end_year,
                chunk_months=args.chunk_months,
                max_pages_per_chunk=args.max_pages,
            )
            source_counts["biorxiv"] = len(items)
            all_items.extend(items)
            print(f"  ✓ bioRxiv total: {len(items)} in-scope items")
        except Exception as e:
            print(f"  ✗ bioRxiv failed: {e}")
            source_counts["biorxiv"] = 0
        print()

    # ── medRxiv ─────────────────────────────────────────────────────
    if "medrxiv" in sources:
        print("─" * 70)
        print("SOURCE: medRxiv (content API, client-side filtering)")
        print("─" * 70)
        from tools.biorxiv import fetch_biorxiv_backfill
        try:
            items = fetch_biorxiv_backfill(
                server="medrxiv",
                start_year=args.start_year,
                end_year=args.end_year,
                chunk_months=args.chunk_months,
                max_pages_per_chunk=args.max_pages,
            )
            source_counts["medrxiv"] = len(items)
            all_items.extend(items)
            print(f"  ✓ medRxiv total: {len(items)} in-scope items")
        except Exception as e:
            print(f"  ✗ medRxiv failed: {e}")
            source_counts["medrxiv"] = 0
        print()

    # ── arXiv ───────────────────────────────────────────────────────
    if "arxiv" in sources:
        print("─" * 70)
        print("SOURCE: arXiv (search API)")
        print("─" * 70)
        from tools.arxiv import fetch_arxiv_backfill
        try:
            items = fetch_arxiv_backfill(max_results=args.arxiv_max)
            source_counts["arxiv"] = len(items)
            all_items.extend(items)
            print(f"  ✓ arXiv total: {len(items)} items")
        except Exception as e:
            print(f"  ✗ arXiv failed: {e}")
            source_counts["arxiv"] = 0
        print()

    # ── Regex Scoring ───────────────────────────────────────────────
    print("─" * 70)
    print("SCORING: Regex pre-filter")
    print("─" * 70)
    scored = []
    discarded = 0
    for item in all_items:
        title = item.get("title", "")
        summary = item.get("summary", "")
        source = item.get("source", "")

        if is_in_scope(title, summary, source):
            score = regex_score(title, summary, source)
            item["score"] = score
            if score >= args.regex_threshold:
                scored.append(item)
            else:
                discarded += 1
        else:
            discarded += 1

    scored.sort(key=lambda x: x.get("score", 0), reverse=True)

    score_dist = {}
    for item in scored:
        s = item.get("score", 0)
        score_dist[s] = score_dist.get(s, 0) + 1

    print(f"  Total fetched:     {len(all_items)}")
    print(f"  Passed threshold:  {len(scored)} (regex >= {args.regex_threshold})")
    print(f"  Discarded:         {discarded}")
    print(f"  Score distribution: {', '.join(f'{k}={v}' for k, v in sorted(score_dist.items(), reverse=True))}")
    print()

    # ── Deduplication History Update ────────────────────────────────
    if not args.dry_run:
        print("─" * 70)
        print("DEDUP: Updating seen_items.json")
        print("─" * 70)
        history = load_history()
        before = len(history)

        for item in scored:
            h = _item_hash(item.get("title", ""), item.get("url", ""))
            item["_hash"] = h

        update_history(history, scored)
        save_history(history)
        after = len(history)
        print(f"  Before: {before} items | After: {after} items | New: {after - before}")
        print()

    # ── Write Backfill Archive ──────────────────────────────────────
    print("─" * 70)
    print("OUTPUT: Writing backfill archive")
    print("─" * 70)
    duration = time.time() - start_time

    archive = {
        "backfill_date": today,
        "start_year": args.start_year,
        "end_year": args.end_year,
        "sources": sources,
        "regex_threshold": args.regex_threshold,
        "source_counts": source_counts,
        "total_fetched": len(all_items),
        "total_scored": len(scored),
        "score_distribution": score_dist,
        "duration_seconds": round(duration, 1),
        "items": scored,
    }

    archive_path = os.path.join(out_dir, f"backfill_{today}.json")
    with open(archive_path, "w") as f:
        json.dump(archive, f, indent=2, default=str)
    print(f"  Archive: {archive_path}")

    # Top items summary
    top_path = os.path.join(out_dir, f"backfill_{today}_top.md")
    with open(top_path, "w") as f:
        f.write(f"# Backfill Top Items — {today}\n\n")
        f.write(f"Date range: {args.start_year}–{args.end_year}\n")
        f.write(f"Sources: {', '.join(sources)}\n")
        f.write(f"Total scored: {len(scored)} (regex >= {args.regex_threshold})\n\n")
        for item in scored[:100]:
            f.write(f"### [{item.get('score', '?')}] {item.get('title', '')[:120]}\n")
            f.write(f"- Source: {item.get('source', '')} | {item.get('meta', '')[:80]}\n")
            if item.get("url"):
                f.write(f"- URL: {item['url']}\n")
            f.write("\n")
    print(f"  Top items: {top_path}")

    # ── Summary ─────────────────────────────────────────────────────
    print()
    print("=" * 70)
    print("BACKFILL COMPLETE")
    print("=" * 70)
    print(f"  Duration:    {duration:.0f}s ({duration/60:.1f} min)")
    print(f"  Fetched:     {len(all_items)} items from {len(source_counts)} sources")
    for src, count in sorted(source_counts.items()):
        print(f"    {src}: {count}")
    print(f"  Scored:      {len(scored)} items (regex >= {args.regex_threshold})")
    if scored:
        print(f"  Top score:   {scored[0].get('score', '?')} — {scored[0].get('title', '')[:80]}")
    print(f"  Archive:     {archive_path}")
    if not args.dry_run:
        print(f"  Dedup updated: seen_items.json")
    print("=" * 70)


def main():
    ap = argparse.ArgumentParser(
        description="NeuroTech NewsHound — Historical Backfill (Phase 8)"
    )
    ap.add_argument(
        "--start-year", type=int, default=2021,
        help="Start year for backfill (default: 2021)"
    )
    ap.add_argument(
        "--end-year", type=int, default=2026,
        help="End year for backfill (default: 2026)"
    )
    ap.add_argument(
        "--sources", type=str, default="pubmed,biorxiv,medrxiv,arxiv",
        help="Comma-separated sources (default: pubmed,biorxiv,medrxiv,arxiv)"
    )
    ap.add_argument(
        "--regex-threshold", type=int, default=5,
        help="Minimum regex score to keep (default: 5)"
    )
    ap.add_argument(
        "--chunk-months", type=int, default=3,
        help="bioRxiv/medRxiv chunk size in months (default: 3)"
    )
    ap.add_argument(
        "--max-pages", type=int, default=100,
        help="Max API pages per bioRxiv/medRxiv chunk (default: 100)"
    )
    ap.add_argument(
        "--arxiv-max", type=int, default=2000,
        help="Max arXiv results to fetch (default: 2000)"
    )
    ap.add_argument(
        "--output-dir", type=str, default=None,
        help="Output directory for backfill archive"
    )
    ap.add_argument(
        "--dry-run", action="store_true",
        help="Fetch and score but don't update dedup history"
    )
    args = ap.parse_args()
    run_backfill(args)


if __name__ == "__main__":
    main()
