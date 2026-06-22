# ADR-002 — Tools layer as the sole agent–world contract

**Status:** Accepted · **Date:** 2026-06-22

## Context and forces

The agent needs telemetry to diagnose anything. How that access is structured determines four things at once: whether the agent is testable, whether the evaluation can be trusted, how hard it is to point at real systems later, and how well the model reasons. These pull in the same direction if access is mediated by a narrow contract, and against each other if it isn't.

## Decision

All access between the agent and the world goes through a small, fixed set of tools (`query_logs`, `query_metrics`, `get_traces`, `query_deploys`, `search_runbooks`). The surface is read-only, side-effect-free, and deterministic given a populated store. The agent has no other reach — no file, shell, network, or store access.

This is ports-and-adapters: the agent is the core, each tool is a port, and implementations (simulator today, real backend later) are adapters at the edge.

## Consequences

Positive:

- **Swappable data plane.** The implementation behind a tool changes without touching the agent.
- **Integrity boundary.** Because the agent can only call these tools, it cannot reach the ground-truth answer key (invariant I1). Leakage is prevented here, in code — the eval harness is the only caller of `ground_truth()` — not by repository layout, which would add nothing since scoring must co-locate output and answer regardless.
- **Testable determinism.** Aggregation, correlation and trace-walking live in the tools as ordinary, unit-tested code, out of the model where they can't be hallucinated.

Negative / accepted costs:

- **The contract is now a versioned interface** with its own backward-compatibility burden; changing a return shape is a breaking change to the agent.
- **Every capability must be expressed as a tool.** This is a deliberate constraint on how the agent can grow, and occasionally a friction.
- **Return granularity encodes product judgment.** Summarising a metric series (rather than returning raw points) keeps context dense but bakes a decision into the tool layer that could bias the agent; the summary must preserve the signal a human would use.

## Alternatives considered

- **Direct store/database access from the agent** — rejected: couples the agent to the data layer and destroys the integrity boundary.
- **A single generic `query` tool** — rejected: too unconstrained to design good granularity or error semantics around, and harder for the model to use well.
- **MCP from day one** — deferred: premature before the capability vocabulary is stable; adopting it later (behind this same contract) is the planned path.

## Revisit when

Real backends are added. That is the point to formalise the capability vocabulary and likely adopt MCP as the inbound protocol — without changing the agent, since it only ever sees the contract.
