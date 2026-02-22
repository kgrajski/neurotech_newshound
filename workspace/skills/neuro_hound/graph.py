"""
LangGraph workflow for the NeuroTech NewsHound agent.

Architecture:
    fetch_pubmed → fetch_clinicaltrials → fetch_rss → fetch_tavily → save_registry
        → prefilter → [conditional] → score_items
        → summarize_themes → write_brief → review → meta_reflect → END

Sources are registry-driven (sources.json):
    - PubMed (API), ClinicalTrials.gov (API), RSS feeds (journals, preprints, press, regulatory), Tavily (wideband)
    - Source stats updated per run for yield tracking and pruning

Design Patterns:
    - Sequential Chain with Reflection (same as trading_etf analyst)
    - Conditional edge for cost control
    - Two-stage scoring: regex pre-filter → LLM assessment
    - Source registry with auto-discovery and cold-source pruning
    - ReAct meta-reflection: LLM reasons about self-improvement after pipeline
"""
from langgraph.graph import StateGraph, END

from state import HoundState
from nodes.fetch import fetch_pubmed, fetch_clinicaltrials, fetch_rss, fetch_tavily, save_registry
from nodes.prefilter import prefilter
from nodes.score import score_items
from nodes.summarize import summarize_themes, write_brief
from nodes.review import review
from nodes.meta_reflect import meta_reflect


def should_score(state: HoundState) -> str:
    """Conditional edge: skip LLM scoring if nothing passed pre-filter."""
    if not state.get("prefiltered_items"):
        return "skip"
    return "score"


def build_hound_graph():
    """
    Build the NeuroTech NewsHound workflow graph.

    Returns a compiled LangGraph ready for .invoke().
    """
    wf = StateGraph(HoundState)

    # Fetch nodes (no LLM cost, except Tavily which is ~$0.001/search)
    wf.add_node("fetch_pubmed", fetch_pubmed)
    wf.add_node("fetch_clinicaltrials", fetch_clinicaltrials)
    wf.add_node("fetch_rss", fetch_rss)
    wf.add_node("fetch_tavily", fetch_tavily)
    wf.add_node("save_registry", save_registry)

    # Analysis nodes
    wf.add_node("prefilter", prefilter)
    wf.add_node("score_items", score_items)
    wf.add_node("summarize_themes", summarize_themes)
    wf.add_node("write_brief", write_brief)
    wf.add_node("review", review)
    wf.add_node("meta_reflect", meta_reflect)

    # Define flow: fetch cascade → prefilter → conditional → LLM pipeline
    wf.set_entry_point("fetch_pubmed")
    wf.add_edge("fetch_pubmed", "fetch_clinicaltrials")
    wf.add_edge("fetch_clinicaltrials", "fetch_rss")
    wf.add_edge("fetch_rss", "fetch_tavily")
    wf.add_edge("fetch_tavily", "save_registry")
    wf.add_edge("save_registry", "prefilter")

    # Conditional: skip LLM if nothing in-scope
    wf.add_conditional_edges(
        "prefilter",
        should_score,
        {"score": "score_items", "skip": END},
    )

    # LLM pipeline
    wf.add_edge("score_items", "summarize_themes")
    wf.add_edge("summarize_themes", "write_brief")
    wf.add_edge("write_brief", "review")
    wf.add_edge("review", "meta_reflect")
    wf.add_edge("meta_reflect", END)

    return wf.compile()
