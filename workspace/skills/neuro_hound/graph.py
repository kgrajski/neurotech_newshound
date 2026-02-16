"""
LangGraph workflow for the NeuroTech Hound agent.

Architecture:
    fetch_pubmed → fetch_rss → prefilter → [conditional] → score_items
        → summarize_themes → write_brief → review → END

The conditional edge after prefilter skips LLM nodes if nothing is in-scope,
saving cost on quiet weeks.

Design Patterns:
    - Sequential Chain with Reflection (same as trading_etf analyst)
    - Conditional edge for cost control
    - Two-stage scoring: regex pre-filter → LLM assessment
"""
from langgraph.graph import StateGraph, END

from state import HoundState
from nodes.fetch import fetch_pubmed, fetch_rss
from nodes.prefilter import prefilter
from nodes.score import score_items
from nodes.summarize import summarize_themes, write_brief
from nodes.review import review


def should_score(state: HoundState) -> str:
    """Conditional edge: skip LLM scoring if nothing passed pre-filter."""
    if not state.get("prefiltered_items"):
        return "skip"
    return "score"


def build_hound_graph():
    """
    Build the NeuroTech Hound workflow graph.

    Returns a compiled LangGraph ready for .invoke().
    """
    wf = StateGraph(HoundState)

    # Add nodes
    wf.add_node("fetch_pubmed", fetch_pubmed)
    wf.add_node("fetch_rss", fetch_rss)
    wf.add_node("prefilter", prefilter)
    wf.add_node("score_items", score_items)
    wf.add_node("summarize_themes", summarize_themes)
    wf.add_node("write_brief", write_brief)
    wf.add_node("review", review)

    # Define flow
    wf.set_entry_point("fetch_pubmed")
    wf.add_edge("fetch_pubmed", "fetch_rss")
    wf.add_edge("fetch_rss", "prefilter")

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
    wf.add_edge("review", END)

    return wf.compile()
