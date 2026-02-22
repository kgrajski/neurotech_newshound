"""ClinicalTrials.gov API v2 fetch — searches for BCI/neurotech-related trials.

Uses the public REST API (no key required). Queries by condition/term with a
date window, returning recently-updated studies as standardized items for the
pipeline's pre-filter and scoring stages.

API docs: https://clinicaltrials.gov/data-api/api
"""
import datetime as dt
import json
import urllib.parse
from typing import Any, Dict, List

from tools.http import http_get, safe_text

API_BASE = "https://clinicaltrials.gov/api/v2/studies"

SEARCH_TERMS = (
    "brain-computer interface OR neural prosthesis OR brain implant "
    "OR ECoG OR intracortical OR neurostimulation OR neural interface "
    "OR deep brain stimulation OR cochlear implant OR retinal prosthesis "
    "OR BCI OR stentrode OR neuroprosthetic"
)

FIELDS = (
    "NCTId,BriefTitle,BriefSummary,Condition,OverallStatus,"
    "LastUpdatePostDate,LeadSponsorName,Phase"
)


def _build_url(days: int, page_size: int = 50, page_token: str = "") -> str:
    end = dt.date.today()
    start = end - dt.timedelta(days=days)
    date_filter = (
        f"AREA[LastUpdatePostDate]RANGE"
        f"[{start.strftime('%Y-%m-%d')},{end.strftime('%Y-%m-%d')}]"
    )
    params = {
        "query.cond": SEARCH_TERMS,
        "filter.advanced": date_filter,
        "format": "json",
        "pageSize": str(page_size),
        "fields": FIELDS,
        "sort": "LastUpdatePostDate:desc",
        "countTotal": "true",
    }
    if page_token:
        params["pageToken"] = page_token
    return f"{API_BASE}?{urllib.parse.urlencode(params)}"


def _parse_study(study: dict) -> Dict[str, Any]:
    proto = study.get("protocolSection", {})
    ident = proto.get("identificationModule", {})
    status = proto.get("statusModule", {})
    desc = proto.get("descriptionModule", {})
    sponsor = proto.get("sponsorCollaboratorsModule", {})
    conds = proto.get("conditionsModule", {})

    nct_id = ident.get("nctId", "")
    title = safe_text(ident.get("briefTitle", ""))
    summary = safe_text(desc.get("briefSummary", ""))
    overall_status = status.get("overallStatus", "")
    conditions = ", ".join(conds.get("conditions", []))
    lead = sponsor.get("leadSponsor", {}).get("name", "")

    last_update = ""
    lup = status.get("lastUpdatePostDateStruct", {})
    if lup:
        last_update = lup.get("date", "")

    meta_parts = [f"Status: {overall_status}"]
    if conditions:
        meta_parts.append(f"Conditions: {conditions}")
    if lead:
        meta_parts.append(f"Sponsor: {lead}")

    return {
        "source": "ClinicalTrials.gov",
        "title": title,
        "summary": summary,
        "meta": safe_text(" | ".join(meta_parts)),
        "url": f"https://clinicaltrials.gov/study/{nct_id}" if nct_id else "",
    }


def fetch_clinicaltrials_items(
    days: int = 7, max_items: int = 50
) -> List[Dict[str, Any]]:
    """Fetch recently-updated clinical trials matching BCI/neurotech terms."""
    page_size = min(max_items, 100)
    url = _build_url(days, page_size)

    try:
        raw = http_get(url, timeout=30)
        data = json.loads(raw)
    except Exception as e:
        raise RuntimeError(f"ClinicalTrials.gov API error: {e}") from e

    studies = data.get("studies", [])
    total = data.get("totalCount", len(studies))
    items = [_parse_study(s) for s in studies]

    next_token = data.get("nextPageToken")
    while next_token and len(items) < max_items:
        url = _build_url(days, page_size, next_token)
        try:
            raw = http_get(url, timeout=30)
            data = json.loads(raw)
        except Exception:
            break
        studies = data.get("studies", [])
        items.extend(_parse_study(s) for s in studies)
        next_token = data.get("nextPageToken")

    print(f"    ClinicalTrials.gov: {total} total, returning {len(items[:max_items])}")
    return items[:max_items]
