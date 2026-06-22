# ADR-003 — A single agent, not a multi-agent architecture

**Status:** Accepted · **Date:** 2026-06-22

## Context and forces

The reflexive design for "diagnose an incident" is to decompose into specialist sub-agents — logs, metrics, traces — behind an orchestrator. The forces actually at play: diagnosis is cross-cutting (the insight is the _connection_ between signals), debuggability matters, latency and token cost matter, and there is fashion pressure toward multi-agent designs that look sophisticated.

## Decision

One agent, with access to all tools, reasoning over a single shared context. No sub-agents, no orchestrator.

## Consequences

Positive:

- **Cross-signal reasoning stays intact.** The cascading-timeout scenario is solved by connecting a log symptom to a trace edge to a downstream metric; a single context is where that connection can be made.
- **One debugging surface** — one loop, one context, one trace to read when a run goes wrong.
- **Lower latency and token overhead** — no inter-agent message-passing or repeated context rehydration.

Negative / accepted costs:

- **The single context is a finite budget,** so context curation becomes load-bearing (see ARCHITECTURE: the diagnosis loop) rather than something a multi-agent split would have partitioned for free.
- **No natural parallelism** across signals; investigation is sequential by construction.

## Alternatives considered

- **Orchestrator + per-signal specialists** — rejected: puts walls exactly where the reasoning needs to flow, adds a coordination layer whose only job is to undo the split, and multiplies the surface for lost context and non-determinism — with no offsetting benefit at this scale.

## Revisit when

A capability provably requires isolation — for example a sandboxed sub-task whose output must be treated as untrusted — and that need can be named concretely rather than anticipated speculatively. The least-machinery principle is the bar any such change must clear.
