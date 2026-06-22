# ADR-001 — Synthetic fault injection as the ground-truth source

**Status:** Accepted · **Date:** 2026-06-22

## Context and forces

Evaluation is the hard part of any diagnosis system: a proposed root cause is only meaningful if it can be checked against a known-correct one. Several forces are in tension:

- **Measurability.** Quality must be a number with a trend, not a claim — which requires labelled incidents.
- **Availability.** Real production telemetry cannot be used here, and public incident data rarely pairs a write-up with the raw signal needed to _reason_ rather than read a conclusion.
- **Reproducibility.** Comparing prompt and tool changes requires that the same scenario produces the same telemetry every time.
- **Validity.** Generated data must be realistic enough to demand reasoning, and must not encode the answer.

## Decision

Generate incidents by injecting known faults. A `Scenario` defines a fault, renders it deterministically into telemetry as a function of `(fault, seed)`, and records the correct root cause, remediation class, and minimum evidence path as `ground_truth()`.

## Consequences

Positive:

- Labels are free and exact; accuracy becomes measurable and regression-testable.
- Runs are reproducible (telemetry has no wall-clock or unseeded RNG), so eval is stable enough to attribute changes to.
- The scenarios later double as a conformance suite for real-data connectors.

Negative / accepted costs:

- **Realism is now an engineering burden and a standing validity risk.** Telemetry must be layered enough that the cause sits one or two hops from the symptom; a scenario that states the answer in a log line measures nothing. This is a per-scenario review gate, not a one-time effort.
- **Coverage is not the real-world distribution.** The agent is only as good as scenario diversity; strong eval numbers are evidence under the scenarios tested, not a guarantee in production. This is stated honestly rather than papered over.

## Alternatives considered

- **Public incident datasets / post-mortems** — rejected: inconsistent structure, and seldom shipped with the raw telemetry required to reason.
- **Hand-labelled real logs** — unavailable (the originating constraint).
- **LLM-generated telemetry end-to-end** — rejected: severs the deterministic link between fault and signal, breaking reproducibility (I3) and ground-truth integrity. An LLM may add surface variety, never the underlying numbers.

## Revisit when

Anonymised real telemetry becomes available. At that point synthetic injection becomes a _complement_ — a controlled conformance layer — rather than the sole source of truth.
