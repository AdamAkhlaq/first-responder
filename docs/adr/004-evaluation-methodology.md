# ADR-004 — Evaluating a non-deterministic agent: N-trial scoring

**Status:** Accepted · **Date:** 2026-06-22

## Context and forces

The agent's only non-deterministic component is the model; the simulator, tools, and scorer are seeded and pure (invariant I3). A single run is therefore a _sample_, not a verdict, which puts three forces in tension:

- **Statistical reliability** — more trials per scenario give a more trustworthy number.
- **Cost and latency** — each trial is a full agent run (multiple model calls × tokens); eval spend scales with trials × scenarios.
- **CI usefulness** — the gate must be stable enough that a failure means a real regression, not model noise.

The scoring rubric itself is settled (root cause strict; remediation class loose; plus evidence-path coverage and tool-call count). This decision is about how to aggregate those across stochastic runs, and what counts as a regression.

## Decision

Run each scenario _N_ times per evaluation and report, per axis, the **pass rate and its variance** — never a single pass/fail. A change is a regression when a scenario's pass rate falls below its committed baseline by more than the trial-to-trial noise band; CI fails on that condition. Provider, model, temperature, and seed (where supported) are pinned and recorded with every result, so each number is attributable to an exact configuration.

`N` starts small (≈5–10 per scenario) — a deliberate signal-vs-cost knob, raised for axes or scenarios that prove noisy.

## Consequences

Positive:

- A one-off flip reads as noise; a shifted distribution reads as a regression. The CI gate means something.
- Reporting variance alongside pass rate surfaces an unreliable agent that a healthy average would otherwise hide.
- Every result is reproducible-to-configuration, even though individual runs are not.

Negative / accepted costs:

- **Eval cost grows linearly** with N × scenarios × per-run model calls; the suite carries a real, recurring spend.
- The noise band from small N is itself approximate — a pragmatic threshold, not a rigorous statistical guarantee.
- The gate is probabilistic: a borderline regression can occasionally slip under it, or a healthy change occasionally trip it. The noise band mitigates this; it does not eliminate it.

## Alternatives considered

- **Single-pass scoring** (one run, pass/fail) — rejected: mistakes a sample for a verdict, producing a CI gate too flaky to trust.
- **Forced determinism** (temperature 0 + pinned seed) — rejected as the primary method: providers don't guarantee reproducibility, seed support is inconsistent, and freezing one sampling path doesn't reflect real behaviour. Retained only as an optional low-variance smoke check.
- **LLM-as-judge for the core axes** — rejected: ground truth is known exactly from the injected fault, so a deterministic programmatic scorer is cheaper and more reliable, and a judge would inject its own non-determinism and bias into the measurement.

## Revisit when

The suite grows enough that N × scenarios makes CI a bottleneck — at which point a tiered run (fast subset per PR, full suite nightly) or adaptive N is warranted; or when the stakes justify a more formal statistical treatment (confidence intervals, sequential tests).
