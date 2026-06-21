# first-responder

Autonomous diagnosis agent for production incidents. Given an alert, it gathers telemetry across logs, metrics, traces, deploys and runbooks, reasons over the combined signal, and returns a structured root-cause diagnosis with a proposed remediation. Diagnosis quality is measured against fault-injected scenarios with known ground truth.

```
alert ──▶ agent (query_logs · query_metrics · get_traces · query_deploys · search_runbooks) ──▶ Diagnosis
```

---

## Overview

The agent runs a bounded reason–act loop over a fixed tool surface. It receives an alert and nothing else, then iteratively selects tools, observes their results, and updates its hypothesis until it reaches a root cause or hits its call budget. Output is a typed `Diagnosis`, not free text, so every run is machine-scoreable.

Two properties define the system:

- **The tool surface is the agent's only interface to the world.** No filesystem, no shell, no direct store access. Implementations behind the tools are swappable — a deterministic simulator drives evaluation; a real observability backend drops in unchanged.
- **Ground truth is generated, not labelled.** Scenarios inject a known fault and render it into internally-consistent telemetry, so the correct root cause is known a priori and accuracy is a measured number rather than a claim.

Deterministic work — metric aggregation, timestamp alignment, trace walking, retrieval — is done in tested code behind the tools. The model is reserved for the non-deterministic judgment: which signal to pull next and what it means.

## Architecture

```
                 alert
  ┌──────────────────────────────────────────────────────┐
  │                                                      ▼
┌─────────────────┐      ┌──────────────────┐     ┌──────────────┐
│   simulator     │      │      tools       │     │    agent     │
│  Scenario       │ store│  query_logs      │◀───▶│  reason ↔    │
│   activate()  ──┼─────▶│  query_metrics   │     │  act loop    │
│   ground_truth()│      │  get_traces      │     │      │       │
│  telemetry store│      │  query_deploys   │     │      ▼       │
└───────┬─────────┘      │  search_runbooks │     │  Diagnosis   │
        │                └──────────────────┘     └──────┬───────┘
        │ ground truth (eval only)                       │ diagnosis
        ▼                                                ▼
       ┌──────────────────────────────────────────────────┐
       │   eval: score(Diagnosis, ground_truth)           │
       └──────────────────────────────────────────────────┘
```

| Component    | Responsibility                                                                                                                                |
| ------------ | --------------------------------------------------------------------------------------------------------------------------------------------- |
| `agent/`     | The reason–act loop, versioned system prompt, and the `Diagnosis` schema. Imports nothing from `simulator/`.                                  |
| `tools/`     | The sole agent↔world contract. One responsibility per tool; model-shaped return granularity; informative errors the agent can adapt to.       |
| `simulator/` | Scenario definitions and the fault→telemetry renderer. `activate()` emits agent-visible signal; `ground_truth()` emits the hidden answer key. |
| `eval/`      | Scores a `Diagnosis` against ground truth; the only caller of `ground_truth()`. Doubles as the per-run audit trail.                           |

`agent/` and `simulator/` never reference each other — they meet only at `tools/`. That seam is both the integrity boundary (the agent cannot reach the answer key) and the extensibility boundary (swap the backend, the agent is untouched).

## Tool contract

```python
query_logs(service: str, window: TimeRange, filter: str | None = None) -> list[LogEntry]
query_metrics(service: str, metric: str, window: TimeRange)            -> MetricSeries
get_traces(request_id: str | None = None, service: str | None = None)  -> list[Trace]
query_deploys(window: TimeRange)                                       -> list[DeployEvent]
search_runbooks(query: str, k: int = 5)                               -> list[RunbookChunk]
```

`query_metrics` returns a summarized series (baseline, anomaly window, percentiles) rather than raw points, keeping the context window dense with signal. Empty results are returned as structured findings, not errors — "no traces in window" is information the agent reasons with.

## Diagnosis output

```python
class Evidence(BaseModel):
    tool: str                      # which tool produced this
    query: dict                    # the call that produced it
    finding: str                   # what it established

class Diagnosis(BaseModel):
    root_cause: str
    confidence: Literal["high", "medium", "low"]
    evidence: list[Evidence]       # the trail that justifies root_cause
    proposed_fix: str
    remediation_class: Literal["rollback", "scale", "config_change", "restart", "unknown"]
```

`evidence` makes every conclusion traceable to the tool calls that support it; `remediation_class` is the scoreable projection of the free-text fix. The agent may return `confidence="low"` with an empty/partial cause when evidence is insufficient — an honest non-answer is a valid, and scored, outcome.

## The diagnosis loop

```
receive(alert)
while calls < budget:
    action = model.decide(context)        # reason: pick a tool + args, or conclude
    if action.is_conclusion:
        break
    result = tools.dispatch(action)        # act: deterministic execution
    context.append(result)                 # observe
emit Diagnosis
```

Every iteration — the model's reasoning, the tool call, its inputs and outputs — is traced, so a run is fully reconstructable post-hoc.

## Evaluation

The scorer grades each run on two axes:

- **Root cause** — strict match against the injected fault.
- **Remediation** — loose match against the known remediation class.

It also records tool-call count and the evidence path, surfacing _how_ a diagnosis was reached, not just whether it was right. The agent and the answer key meet only here, after the run completes — the graded system never had access to what it's graded against.

```
scenario              root_cause   remediation   calls
────────────────────  ──────────   ───────────   ─────
cascading_timeout         ✓            ✓            6
pool_exhaustion           ✓            ✓            8
bad_deploy                ✓            ✓            4
```

_(report format; per-scenario detail and failure traces emitted alongside)_

## Scenarios

Fault scenarios are designed so the root cause sits one or two hops from the symptom, each exercising a distinct reasoning mode and each carrying a red herring to rule out:

| Scenario            | Symptom → cause                                                         | Reasoning mode            |
| ------------------- | ----------------------------------------------------------------------- | ------------------------- |
| `cascading_timeout` | 5xx/latency on service A → downstream B latency spike (one trace hop)   | spatial / trace-following |
| `pool_exhaustion`   | intermittent failures → connection-pool saturation correlated with load | temporal correlation      |
| `bad_deploy`        | sharp error-rate onset → deploy event at the same timestamp             | event correlation         |

Telemetry is rendered programmatically from the fault model, so signal stays internally consistent and ground truth is preserved exactly.

## Project layout

```
first-responder/
├── agent/         loop.py · prompts/ · schema.py
├── tools/         logs.py · metrics.py · traces.py · deploys.py · runbooks.py
├── simulator/     scenario.py · telemetry.py · store.py · scenarios/
├── eval/          scorer.py · report.py
├── web/           run viewer
└── docs/          ARCHITECTURE.md · adr/
```

## Quickstart

```bash
git clone https://github.com/<you>/first-responder
cd first-responder
pip install -e .

# diagnose a single scenario, print the reasoning trace
first-responder diagnose --scenario cascading_timeout --trace

# score the agent across all scenarios
first-responder eval --all
```

Model provider is configured via environment; the agent is provider-agnostic behind a thin client interface.

## Design notes

The load-bearing decisions and their rationale are recorded as ADRs in [`docs/adr/`](docs/adr/) — synthetic fault injection for ground truth, the tool contract as the agent↔world boundary, and single-agent over multi-agent. System-level detail in [ARCHITECTURE.md](ARCHITECTURE.md).

## Stack

Python · pydantic (typed scenarios, tools, and output) · pytest-driven eval harness · RAG over a local runbook corpus for `search_runbooks` · provider-agnostic model client.
