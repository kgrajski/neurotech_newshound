# ADR-001: Agent Specification Architecture

**Status:** Accepted
**Date:** 2026-02-17
**Context:** NeuroTech NewsHound — agentic research intelligence

---

## Decision

This project uses a four-layer specification architecture:

| Layer | File | Authority | Consumed by |
|-------|------|-----------|-------------|
| **Identity** | `SOUL.md` | Agent personality, values, meta-goals | OpenClaw host agent (LLM) |
| **Specification** | `SKILL.md` | Complete operational spec — goals, tools, workflow, constraints | Developers + OpenClaw |
| **Configuration** | `config.yaml` | Runtime parameters — sources, watchlist, models | Python pipeline code |
| **Prompts** | `prompts.yaml` | LLM prompt templates | Python pipeline code |

## Context

Two conventions exist in the agentic AI community for specifying agent behavior:

**SOUL.md + SKILL.md** (OpenClaw and similar frameworks): SOUL.md defines
persistent agent identity shared across skills. SKILL.md defines a specific
capability. The host agent reads SOUL.md at session start, then loads the
relevant SKILL.md when a skill is invoked.

**SKILL.md only** (Anthropic / DeepLearning.ai pattern): A single SKILL.md is
the complete self-contained specification — identity, purpose, tools,
constraints, reasoning guidelines. No separate identity layer.

Neither is an industry standard. Both are conventions.

## Why We Have Both

This project is deployed on OpenClaw, which expects the `workspace/SOUL.md` +
`workspace/skills/<name>/SKILL.md` structure. We retain this structure for
deployment compatibility.

However, since we have a **single skill** (neuro_hound), the SOUL/SKILL
separation risks duplication and drift. We mitigate this by:

1. **SOUL.md is slim** — identity, values, and meta-goals only. No operational
   details, no monitoring targets, no scoring criteria.
2. **SKILL.md is comprehensive** — a developer can read SKILL.md alone and
   understand the agent's complete behavior. It cross-references SOUL.md for
   identity rather than duplicating it.
3. **config.yaml is the single source of truth** for all runtime parameters.
   Neither SOUL.md nor SKILL.md contains lists of companies, sources, or
   queries that could drift from the actual configuration.
4. **prompts.yaml is the single source of truth** for LLM behavior. Prompt
   text is logged to MLflow, enabling A/B iteration independent of code or
   spec changes.

## The Honesty Gap: Procedural vs. Agentic

SOUL.md describes meta-goals ("discover new companies," "curate sources,"
"self-assess coverage"). SKILL.md documents these as explicit goals.

The current implementation of these meta-capabilities is **procedural, not
agentic**:

- Company discovery is a fixed function that always runs after the review node
- Source health monitoring is a counter-based mechanism, not LLM reasoning
- The agent does not read SOUL.md or SKILL.md at runtime
- The agent does not reason about *whether* to pursue its meta-goals

This is documented in SKILL.md's Evolution table. The path to genuine agency
would involve a ReAct-style meta-reflection node that receives the pipeline's
output and *decides* which tools to invoke based on observed gaps — rather than
following a fixed code path.

We are honest about this gap because:
- Most production "AI agents" operate at this level (LLM-augmented pipelines)
- Claiming agentic behavior we don't have would not withstand critical review
- Documenting the roadmap shows architectural intent and invites contribution

## Consequences

**Positive:**
- Clear separation of concerns — each file has one job
- No duplication of operational data between spec and config
- Honest about the current level of agency
- Compatible with OpenClaw deployment model
- SKILL.md is readable as a standalone specification

**Negative:**
- Two spec files (SOUL.md + SKILL.md) for a single-skill agent is more
  ceremony than strictly necessary
- SOUL.md is only consumed by the OpenClaw host agent; when running locally,
  it has no effect on pipeline behavior
- The meta-goals in SOUL.md and SKILL.md are aspirational — the code does not
  enforce them through agent reasoning

## Alternatives Considered

**SKILL.md only (Anthropic pattern):** Would eliminate SOUL.md and consolidate
everything into SKILL.md. Cleaner for a single-skill agent, but breaks OpenClaw
deployment conventions and loses the identity/capability separation that would
matter if we add skills later.

**SOUL.md as runtime config:** Have the Python pipeline read SOUL.md and extract
monitoring targets, scoring criteria, etc. Rejected because YAML (config.yaml)
is better suited for structured data than Markdown, and it would create a
fragile parsing dependency.

**No specification files:** Rely entirely on config.yaml + code comments.
Rejected because agent specifications serve both human readers and LLM host
agents — they're documentation *and* instructions.

---

_This ADR follows the format described by Michael Nygard in
[Documenting Architecture Decisions](https://cognitect.com/blog/2011/11/15/documenting-architecture-decisions)._
