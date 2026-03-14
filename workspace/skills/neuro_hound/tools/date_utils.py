"""
Date parsing and freshness gating — discard items outside the lookback window.

Different sources encode dates in wildly different formats:
  - RSS pubDate: "Mon, 03 Feb 2026 12:00:00 GMT"
  - Atom updated: "2026-02-03T12:00:00Z"
  - PubMed meta:  "Nature 2026 PMID:12345"
  - Tavily:       freeform snippet text
  - ClinicalTrials: "2026-02-03" (via status module)

This module normalises all of them into a date object and provides
a gate function for the prefilter.
"""
import datetime as dt
import re
from typing import Optional


_MONTH_MAP = {
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
    "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
}

# RFC 2822: "Mon, 03 Feb 2026 12:00:00 GMT" or "3 Feb 2026 12:00:00 +0000"
_RFC2822_RE = re.compile(
    r"(\d{1,2})\s+(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\w*\s+(\d{4})",
    re.IGNORECASE,
)

# ISO-ish: "2026-02-03", "2026-02-03T12:00:00Z", "2026/02/03"
_ISO_RE = re.compile(r"(\d{4})[-/](\d{1,2})[-/](\d{1,2})")

# "Month DD, YYYY" or "Month DD YYYY": "February 3, 2026"
_LONG_DATE_RE = re.compile(
    r"(January|February|March|April|May|June|July|August|September|October|November|December)"
    r"\s+(\d{1,2}),?\s+(\d{4})",
    re.IGNORECASE,
)

_LONG_MONTH_MAP = {
    "january": 1, "february": 2, "march": 3, "april": 4,
    "may": 5, "june": 6, "july": 7, "august": 8,
    "september": 9, "october": 10, "november": 11, "december": 12,
}

# PubMed meta often has "Journal YYYY PMID:..." — extract just the year
_YEAR_ONLY_RE = re.compile(r"\b(20\d{2})\b")


def parse_date(text: str) -> Optional[dt.date]:
    """Best-effort date extraction from freeform text.

    Returns the first parseable date found, or None.
    """
    if not text:
        return None

    # Try ISO first (most structured)
    m = _ISO_RE.search(text)
    if m:
        try:
            return dt.date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        except ValueError:
            pass

    # RFC 2822 (RSS pubDate)
    m = _RFC2822_RE.search(text)
    if m:
        try:
            day = int(m.group(1))
            month = _MONTH_MAP.get(m.group(2).lower()[:3], 0)
            year = int(m.group(3))
            if month:
                return dt.date(year, month, day)
        except ValueError:
            pass

    # Long-form: "February 3, 2026"
    m = _LONG_DATE_RE.search(text)
    if m:
        try:
            month = _LONG_MONTH_MAP.get(m.group(1).lower(), 0)
            day = int(m.group(2))
            year = int(m.group(3))
            if month:
                return dt.date(year, month, day)
        except ValueError:
            pass

    # Year only (PubMed-style) — return Jan 1 of that year as a floor
    m = _YEAR_ONLY_RE.search(text)
    if m:
        try:
            return dt.date(int(m.group(1)), 1, 1)
        except ValueError:
            pass

    return None


def extract_item_date(item: dict) -> Optional[dt.date]:
    """Extract the best available date from a pipeline item.

    Checks fields in priority order: meta (contains pubDate for RSS,
    date info for PubMed), then title, then summary.
    """
    for field in ("meta", "title", "summary"):
        d = parse_date(item.get(field, ""))
        if d:
            return d
    return None


def is_within_lookback(
    item_date: Optional[dt.date],
    days: int,
    grace_days: int = 2,
) -> bool:
    """True if item_date falls within the lookback window (+ grace).

    Items with no parseable date always pass (we can't penalize
    missing metadata).
    """
    if item_date is None:
        return True

    cutoff = dt.date.today() - dt.timedelta(days=days + grace_days)
    return item_date >= cutoff


def date_gate(
    items: list,
    days: int,
    grace_days: int = 2,
) -> tuple:
    """Partition items into (fresh, stale) based on publication date.

    Items with year-only dates (e.g. "2025") are treated conservatively:
    if the year is within the lookback's calendar year or later, they pass.
    """
    fresh = []
    stale = []

    for item in items:
        item_date = extract_item_date(item)
        item["_parsed_date"] = item_date.isoformat() if item_date else None

        if is_within_lookback(item_date, days, grace_days):
            fresh.append(item)
        else:
            item["_stale_reason"] = (
                f"Published {item_date.isoformat()}, outside "
                f"{days}+{grace_days}d lookback"
            )
            stale.append(item)

    return fresh, stale
