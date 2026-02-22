"""
Meta-reflection node — genuine ReAct agent for self-improvement.

This node receives the full pipeline output and runs a multi-turn
Thought → Action → Observation loop. The LLM decides which tools to
invoke (vocabulary gaps, source health, company discovery, coverage
assessment) based on what it observes in the pipeline's results.

This is the agentic meta-layer described in ADR-001. Unlike the
fixed code paths that preceded it, the LLM reasons about *whether*
and *when* to take corrective actions.

ReAct pattern:
    1. LLM receives state summary + available tools
    2. LLM responds with THOUGHT + ACTION (or FINISH)
    3. Tool is executed, producing an OBSERVATION
    4. OBSERVATION fed back to LLM for next iteration
    5. Loop until FINISH or max_iterations reached
"""
import json
import re
import datetime as dt
from typing import Any, Dict, List, Optional, Tuple

from state import HoundState
from tools.llm import create_llm, invoke_llm
from tools.meta_tools import call_tool, get_tool_descriptions
from tools.config import get_prompt, get_agent_domain

MAX_ITERATIONS = 5

FALLBACK_SYSTEM_PROMPT = """You are the NeuroTech NewsHound's meta-reflection agent. Your job is to
review the pipeline's output and decide what self-improvement actions to take.

Your domain: {domain}

=== THIS WEEK'S PIPELINE OUTPUT ===
{state_summary}

=== AVAILABLE TOOLS ===
{tool_descriptions}

=== INSTRUCTIONS ===
Think step by step about whether the pipeline's output reveals any gaps:
1. Vocabulary: Are there domain terms in high-scoring items that aren't in our vocabulary?
2. Source health: Are any sources cold or broken?
3. Coverage: Are expected topic areas represented? Any blind spots?
4. Companies: Are there new BCI companies in the web search results?

You do NOT need to use every tool. On a quiet week with good coverage, doing
nothing is the correct answer.

For each step, respond in this exact format:

THOUGHT: <your reasoning about what to check or do next>
ACTION: <tool_name>
ACTION_INPUT: <json arguments, or {{}} if the tool takes no arguments>

After the tool returns an OBSERVATION, you'll reason again.

When you're done (no more actions needed), respond with:

THOUGHT: <final summary of what you did and why>
ACTION: FINISH
ACTION_INPUT: {{"summary": "<1-2 sentence summary of all actions taken>"}}

Be concise. Be selective. More is not better."""


def meta_reflect(state: HoundState) -> HoundState:
    """
    ReAct meta-reflection: LLM reasons about pipeline output and
    decides which self-improvement tools to invoke.
    """
    scored = state.get("scored_items", [])
    if not scored:
        state["meta_actions"] = [{
            "iteration": 0,
            "thought": "No scored items — nothing to reflect on.",
            "action": "FINISH",
            "observation": "Skipped (empty pipeline output).",
        }]
        return state

    model_name = state.get("reviewer_model") or state.get("model", "gpt-4o-mini")
    print(f"\n  Meta-reflection (ReAct) with {model_name}...")
    llm = create_llm(model_name)

    state_summary = _build_state_summary(state)
    tool_descriptions = get_tool_descriptions()
    domain = get_agent_domain()

    prompt_template = get_prompt("meta_reflect", FALLBACK_SYSTEM_PROMPT)
    system_prompt = prompt_template.format(
        state_summary=state_summary,
        tool_descriptions=tool_descriptions,
        domain=domain,
    )

    meta_actions: List[Dict[str, Any]] = []
    conversation = [system_prompt]

    for iteration in range(MAX_ITERATIONS):
        full_prompt = "\n\n".join(conversation)
        response = invoke_llm(
            llm, full_prompt,
            node="meta_reflect", model_name=model_name,
        )

        thought, action, action_input = _parse_react_response(response)

        print(f"    [{iteration+1}] THOUGHT: {thought[:80]}...")
        print(f"    [{iteration+1}] ACTION: {action}")

        if action.upper() == "FINISH":
            meta_actions.append({
                "iteration": iteration + 1,
                "thought": thought,
                "action": "FINISH",
                "action_input": action_input,
                "observation": action_input.get("summary", "Done."),
            })
            break

        observation = call_tool(action, action_input, state)
        print(f"    [{iteration+1}] OBSERVATION: {observation[:100]}...")

        meta_actions.append({
            "iteration": iteration + 1,
            "thought": thought,
            "action": action,
            "action_input": action_input,
            "observation": observation,
        })

        conversation.append(
            f"THOUGHT: {thought}\n"
            f"ACTION: {action}\n"
            f"ACTION_INPUT: {json.dumps(action_input)}\n"
            f"OBSERVATION: {observation}"
        )

    else:
        meta_actions.append({
            "iteration": MAX_ITERATIONS,
            "thought": "Max iterations reached.",
            "action": "FINISH",
            "observation": "Stopped after maximum iterations.",
        })

    state["meta_actions"] = meta_actions

    actions_taken = [a for a in meta_actions if a["action"] not in ("FINISH",)]
    print(f"  Meta-reflection complete: {len(actions_taken)} tool calls, "
          f"{len(meta_actions)} total steps")

    return state


def _build_state_summary(state: HoundState) -> str:
    """Compact summary of the pipeline state for the meta-agent's context."""
    scored = state.get("scored_items", [])
    alerts = state.get("alerts", [])
    themes = state.get("themes") or []
    review = state.get("review") or {}

    categories = {}
    sources = {}
    for it in scored:
        cat = it.get("category", "unknown")
        categories[cat] = categories.get(cat, 0) + 1
        src = it.get("source_id", it.get("source", "unknown"))
        sources[src] = sources.get(src, 0) + 1

    lines = [
        f"Items scored: {len(scored)}",
        f"Alerts (9-10): {len(alerts)}",
        f"Themes: {len(themes)}",
        f"Categories: {', '.join(f'{k}={v}' for k, v in sorted(categories.items(), key=lambda x: -x[1]))}",
        f"Sources: {', '.join(f'{k}={v}' for k, v in sorted(sources.items(), key=lambda x: -x[1]))}",
    ]

    if review and review.get("assessment"):
        lines.append(f"Reviewer assessment: {review.get('assessment')} (quality: {review.get('quality_score', '?')}/10)")
        missed = review.get("missed_signals", [])
        if missed:
            lines.append(f"Reviewer missed signals: {', '.join(str(m) for m in missed)}")

    if themes:
        lines.append("Theme names: " + ", ".join(t.get("name", "?") for t in themes))

    top_items = scored[:5]
    if top_items:
        lines.append("Top 5 items:")
        for it in top_items:
            lines.append(f"  [{it.get('llm_score', '?')}] {it.get('title', '')[:80]} ({it.get('category', '?')})")

    return "\n".join(lines)


def _parse_react_response(response: str) -> Tuple[str, str, Dict]:
    """Parse the LLM's ReAct-formatted response into components."""
    thought = ""
    action = "FINISH"
    action_input = {}

    thought_match = re.search(r"THOUGHT:\s*(.+?)(?=\nACTION:|\Z)", response, re.DOTALL)
    if thought_match:
        thought = thought_match.group(1).strip()

    action_match = re.search(r"ACTION:\s*(.+?)(?=\nACTION_INPUT:|\Z)", response, re.DOTALL)
    if action_match:
        action = action_match.group(1).strip()

    input_match = re.search(r"ACTION_INPUT:\s*(.+?)(?=\nTHOUGHT:|\nOBSERVATION:|\Z)", response, re.DOTALL)
    if input_match:
        raw = input_match.group(1).strip()
        try:
            if "```json" in raw:
                raw = raw.split("```json")[1].split("```")[0]
            elif "```" in raw:
                raw = raw.split("```")[1].split("```")[0]
            action_input = json.loads(raw)
        except (json.JSONDecodeError, IndexError):
            action_input = {"raw": raw}

    return thought, action, action_input
