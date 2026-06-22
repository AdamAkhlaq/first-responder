# Architecture

first-responder is a bounded reason–act agent whose autonomy is constrained by a fixed tool contract and whose output quality is measured against generated ground truth. The design is organised around a small set of invariants; most of the engineering exists to enforce them. This document covers what the system guarantees, how it's structured, and the decisions and failure modes that shaped it.

Data flow: `Scenario.activate()` populates a telemetry store; the agent reads it only through the tools layer, loops to a structured `Diagnosis`, and the eval harness scores that against `Scenario.ground_truth()` — which the agent never sees.

## Invariants

These hold by construction. Everything below enforces one of them.

|        | Invariant                                                                                                 | Enforced by                                                                 |
| ------ | --------------------------------------------------------------------------------------------------------- | --------------------------------------------------------------------------- |
| **I1** | The agent's only I/O with the world is the tool surface — no filesystem, shell, network, or store access. | No such tool exists; the agent is constructed with an explicit tool list.   |
| **I2** | `ground_truth()` is read only by the eval harness, and only after a run completes.                        | Single call site; the agent's context is assembled without it.              |
| **I3** | Telemetry is a pure function of `(fault, seed)` — every run is reproducible.                              | Programmatic rendering; no wall-clock or RNG outside the seeded generator.  |
| **I4** | Every claim in a `Diagnosis` cites evidence that traces to a real tool result.                            | `evidence[]` references logged tool calls; the scorer verifies the linkage. |
| **I5** | A run terminates.                                                                                         | Hard caps on tool calls and wall-clock in the loop.                         |

## Principles

- **Least autonomy that solves the problem.** This is an agent only because the number of hops and the order of investigation are data-dependent. Any fixed-workflow subset is implemented as a tool, not as agent reasoning.
- **The model is the only stochastic component, and its surface is minimised.** Aggregation, correlation, timestamp math, trace-walking and retrieval are deterministic code behind tools. The model is reserved for judgment: what to look at next and what it means.
- **One agent, one context, one loop.** Diagnosis is cross-cutting; splitting signals across agents puts walls where reasoning must flow. (ADR-003.)
- **Measure, don't assert.** The eval harness and scenarios exist alongside the agent so every prompt or tool change is a scored diff.
- **An un-inspectable run is an un-debuggable one.** Full structured tracing is a build requirement, not an add-on.

## Components

Each component is a subpackage of the importable `first_responder/` package, with one responsibility and an explicit contract.

| Component                    | Owns                                                           | Must not                                                                    | Contract                                                                   |
| ---------------------------- | -------------------------------------------------------------- | --------------------------------------------------------------------------- | -------------------------------------------------------------------------- |
| `first_responder/agent/`     | The loop, the versioned system prompt, the `Diagnosis` schema. | Import from `first_responder/simulator/`; know that telemetry is synthetic. | In: alert + tool handles. Out: `Diagnosis`.                                |
| `first_responder/tools/`     | The sole agent↔world interface.                                | Mutate state; expose raw stores; leak ground truth.                         | Typed, read-only, side-effect-free, deterministic given a populated store. |
| `first_responder/simulator/` | Scenario definitions; the fault→telemetry renderer.            | Encode the verdict verbatim in agent-visible signal.                        | `activate() -> (telemetry, alert)`; `ground_truth() -> GroundTruth`.       |
| `first_responder/eval/`      | Scoring and the run report; the audit trail.                   | Influence a run in progress.                                                | In: `Diagnosis` + `GroundTruth`. Out: scored result + trace.               |

The agent and simulator packages never reference each other; they meet only at the tools layer. That seam is simultaneously the integrity boundary (I1) and the extensibility boundary (the data plane behind the tools is swappable).

## The tool contract

```python
query_logs(service: str, window: TimeRange, filter: str | None = None) -> list[LogEntry]
query_metrics(service: str, metric: str, window: TimeRange)            -> MetricSeries
get_traces(request_id: str | None = None, service: str | None = None)  -> list[Trace]
query_deploys(window: TimeRange)                                       -> list[DeployEvent]
search_runbooks(query: str, k: int = 5)                               -> list[RunbookChunk]
```

Semantics that matter:

- **Granularity is a product decision, made here.** `query_metrics` returns a summarised series (baseline, anomaly window, percentiles), not raw points — this keeps the context dense and forces reasoning over _shape_ rather than scanning. The trade-off is acknowledged in ADR-002: summarisation bakes judgment into the tool layer and could bias the agent, so the summary must preserve the signal a human would use.
- **Errors are values.** "No traces in window" is a structured finding, not an exception. Absence is frequently diagnostic (e.g. a service that stopped emitting), so the agent must be able to reason about it.
- **Time is scenario-relative.** Every scenario has an incident origin `T0`; windows are expressed relative to it against a synthetic clock. There is no real `now`, which is part of what makes runs reproducible (I3).
- **Reads are pure.** No tool mutates the store. This makes runs replayable and makes the read/write trust split (deferred remediation) a clean future boundary rather than a refactor.

## The diagnosis loop

```
ctx = [alert]
while calls < CALL_BUDGET and elapsed < TIME_BUDGET:
    step = model.decide(ctx)          # reason: choose a tool+args, or conclude
    if step.is_conclusion: break
    result = tools.dispatch(step)     # act: deterministic, traced
    ctx = curate(ctx + [result])      # observe + manage context budget
emit Diagnosis(... , evidence=ledger)
```

- **Termination (I5)** is a conclusion or a budget. The budget is also a quality signal: a correct diagnosis reached in 4 calls is worth more than one reached in 14, and the report records it.
- **Context management is load-bearing, not incidental.** A single context is finite, and quality degrades as it fills with raw tool output. `curate` keeps the alert, the current hypothesis, and the recent observation window verbatim, and compresses older observations to their findings. This is the cost of the single-agent decision (ADR-003) and is treated as a first-class concern, not left to chance.
- **State** is the working hypothesis plus an append-only evidence ledger; the ledger becomes `Diagnosis.evidence` and underwrites I4.

## Reproducibility and the stochastic boundary

The model is the only non-deterministic part of the system; everything else is seeded and pure. Two consequences follow, and both shape how results are interpreted:

- **A single run is a sample, not a verdict.** The eval harness runs each scenario _N_ times and reports pass rate and variance per axis, not a single ✓/✗. Regressions are detected against the distribution; a one-off flip is noise, a shifted distribution is a regression. (ADR-004.)
- **Runs are attributable.** Provider, model, temperature and (where the provider supports it) seed are pinned and recorded with every result, so an accuracy number is always tied to the exact configuration that produced it.

## Eval validity — a threat model

The measurement is worthless if the graded system can see the answer. Leakage vectors considered, and how each is closed:

- **Direct access** — closed by I1 (no file/shell tool) and I2 (`ground_truth()` has one call site, outside the agent's context assembly).
- **Telemetry that states the answer** — a generated log line literally naming the root cause would let the agent read, not reason. Scenario acceptance requires that the verdict is never present verbatim in agent-visible signal; the cause must be inferable but not stated. This is a review gate on every scenario.
- **Lucky guesses with fabricated justification** — closed by I4: the scorer verifies that cited evidence corresponds to tool results actually returned during the run, so a correct `root_cause` backed by invented evidence does not score as a clean pass.

Enforcement is in code and review, not convention; convention does not survive contributors.

## Observability

Every run emits one structured trace: an ordered sequence of `{step, model_reasoning, tool, args, result_digest, latency_ms, tokens}`, plus the final `Diagnosis` and score. This single artifact serves three purposes — the debugging surface during development, the audit trail behind every eval score, and the demo view. Building it once, well, is cheaper than three bespoke views.

## Evaluation methodology

Two outcome axes, scored independently so the fuzzy one cannot contaminate the strict one:

- **Root cause** — strict equality against the injected fault.
- **Remediation class** — loose match against the known class (`rollback` / `scale` / `config_change` / `restart`).

Plus process metrics that catch shallow reasoning a binary outcome would miss: tool-call count, **evidence-path coverage** (did the run touch the minimum evidence set the scenario declares?), and wall-clock. A run can reach the right cause by luck while skipping the evidence path; the coverage metric surfaces that. The scenarios are the regression suite, and the harness is wired as a CI gate: a change that drops pass rate below the recorded baseline fails the build.

## Failure modes

| Mode                                      | Mitigation                                                                          |
| ----------------------------------------- | ----------------------------------------------------------------------------------- |
| Fixation on the first symptom             | Scenarios plant red herrings; evidence-path coverage exposes premature conclusions. |
| Runaway loop                              | Call and wall-clock budgets (I5).                                                   |
| Empty / edge-case tool result             | Errors-as-values; absence is a reasonable-about finding.                            |
| Hallucinated evidence                     | Evidence-citation verification (I4).                                                |
| Provider change or outage                 | Provider-agnostic client; configuration pinned and recorded per run.                |
| Context degradation on long runs          | Explicit `curate` step; older observations compressed to findings.                  |
| Stochastic flakiness read as a regression | N-trial distribution rather than a point estimate.                                  |

## Extensibility — considered evolution

The boundaries were drawn knowing where they'd move:

- **Real backends** drop in behind the tool contract as adapters; the simulator is the reference implementation of the data plane, not a special case.
- **Remediation** is a future _write_ tier, kept distinct from reads by design: dry-run by default, an action allowlist, plan → approve → execute, and an audit record. The current tooling is read-only, which is why the read/write split is a clean seam rather than a rewrite. Closing the loop also requires the simulator to model system _dynamics_ (does a metric recover after a fix?), which the current static fault model does not.
- **An open connector ecosystem** would adopt MCP as the inbound protocol with a thin capability vocabulary mapped via ports-and-adapters; the eval harness becomes the connector conformance suite — a new adapter must pass the scenarios to be trusted.

## Non-goals (current)

- **Multi-agent orchestration** — severs cross-signal reasoning for no benefit at this scale (ADR-003).
- **Remediation execution** — a different and higher-risk system; reads first, writes later, gated.
- **Real telemetry ingestion** — would forfeit the reproducible ground truth that makes evaluation possible (ADR-001).

## Decision records

The load-bearing decisions, their forces, and their honest consequences are in [`docs/adr/`](docs/adr/). Read those for _why_ the system is shaped this way.
