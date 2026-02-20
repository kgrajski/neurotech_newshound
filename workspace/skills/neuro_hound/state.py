"""
HoundState — the single source of truth flowing through the graph.

Minimal, explicit, typed. Each node receives the full state,
performs work, and returns partial updates.
"""
from typing import Any, Dict, List, Optional, TypedDict


class HoundState(TypedDict):
    # --- Config (set once at entry) ---
    days: int
    max_items: int
    model: str
    reviewer_model: str

    # --- Phase 1: Deterministic (no LLM) ---
    raw_items: List[Dict[str, Any]]           # Everything fetched
    prefiltered_items: List[Dict[str, Any]]   # After regex pre-filter (in-scope)
    regex_scores: Dict[str, int]              # title_hash -> regex score (for reference)

    # --- Phase 2: LLM-scored ---
    scored_items: List[Dict[str, Any]]        # Items with LLM scores + assessments
    alerts: List[Dict[str, Any]]              # Score >= 9 only

    # --- Phase 2: LLM-synthesized ---
    themes: Optional[List[Dict[str, Any]]]    # Clustered themes
    executive_brief: Optional[str]            # Markdown brief
    review: Optional[Dict[str, Any]]          # Reviewer critique + adjustments

    # --- Source management ---
    _registry: Optional[Dict[str, Any]]       # Source registry (transient, not serialized)
    source_discoveries: List[Dict[str, Any]]  # Domains discovered via Tavily
    company_discoveries: List[Dict[str, Any]] # Companies discovered via LLM analysis
    _dedup_history: Optional[Dict[str, Any]]  # Dedup history (transient, not serialized)

    # --- Metadata ---
    errors: List[str]
    usage: Dict[str, Any]                     # Token/cost tracking
